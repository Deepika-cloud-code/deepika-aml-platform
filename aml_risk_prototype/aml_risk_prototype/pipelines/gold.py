
"""Gold layer: Banking and multi-factor Bitcoin AML detection."""

import json
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from aml.core import connect
from detection.bitcoin_rules import score_bitcoin_transaction


RULE_VERSION = "2.0"
BANKING_ALERT_THRESHOLD = 30


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def parse_time(value):
    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
        if parsed.tzinfo is None:
            return None

        return parsed.astimezone(timezone.utc)
    except (ValueError, AttributeError):
        return None


def risk_level(score):
    if score >= 80:
        return "CRITICAL"
    if score >= 60:
        return "HIGH"
    if score >= 30:
        return "MEDIUM"
    return "LOW"


def create_gold_tables(db):
    db.execute("""
        CREATE TABLE IF NOT EXISTS gold_risk_scores (
            event_id TEXT PRIMARY KEY,
            transaction_id TEXT NOT NULL,
            source TEXT NOT NULL,
            customer_id TEXT,
            amount_usd REAL,
            amount_btc REAL,
            risk_score INTEGER NOT NULL,
            risk_level TEXT NOT NULL,
            triggered_rules TEXT NOT NULL,
            rule_version TEXT NOT NULL,
            scored_at TEXT NOT NULL
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS gold_aml_alerts (
            alert_id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL UNIQUE,
            customer_id TEXT,
            risk_score INTEGER NOT NULL,
            severity TEXT NOT NULL,
            explanation TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'OPEN',
            created_at TEXT NOT NULL
        )
    """)


def score_banking(row, customer_history):
    """Existing banking rules R001, R002 and R003."""

    score = 0
    rules = []

    usd = row["amount_usd"]
    customer = row["customer_id"]

    if usd is not None and usd >= 25000:
        score += 40
        rules.append({
            "rule": "R001",
            "reason": "High-value banking transaction",
            "points": 40
        })

    current_time = parse_time(row["event_time"])

    if customer and current_time:
        history = customer_history[customer]
        cutoff = current_time - timedelta(hours=24)

        while history and history[0][0] < cutoff:
            history.popleft()

        recent = list(history) + [(current_time, usd)]

        if len(recent) >= 5:
            score += 30
            rules.append({
                "rule": "R002",
                "reason": "At least 5 customer transactions in 24h",
                "points": 30
            })

        near_threshold = sum(
            1
            for _, amount in recent
            if amount is not None
            and 8000 <= amount < 10000
        )

        if near_threshold >= 3:
            score += 45
            rules.append({
                "rule": "R003",
                "reason": "Repeated near-threshold transactions",
                "points": 45
            })

        history.append((current_time, usd))

    score = min(score, 100)
    return score, rules, score >= BANKING_ALERT_THRESHOLD


def score_bitcoin(row, raw_event, bitcoin_history):
    """Use the new four-factor Bitcoin rule engine."""

    observation_time = (
        parse_time(row["event_time"])
        or parse_time(row["ingested_at"])
    )

    if observation_time is None:
        raise ValueError(
            f"No valid timestamp for {row['event_id']}"
        )

    input_addresses = raw_event.get("input_addresses") or []

    event = {
        "observation_time": observation_time,
        "output_btc": row["amount_btc"],
        "output_count": raw_event.get("output_count"),
        "input_addresses": input_addresses
    }

    score, rules, should_alert = score_bitcoin_transaction(
        event,
        bitcoin_history
    )

    bitcoin_history.append({
        "event_time": observation_time,
        "addresses": set(input_addresses),
        "amount_btc": float(row["amount_btc"] or 0)
    })

    return score, rules, should_alert


def save_score(db, row, score, rules, scored_at):
    db.execute("""
        INSERT INTO gold_risk_scores (
            event_id, transaction_id, source,
            customer_id, amount_usd, amount_btc,
            risk_score, risk_level, triggered_rules,
            rule_version, scored_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)

        ON CONFLICT(event_id) DO UPDATE SET
            transaction_id = excluded.transaction_id,
            source = excluded.source,
            customer_id = excluded.customer_id,
            amount_usd = excluded.amount_usd,
            amount_btc = excluded.amount_btc,
            risk_score = excluded.risk_score,
            risk_level = excluded.risk_level,
            triggered_rules = excluded.triggered_rules,
            rule_version = excluded.rule_version,
            scored_at = excluded.scored_at
    """, (
        row["event_id"],
        row["transaction_id"],
        row["source"],
        row["customer_id"],
        row["amount_usd"],
        row["amount_btc"],
        score,
        risk_level(score),
        json.dumps(rules),
        RULE_VERSION,
        scored_at
    ))


def save_alert(db, row, score, rules, created_at):
    explanation = "; ".join(
        rule["reason"] for rule in rules
    )

    db.execute("""
        INSERT INTO gold_aml_alerts (
            alert_id, event_id, customer_id,
            risk_score, severity, explanation,
            status, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, 'OPEN', ?)

        ON CONFLICT(event_id) DO UPDATE SET
            customer_id = excluded.customer_id,
            risk_score = excluded.risk_score,
            severity = excluded.severity,
            explanation = excluded.explanation,
            status = CASE
                WHEN gold_aml_alerts.status =
                    'NO_LONGER_TRIGGERED'
                THEN 'OPEN'
                ELSE gold_aml_alerts.status
            END
    """, (
        f"AML:{row['event_id']}",
        row["event_id"],
        row["customer_id"],
        score,
        risk_level(score),
        explanation,
        created_at
    ))


def run_gold_pipeline():
    scored_at = utc_now()

    scored_count = 0
    alert_count = 0

    banking_history = defaultdict(deque)
    bitcoin_history = []

    with connect() as db:
        create_gold_tables(db)

        # Fetch both Silver fields and original Bronze JSON.
        rows = db.execute("""
            SELECT
                s.*,
                b.payload AS bronze_payload
            FROM silver_transactions s
            LEFT JOIN bronze b
                ON s.event_id = b.event_id
            ORDER BY
                COALESCE(s.event_time, s.ingested_at),
                s.event_id
        """).fetchall()

        # Scores and alerts are saved together in one
        # SQLite transaction.
        db.execute("SAVEPOINT gold_run")

        try:
            for row in rows:
                source = row["source"]

                if source == "synthetic_banking":
                    score, rules, should_alert = score_banking(
                        row, banking_history
                    )

                elif source == "blockstream_esplora":
                    if row["bronze_payload"] is None:
                        raise ValueError(
                            f"Missing Bronze event: {row['event_id']}"
                        )

                    raw_event = json.loads(
                        row["bronze_payload"]
                    )

                    score, rules, should_alert = score_bitcoin(
                        row, raw_event, bitcoin_history
                    )

                else:
                    # Unknown sources get zero risk,
                    # never an automatic alert.
                    score, rules, should_alert = 0, [], False

                save_score(
                    db, row, score, rules, scored_at
                )
                scored_count += 1

                if should_alert:
                    save_alert(
                        db, row, score, rules, scored_at
                    )
                    alert_count += 1
                else:
                    # Keep the alert record for audit, but
                    # stop treating an old OPEN alert as active.
                    db.execute("""
                        UPDATE gold_aml_alerts
                        SET status = 'NO_LONGER_TRIGGERED'
                        WHERE event_id = ?
                          AND status = 'OPEN'
                    """, (row["event_id"],))

            db.execute("RELEASE SAVEPOINT gold_run")
            db.commit()

        except Exception:
            db.execute("ROLLBACK TO SAVEPOINT gold_run")
            db.execute("RELEASE SAVEPOINT gold_run")
            db.rollback()
            raise

    print("\nGOLD PIPELINE COMPLETED")
    print("-" * 40)
    print("Transactions scored:", scored_count)
    print("Current triggered alerts:", alert_count)
    print("Rule version:", RULE_VERSION)

    return scored_count, alert_count


if __name__ == "__main__":
    run_gold_pipeline()
