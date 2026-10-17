
from aml.core import connect

with connect() as db:
    tables = ["bronze", "silver", "gold_alerts"]

    print("\nPIPELINE RECORD COUNTS")
    print("-" * 35)

    for table in tables:
        count = db.execute(
            f"SELECT COUNT(*) FROM {table}"
        ).fetchone()[0]

        print(f"{table}: {count}")
