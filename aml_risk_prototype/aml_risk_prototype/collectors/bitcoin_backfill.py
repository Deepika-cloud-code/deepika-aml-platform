
"""Backfill real confirmed Bitcoin transactions into Bronze."""

import argparse
import time
from datetime import datetime, timezone

import requests

from aml.core import normalize_esplora
from pipelines.bronze import ingest_bronze


API_URL = "https://blockstream.info/api"


def api_get(session, endpoint, as_text=False):
    """Call the Esplora API with retries."""

    for attempt in range(4):
        try:
            response = session.get(
                API_URL + endpoint,
                timeout=25
            )

            if response.status_code in (
                429, 500, 502, 503, 504
            ):
                response.raise_for_status()

            response.raise_for_status()

            if as_text:
                return response.text.strip()

            return response.json()

        except (requests.RequestException, ValueError):
            if attempt == 3:
                raise

            time.sleep(2 ** attempt)


def backfill(count=100, max_blocks=10):
    inserted = 0
    examined = 0

    with requests.Session() as session:

        latest_height = int(
            api_get(
                session,
                "/blocks/tip/height",
                as_text=True
            )
        )

        print("Latest Bitcoin block:", latest_height)

        for height in range(
            latest_height,
            max(-1, latest_height - max_blocks),
            -1
        ):

            block_hash = api_get(
                session,
                f"/block-height/{height}",
                as_text=True
            )

            print("Processing block:", height)

            # Esplora paginates full block transactions.
            # Each page contains up to 25 transactions.
            for offset in range(0, 2500, 25):

                transactions = api_get(
                    session,
                    f"/block/{block_hash}/txs/{offset}"
                )

                if not transactions:
                    break

                for tx in transactions:

                    examined += 1

                    event = normalize_esplora(tx)

                    status = tx.get("status", {})
                    block_time = status.get("block_time")

                    if block_time:
                        event["event_time"] = (
                            datetime.fromtimestamp(
                                block_time,
                                timezone.utc
                            ).isoformat()
                        )

                    event["status"] = "confirmed"

                    if ingest_bronze(event):
                        inserted += 1

                    if inserted >= count:
                        print(
                            "New Bitcoin Bronze records:",
                            inserted
                        )
                        print(
                            "Transactions examined:",
                            examined
                        )
                        return inserted

                time.sleep(0.15)

    print("New Bitcoin Bronze records:", inserted)
    print("Transactions examined:", examined)

    return inserted


if __name__ == "__main__":

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--count",
        type=int,
        default=100
    )

    parser.add_argument(
        "--max-blocks",
        type=int,
        default=10
    )

    args = parser.parse_args()

    if not 1 <= args.count <= 1000:
        parser.error("--count must be between 1 and 1000")

    if args.max_blocks < 1:
        parser.error("--max-blocks must be positive")

    backfill(
        count=args.count,
        max_blocks=args.max_blocks
    )
