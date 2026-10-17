
from aml.core import connect

with connect() as db:
    rows = db.execute("""
        SELECT source, COUNT(*) AS total
        FROM bronze
        GROUP BY source
    """).fetchall()

    for row in rows:
        print(row["source"], row["total"])
