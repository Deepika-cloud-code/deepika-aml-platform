
"""Incremental Bronze-to-Silver AML transformation pipeline."""

import json
import math
import sqlite3
from datetime import datetime, timezone

from aml.core import connect


def create_silver_tables(db):
    db.execute("""
        CREATE TABLE IF NOT EXISTS silver_transactions (
            event_id TEXT PRIMARY KEY,
            transaction_id TEXT NOT NULL,
            source TEXT NOT NULL,
            network TEXT,
            event_time TEXT,
            ingested_at TEXT NOT NULL,
            status TEXT,
            amount_usd REAL,
            amount_btc REAL,
            fee_btc REAL,
            sender_address TEXT,
            receiver_address TEXT,
            customer_id TEXT,
            is_synthetic INTEGER NOT NULL,
            processed_at TEXT NOT NULL
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS silver_rejections (
            event_id TEXT PRIMARY KEY,
            source TEXT,
            reason TEXT NOT NULL,
            rejected_at TEXT NOT NULL
        )
    """)

    db.execute("""
        CREATE INDEX IF NOT EXISTS idx_silver_source_time
        ON silver_transactions(source, event_time)
    """)


def parse_amount(value, field):
    if value is None:
        return None

    if isinstance(value, bool):
        raise ValueError(f"{field} must be numeric")

    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"Invalid {field}: {value}") from None

    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{field} must be finite and non-negative")

    return result


def first_address(value):
    if isinstance(value, list):
        return next(
            (v for v in value if isinstance(v, str) and v),
            None
        )
    return None


def validate_timestamp(value):
    if value is None:
        return None

    if not isinstance(value, str):
        raise ValueError("event_time must be an ISO timestamp")

    try:
        parsed = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
    except ValueError:
        raise ValueError("Invalid event_time") from None

    if parsed.tzinfo is None:
        raise ValueError("event_time must include timezone")

    return parsed.astimezone(timezone.utc).isoformat()


def transform_record(row):
    """Validate and normalize one Bronze event."""

    event = json.loads(row["payload"])

    if not isinstance(event, dict):
        raise ValueError("Payload must be a JSON object")

    if event.get("schema_version") != "1.0":
        raise ValueError("Unsupported schema version")

    event_id = row["event_id"]
    source = row["source"]

    if event.get("event_id") != event_id:
        raise ValueError("Bronze and payload event_id mismatch")

    if event.get("source") != source:
        raise ValueError("Bronze and payload source mismatch")

    transaction_id = event.get("transaction_id")

    if not transaction_id and source == "blockstream_esplora":
        transaction_id = event_id.removeprefix("bitcoin:")

    if not isinstance(transaction_id, str) or not transaction_id:
        raise ValueError("Missing transaction_id")

    is_synthetic = event.get("is_synthetic", False)

    if not isinstance(is_synthetic, bool):
        raise ValueError("is_synthetic must be boolean")

    if source == "synthetic_banking" and not is_synthetic:
        raise ValueError("Synthetic source incorrectly labeled")

    if source == "blockstream_esplora" and is_synthetic:
        raise ValueError("Live Bitcoin source incorrectly labeled")

    amount_usd = parse_amount(
        event.get("amount_usd"), "amount_usd"
    )

    amount_btc = parse_amount(
        event.get("output_btc"), "output_btc"
    )

    fee_btc = parse_amount(
        event.get("fee_btc"), "fee_btc"
    )

    # A banking event's output_btc=0 is a placeholder.
    if source == "synthetic_banking":
        amount_btc = None

    if source == "synthetic_banking" and amount_usd is None:
        raise ValueError("Banking amount_usd is missing")

    if source == "blockstream_esplora" and amount_btc is None:
        raise ValueError("Bitcoin output_btc is missing")

    now = datetime.now(timezone.utc).isoformat()

    return (
        event_id,
        transaction_id,
        source,
        event.get("network"),
        validate_timestamp(event.get("event_time")),
        row["ingested_at"],
        event.get("status"),
        amount_usd,
        amount_btc,
        fee_btc,
        first_address(event.get("input_addresses")),
        first_address(event.get("output_addresses")),
        event.get("customer_id"),
        int(is_synthetic),
        now,
    )


def run_silver_pipeline():
    processed = 0
    rejected = 0

    with connect() as db:
        create_silver_tables(db)

        # Process each Bronze event only if it has no
        # Silver record and no recorded rejection.
        rows = db.execute("""
            SELECT b.*
            FROM bronze b
            LEFT JOIN silver_transactions s
                ON b.event_id = s.event_id
            LEFT JOIN silver_rejections r
                ON b.event_id = r.event_id
            WHERE s.event_id IS NULL
              AND r.event_id IS NULL
            ORDER BY b.ingested_at, b.event_id
        """).fetchall()

        for row in rows:
            try:
                values = transform_record(row)

                db.execute("""
                    INSERT INTO silver_transactions (
                        event_id, transaction_id, source, network,
                        event_time, ingested_at, status,
                        amount_usd, amount_btc, fee_btc,
                        sender_address, receiver_address,
                        customer_id, is_synthetic, processed_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, values)

                processed += 1

            except (
                ValueError,
                TypeError,
                KeyError,
                json.JSONDecodeError,
                sqlite3.IntegrityError
            ) as exc:
                db.execute("""
                    INSERT INTO silver_rejections
                        (event_id, source, reason, rejected_at)
                    VALUES (?, ?, ?, ?)
                """, (
                    row["event_id"],
                    row["source"],
                    str(exc),
                    datetime.now(timezone.utc).isoformat()
                ))
                rejected += 1

        db.commit()

    print(f"Silver records created: {processed}")
    print(f"Rejected records: {rejected}")

    return processed, rejected


if __name__ == "__main__":
    run_silver_pipeline()
