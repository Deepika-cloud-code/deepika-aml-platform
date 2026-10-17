
"""Generate synthetic banking events and write to Bronze only."""

import argparse
import random

from aml.core import connect, normalize_synthetic
from pipelines.bronze import ingest_bronze


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--start", type=int, default=0)
    args = parser.parse_args()

    if not 1 <= args.count <= 10000:
        parser.error("--count must be between 1 and 10000")
    if args.start < 0:
        parser.error("--start must be non-negative")

    rng = random.Random(42)
    inserted = 0

    # Generate deterministic event IDs using record indices.
    # This makes repeated runs safely deduplicated.
    for idx in range(args.start, args.start + args.count):
        event = normalize_synthetic(idx, rng)

        if ingest_bronze(event):
            inserted += 1

    with connect() as db:
        total = db.execute("""
            SELECT COUNT(*) FROM bronze
            WHERE source = 'synthetic_banking'
        """).fetchone()[0]

    print(f"New Bronze records: {inserted}")
    print(f"Total synthetic Bronze records: {total}")


if __name__ == "__main__":
    main()
