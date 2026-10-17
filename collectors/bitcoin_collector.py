import json
import os
import signal
from datetime import datetime, timezone
from typing import Any

import websocket
from azure.eventhub import EventData, EventHubProducerClient
from dotenv import load_dotenv


load_dotenv()

BITCOIN_WEBSOCKET_URL = "wss://ws.blockchain.info/inv"

EVENT_HUB_CONNECTION_STRING = os.getenv(
    "EVENT_HUB_CONNECTION_STRING"
)

MAX_BITCOIN_EVENTS = int(
    os.getenv("MAX_BITCOIN_EVENTS", "100")
)

SATOSHIS_PER_BITCOIN = 100_000_000


if not EVENT_HUB_CONNECTION_STRING:
    raise ValueError(
        "EVENT_HUB_CONNECTION_STRING is missing from .env"
    )


def satoshis_to_btc(value: int | float | None) -> float:
    """Convert satoshis into BTC."""

    if value is None:
        return 0.0

    return float(value) / SATOSHIS_PER_BITCOIN


def unix_time_to_utc(timestamp: int | None) -> str | None:
    """Convert Unix time into an ISO UTC timestamp."""

    if timestamp is None:
        return None

    return datetime.fromtimestamp(
        timestamp,
        tz=timezone.utc
    ).isoformat()


def normalize_transaction(
    raw_transaction: dict[str, Any]
) -> dict[str, Any]:
    """
    Convert a Blockchain.com transaction message into
    the project's standard Bitcoin transaction format.
    """

    normalized_inputs = []
    normalized_outputs = []

    total_input_satoshis = 0
    total_output_satoshis = 0

    for transaction_input in raw_transaction.get("inputs", []):
        previous_output = (
            transaction_input.get("prev_out") or {}
        )

        input_value = previous_output.get("value", 0)
        total_input_satoshis += input_value or 0

        normalized_inputs.append(
            {
                "address": previous_output.get("addr"),
                "value_satoshis": input_value,
                "value_btc": satoshis_to_btc(input_value),
                "previous_transaction_index":
                    previous_output.get("tx_index"),
                "output_index": previous_output.get("n"),
            }
        )

    for transaction_output in raw_transaction.get("out", []):
        output_value = transaction_output.get("value", 0)
        total_output_satoshis += output_value or 0

        normalized_outputs.append(
            {
                "address": transaction_output.get("addr"),
                "value_satoshis": output_value,
                "value_btc": satoshis_to_btc(output_value),
                "output_index": transaction_output.get("n"),
                "spent": transaction_output.get("spent"),
            }
        )

    fee_satoshis = max(
        total_input_satoshis - total_output_satoshis,
        0
    )

    input_addresses = sorted(
        {
            item["address"]
            for item in normalized_inputs
            if item["address"]
        }
    )

    output_addresses = sorted(
        {
            item["address"]
            for item in normalized_outputs
            if item["address"]
        }
    )

    transaction_hash = raw_transaction.get("hash")

    return {
        "event_id": f"bitcoin:{transaction_hash}",
        "source": "blockchain_com_websocket",
        "network": "bitcoin",
        "transaction_id": transaction_hash,
        "transaction_index":
            raw_transaction.get("tx_index"),
        "status": "unconfirmed",
        "event_timestamp": unix_time_to_utc(
            raw_transaction.get("time")
        ),
        "ingestion_timestamp":
            datetime.now(timezone.utc).isoformat(),
        "transaction_version":
            raw_transaction.get("ver"),
        "lock_time":
            raw_transaction.get("lock_time"),
        "transaction_size_bytes":
            raw_transaction.get("size"),
        "input_count": len(normalized_inputs),
        "output_count": len(normalized_outputs),
        "input_addresses": input_addresses,
        "output_addresses": output_addresses,
        "inputs": normalized_inputs,
        "outputs": normalized_outputs,
        "total_input_satoshis":
            total_input_satoshis,
        "total_input_btc":
            satoshis_to_btc(total_input_satoshis),
        "total_output_satoshis":
            total_output_satoshis,
        "total_output_btc":
            satoshis_to_btc(total_output_satoshis),
        "fee_satoshis": fee_satoshis,
        "fee_btc":
            satoshis_to_btc(fee_satoshis),
        "schema_version": "1.0",
    }


class BitcoinCollector:
    def __init__(self) -> None:
        self.events_received = 0
        self.events_sent = 0
        self.events_failed = 0

        self.producer = (
            EventHubProducerClient.from_connection_string(
                conn_str=EVENT_HUB_CONNECTION_STRING
            )
        )

    def send_to_event_hubs(
        self,
        transaction: dict[str, Any]
    ) -> None:
        """Send one normalized Bitcoin transaction."""

        event_json = json.dumps(
            transaction,
            separators=(",", ":")
        )

        event = EventData(event_json)

        event.properties = {
            "source": transaction["source"],
            "network": transaction["network"],
            "status": transaction["status"],
            "schema_version":
                transaction["schema_version"],
        }

        batch = self.producer.create_batch()
        batch.add(event)
        self.producer.send_batch(batch)

    def on_open(self, ws: websocket.WebSocketApp) -> None:
        subscription = {
            "op": "unconfirmed_sub"
        }

        ws.send(json.dumps(subscription))

        print("Connected to the Bitcoin WebSocket.")
        print(
            f"Collecting up to {MAX_BITCOIN_EVENTS} "
            "real transactions..."
        )

    def on_message(
        self,
        ws: websocket.WebSocketApp,
        message: str
    ) -> None:
        try:
            raw_message = json.loads(message)

            if raw_message.get("op") != "utx":
                return

            self.events_received += 1

            raw_transaction = raw_message.get("x", {})

            transaction = normalize_transaction(
                raw_transaction
            )

            self.send_to_event_hubs(transaction)
            self.events_sent += 1

            print(
                f"Sent {self.events_sent}/"
                f"{MAX_BITCOIN_EVENTS} | "
                f"TX: {transaction['transaction_id']} | "
                f"Outputs: "
                f"{transaction['total_output_btc']:.8f} BTC | "
                f"Fee: {transaction['fee_btc']:.8f} BTC"
            )

            if self.events_sent >= MAX_BITCOIN_EVENTS:
                print(
                    "\nCollection limit reached. "
                    "Closing the WebSocket."
                )

                ws.send(
                    json.dumps(
                        {"op": "unconfirmed_unsub"}
                    )
                )

                ws.close()

        except Exception as error:
            self.events_failed += 1

            print(
                f"Failed to process event: {error}"
            )

    def on_error(
        self,
        ws: websocket.WebSocketApp,
        error: Exception
    ) -> None:
        print(f"WebSocket error: {error}")

    def on_close(
        self,
        ws: websocket.WebSocketApp,
        close_status_code: int | None,
        close_message: str | None
    ) -> None:
        print("\nBitcoin WebSocket closed.")
        print(f"Events received: {self.events_received}")
        print(f"Events sent: {self.events_sent}")
        print(f"Events failed: {self.events_failed}")

    def stop(
        self,
        signal_number: int,
        frame: Any
    ) -> None:
        print("\nStop signal received.")
        self.websocket.close()

    def run(self) -> None:
        self.websocket = websocket.WebSocketApp(
            BITCOIN_WEBSOCKET_URL,
            on_open=self.on_open,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close,
        )

        signal.signal(signal.SIGINT, self.stop)

        try:
            with self.producer:
                self.websocket.run_forever(
                    ping_interval=30,
                    ping_timeout=10
                )
        finally:
            print("Collector finished.")


if __name__ == "__main__":
    collector = BitcoinCollector()
    collector.run()