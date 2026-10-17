
from aml.core import connect
from pipelines.gold import ALERT_THRESHOLD

with connect() as db:
    silver_count = db.execute("""
        SELECT COUNT(*) FROM silver_transactions
    """).fetchone()[0]

    gold_count = db.execute("""
        SELECT COUNT(*) FROM gold_risk_scores
    """).fetchone()[0]

    alert_count = db.execute("""
        SELECT COUNT(*) FROM gold_aml_alerts
    """).fetchone()[0]

    assert gold_count == silver_count, (
        "Not all Silver transactions were scored"
    )

    invalid_scores = db.execute("""
        SELECT COUNT(*) FROM gold_risk_scores
        WHERE risk_score < 0 OR risk_score > 100
    """).fetchone()[0]

    assert invalid_scores == 0

    invalid_alerts = db.execute("""
        SELECT COUNT(*) FROM gold_aml_alerts
        WHERE risk_score < ?
    """, (ALERT_THRESHOLD,)).fetchone()[0]

    assert invalid_alerts == 0

    print("\nGOLD DATA QUALITY REPORT")
    print("-" * 40)
    print("Silver transactions:", silver_count)
    print("Scored transactions:", gold_count)
    print("Generated alerts:", alert_count)

    print("\nRISK DISTRIBUTION")

    rows = db.execute("""
        SELECT risk_level, COUNT(*) AS total
        FROM gold_risk_scores
        GROUP BY risk_level
        ORDER BY MIN(risk_score) DESC
    """).fetchall()

    for row in rows:
        print(dict(row))

    print("\nTOP AML ALERTS")

    alerts = db.execute("""
        SELECT event_id, risk_score, severity, explanation
        FROM gold_aml_alerts
        ORDER BY risk_score DESC
        LIMIT 5
    """).fetchall()

    for alert in alerts:
        print(dict(alert))

    print("\nGOLD VALIDATION PASSED")
