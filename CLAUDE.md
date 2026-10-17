# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Early-stage anti-money-laundering (AML) data platform. Right now it is only the ingestion layer: Python scripts that publish crypto transaction events to **Azure Event Hubs**. There's no downstream consumer, detection logic, test suite, linter config, or dependency manifest in the repo yet.

## Environment & commands

The local virtualenv is `.venv/` (Python 3.14). Its installed dependencies are `azure-eventhub`, `websocket-client` and `python-dotenv`. There is no `requirements.txt`, so if you add a dependency, install it into `.venv` and consider creating one.

```powershell
.\.venv\Scripts\Activate.ps1

# Stream live unconfirmed Bitcoin txs into Event Hubs (stops after MAX_BITCOIN_EVENTS or Ctrl+C)
python collectors/bitcoin_collector.py

# Send two hard-coded sample events to Event Hubs (connectivity smoke test)
python testing/send_test_events.py
```

Both scripts run from the project root. They call `load_dotenv()`, so `.env` must be in the current working directory. The `.env` file needs these values:
- `EVENT_HUB_CONNECTION_STRING`: required. Both scripts raise `ValueError` at import time if it is missing. It must include `EntityPath` (the hub name), because the producer is created from the connection string alone.
- `MAX_BITCOIN_EVENTS`: optional, default `100`.

Both scripts send to the real Azure Event Hub. Nothing is mocked, and there is no offline mode.

## Architecture

**`collectors/bitcoin_collector.py`**: Blockchain.com WebSocket (`wss://ws.blockchain.info/inv`) → normalize → Event Hubs.
- `on_open` sends `{"op":"unconfirmed_sub"}`. `on_message` handles only `op == "utx"` messages, whose payload is under the `x` key.
- `normalize_transaction()` turns the raw Blockchain.com tx into the project's canonical event schema (`schema_version: "1.0"`):
  - satoshis are converted to BTC
  - `fee = max(sum(inputs.prev_out.value) - sum(out.value), 0)`
  - input and output addresses are de-duplicated and sorted
  - `event_id` is `bitcoin:<tx hash>`
  - `status` is always `"unconfirmed"`
- Each event is sent as its own single-event batch. The JSON body is compact, and the application properties are `source`, `network`, `status` and `schema_version`, which downstream consumers can filter on without parsing the body.
- Errors in individual messages are caught, counted (`events_failed`), and printed. They don't stop the stream.

**`testing/send_test_events.py`**: sends 2 synthetic events in a single batch, with `source: "local_test"`.

**Schema divergence:** the test events use an older, flat shape (`sender_address`, `receiver_address`, `asset_amount`, `amount_usd`). The collector's schema uses `inputs`/`outputs`, `input_addresses`/`output_addresses` and `*_satoshis`/`*_btc` fields, and has no USD value. Both claim `schema_version: "1.0"`. Keep this in mind when building consumers, or align the test script with the collector schema.
