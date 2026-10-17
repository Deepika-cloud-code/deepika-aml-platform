
from aml.core import connect

with connect() as db:
    print("BRONZE TABLE SCHEMA")
    columns = db.execute(
        "PRAGMA table_info(bronze)"
    ).fetchall()

    for col in columns:
        print(tuple(col))

    print("\nSAMPLE BRONZE RECORD")
    row = db.execute(
        "SELECT * FROM bronze LIMIT 1"
    ).fetchone()

    if row:
        print(dict(row))
    else:
        print("Bronze table is empty.")
