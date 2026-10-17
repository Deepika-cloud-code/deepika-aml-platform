
"""Verify Gold v2 risk scores and alert rules."""

import json
from collections import Counter

from aml.core import connect


with connect() as db:
    scores = db.execute("""
        SELECT *
        FROM gold_risk_scores
        WHERE rule_version = '2.0'
    """).fetchall()

    silver_count = db.execute("""
        SELECT COUNT(*) FROM silver_transactions
    """).fetchone()[0]

    assert len(scores) == silver_count, (
        "Not all Silver transactions have Gold v2 scores"
    )

    rule_counts = Counter()
    source_counts = Counter()
    alerts_expected = set()

    for row in scores:
        score = row["risk_score"]
        source = row["source"]
        rules = json.loads(row["triggered_rules"])

        assert 0 <= score <= 100

        source_counts[source] += 1

        for rule in rules:
            rule_counts[rule["rule"]] += 1

        if source == "blockstream_esplora":
            assert all(
                rule["rule"].startswith("BTC")
                for rule in rules
            )

            if len(rules) >= 3 and score >= 60:
                alerts_expected.add(row["event_id"])

        elif source == "synthetic_banking":
            if score >= 30:
                alerts_expected.add(row["event_id"])

    active_alerts = {
        row["event_id"]
        for row in db.execute("""
            SELECT event_id
            FROM gold_aml_alerts
            WHERE status NOT IN ('NO_LONGER_TRIGGERED')
        """).fetchall()
    }

    print("\nGOLD V2 VALIDATION")
    print("-" * 45)
    print("Silver transactions:", silver_count)
    print("Gold v2 scores:", len(scores))

    print("\nSCORED RECORDS BY SOURCE")
    for source, count in sorted(source_counts.items()):
        print(source, ":", count)

    print("\nBITCOIN RULE TRIGGERS")
    for rule in ("BTC001", "BTC002", "BTC003", "BTC004"):
        print(rule, ":", rule_counts[rule])

    print("\nAlerts expected:", len(alerts_expected))
    print("Active alert records:", len(active_alerts))

    assert active_alerts == alerts_expected, (
        "Active Gold alerts do not match current scoring"
    )

    print("\nTOP 5 BITCOIN RISK SCORES")

    rows = db.execute("""
        SELECT
            event_id,
            amount_btc,
            risk_score,
            risk_level,
            triggered_rules
        FROM gold_risk_scores
        WHERE source = 'blockstream_esplora'
        ORDER BY risk_score DESC
        LIMIT 5
    """).fetchall()

    for row in rows:
        print({
            "event_id": row["event_id"][:35],
            "amount_btc": row["amount_btc"],
            "risk_score": row["risk_score"],
            "risk_level": row["risk_level"],
            "rules": [
                r["rule"]
                for r in json.loads(row["triggered_rules"])
            ]
        })

    print("\nGOLD V2 VALIDATION PASSED")
