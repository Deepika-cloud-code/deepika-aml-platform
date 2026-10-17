
import json
import sqlite3
from datetime import datetime, timezone

from aml.core import connect


def ingest_bronze(event: dict) -> bool:
    """
    Stores a raw event in Bronze.

    Returns True for a new event.
    Returns False if the event already exists.
    """
    event_id = event.get("event_id")
    source = event.get("source")

    if not event_id or not source:
        raise ValueError("event_id and source are required")

    ingested_at = datetime.now(timezone.utc).isoformat()

    # Store the event without normalizing its fields.
    payload = json.dumps(event, ensure_ascii=False)

    with connect() as db:
        try:
            cursor = db.execute(
                """
                INSERT INTO bronze
                    (event_id, ingested_at, source, payload)
                VALUES (?, ?, ?, ?)
                """,
                (event_id, ingested_at, source, payload),
            )
            db.commit()
            return cursor.rowcount == 1

        except sqlite3.IntegrityError:
            # Assumes event_id has a UNIQUE constraint.
            return False


def get_bronze_count() -> int:
    with connect() as db:
        row = db.execute(
            "SELECT COUNT(*) AS total FROM bronze"
        ).fetchone()
        return row["total"]
