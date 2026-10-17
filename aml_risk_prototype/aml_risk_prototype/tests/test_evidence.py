
"""Validate the AML evidence table."""

from aml.core import connect


with connect() as db:
    gold_count = db.execute("""
        SELECT COUNT(*) FROM gold_risk_scores
    """).fetchone()[0]

    evidence_count = db.execute("""
        SELECT COUNT(*) FROM aml_evidence
    """).fetchone()[0]

    assert evidence_count == gold_count, (
        "Gold and evidence counts do not match"
    )

    print("Gold scored records:", gold_count)
    print("Evidence documents:", evidence_count)

    print("\nSAMPLE HIGH-RISK BITCOIN EVIDENCE")
    print("-" * 45)

    row = db.execute("""
        SELECT document_text
        FROM aml_evidence
        WHERE source = 'blockstream_esplora'
          AND risk_score >= 60
        ORDER BY risk_score DESC
        LIMIT 1
    """).fetchone()

    if row:
        print(row["document_text"])
    else:
        print("No Bitcoin record scored >= 60")

    print("\nEVIDENCE VALIDATION PASSED")
