
"""Fetch recent Bitcoin transactions and write to Bronze only."""

import argparse

from aml.core import fetch_live, connect
from pipelines.bronze import ingest_bronze


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()

    if not 1 <= args.limit <= 10:
        parser.error("--limit must be between 1 and 10")

    try:
        events = fetch_live(args.limit)
    except Exception as exc:
        print(f"Bitcoin API unavailable: {exc}")
        raise SystemExit(1) from exc

    inserted = 0

    for event in events:
        if ingest_bronze(event):
            inserted += 1

    with connect() as db:
        total = db.execute("""
            SELECT COUNT(*) FROM bronze
            WHERE source = 'blockstream_esplora'
        """).fetchone()[0]

    print(f"Fetched transactions: {len(events)}")
    print(f"New Bronze records: {inserted}")
    print(f"Total Bitcoin Bronze records: {total}")


if __name__ == "__main__":
    main()
