import json
import os
import uuid
from datetime import datetime, timezone

from azure.eventhub import EventData, EventHubProducerClient
from dotenv import load_dotenv


load_dotenv()

connection_string = os.getenv("EVENT_HUB_CONNECTION_STRING")

if not connection_string:
    raise ValueError(
        "EVENT_HUB_CONNECTION_STRING was not found. "
        "Check that the .env file exists in the project root."
    )


def create_test_transactions() -> list[dict]:
    current_time = datetime.now(timezone.utc).isoformat()

    return [
        {
            "event_id": str(uuid.uuid4()),
            "source": "local_test",
            "network": "bitcoin",
            "transaction_id": "btc-test-001",
            "sender_address": "wallet-sender-001",
            "receiver_address": "wallet-receiver-001",
            "asset": "BTC",
            "asset_amount": 0.25,
            "amount_usd": 16250.00,
            "event_timestamp": current_time,
            "ingestion_timestamp": current_time,
            "schema_version": "1.0",
        },
        {
            "event_id": str(uuid.uuid4()),
            "source": "local_test",
            "network": "bitcoin",
            "transaction_id": "btc-test-002",
            "sender_address": "wallet-sender-002",
            "receiver_address": "wallet-receiver-002",
            "asset": "BTC",
            "asset_amount": 1.20,
            "amount_usd": 78000.00,
            "event_timestamp": current_time,
            "ingestion_timestamp": current_time,
            "schema_version": "1.0",
        },
    ]


def send_transactions() -> None:
    transactions = create_test_transactions()

    producer = EventHubProducerClient.from_connection_string(
        conn_str=connection_string
    )

    try:
        with producer:
            batch = producer.create_batch()

            for transaction in transactions:
                event = EventData(json.dumps(transaction))

                event.properties = {
                    "source": transaction["source"],
                    "network": transaction["network"],
                    "schema_version": transaction["schema_version"],
                }

                batch.add(event)

            producer.send_batch(batch)

        print(
            f"Success: {len(transactions)} transactions "
            "were sent to Azure Event Hubs."
        )

    except Exception as error:
        print(f"Failed to send transactions: {error}")
        raise

if __name__ == "__main__":
    send_transactions()