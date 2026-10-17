
from aml.core import connect

with connect() as db:
    print("\nSILVER DATA QUALITY REPORT")
    print("-" * 40)

    bronze_count = db.execute(
        "SELECT COUNT(*) FROM bronze"
    ).fetchone()[0]

    silver_count = db.execute(
        "SELECT COUNT(*) FROM silver_transactions"
    ).fetchone()[0]

    rejected_count = db.execute(
        "SELECT COUNT(*) FROM silver_rejections"
    ).fetchone()[0]

    print("Bronze records:", bronze_count)
    print("Silver records:", silver_count)
    print("Rejected records:", rejected_count)

    assert bronze_count == silver_count + rejected_count, (
        "Some Bronze records are not accounted for"
    )

    print("\nRECORDS BY SOURCE")

    rows = db.execute("""
        SELECT
            source,
            COUNT(*) AS total,
            COUNT(amount_usd) AS usd_records,
            COUNT(amount_btc) AS btc_records
        FROM silver_transactions
        GROUP BY source
    """).fetchall()

    for row in rows:
        print(dict(row))

    print("\nSAMPLE SILVER TRANSACTION")

    sample = db.execute("""
        SELECT *
        FROM silver_transactions
        LIMIT 1
    """).fetchone()

    if sample:
        print(dict(sample))

    print("\nDATA QUALITY CHECK PASSED")
