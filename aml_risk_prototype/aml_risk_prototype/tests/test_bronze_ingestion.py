
from uuid import uuid4

from aml.core import connect
from pipelines.bronze import ingest_bronze, get_bronze_count


event_id = f"test:{uuid4().hex}"

test_event = {
    "schema_version": "1.0",
    "event_id": event_id,
    "transaction_id": event_id,
    "source": "bronze_unit_test",
    "network": "simulated_bank",
    "status": "posted",
    "amount_usd": 25000.0,
    "is_synthetic": True,
}

before = get_bronze_count()

try:
    first = ingest_bronze(test_event)
    second = ingest_bronze(test_event)
    after = get_bronze_count()

    assert first is True
    assert second is False
    assert after == before + 1

    print("First ingestion:", first)
    print("Duplicate ingestion:", second)
    print("Bronze count before:", before)
    print("Bronze count after:", after)
    print("BRONZE INGESTION TEST PASSED")

finally:
    with connect() as db:
        db.execute(
            "DELETE FROM bronze WHERE event_id = ?",
            (event_id,),
        )
        db.commit()
