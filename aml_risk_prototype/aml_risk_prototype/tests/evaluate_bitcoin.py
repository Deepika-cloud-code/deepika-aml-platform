
"""Evaluate real Bitcoin transactions against AML rules."""

import json

from collections import Counter
from datetime import datetime

from aml.core import connect

from detection.bitcoin_rules import (
    score_bitcoin_transaction
)


def parse_timestamp(value):

    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )

        if parsed.tzinfo is None:
            return None

        return parsed

    except (ValueError, AttributeError):
        return None


def evaluate_bitcoin():

    with connect() as db:

        rows = db.execute("""
            SELECT
                s.event_id,
                s.event_time,
                s.ingested_at,
                b.payload
            FROM silver_transactions s
            JOIN bronze b
                ON s.event_id = b.event_id
            WHERE s.source = 'blockstream_esplora'
        """).fetchall()

    events = []

    for row in rows:

        transaction = json.loads(row["payload"])

        event_time = (
            parse_timestamp(row["event_time"])
            or parse_timestamp(row["ingested_at"])
        )

        if event_time is None:
            continue

        events.append((
            event_time,
            row["event_id"],
            transaction
        ))

    # Evaluate earlier observations first.
    events.sort(
        key=lambda item: (item[0], item[1])
    )

    history = []
    triggered = Counter()
    alerts = []

    for event_time, event_id, transaction in events:

        current_event = {
            "observation_time": event_time,
            "output_btc": transaction.get("output_btc"),
            "output_count": transaction.get("output_count"),
            "input_addresses": (
                transaction.get("input_addresses") or []
            )
        }

        score, rules, should_alert = (
            score_bitcoin_transaction(
                current_event,
                history
            )
        )

        triggered.update(
            rule["rule"] for rule in rules
        )

        if should_alert:

            alerts.append({
                "event_id": event_id,
                "risk_score": score,
                "rules": [
                    rule["rule"]
                    for rule in rules
                ]
            })

        history.append({
            "event_time": event_time,
            "addresses": set(
                transaction.get("input_addresses") or []
            ),
            "amount_btc": float(
                transaction.get("output_btc") or 0
            )
        })

    print("\nBITCOIN AML EVALUATION")
    print("-" * 45)

    print("Transactions evaluated:", len(events))

    print("\nRULE TRIGGERS")

    for rule in (
        "BTC001",
        "BTC002",
        "BTC003",
        "BTC004"
    ):
        print(rule, ":", triggered[rule])

    print("\nTotal review alerts:", len(alerts))

    print("\nSAMPLE ALERTS")

    for alert in alerts[:10]:
        print(alert)

    print(
        "\nEvaluation complete. "
        "No Gold tables were modified."
    )


if __name__ == "__main__":
    evaluate_bitcoin()
