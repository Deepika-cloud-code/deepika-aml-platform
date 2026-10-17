# Sentinel AML — local Streamlit prototype

A working Azure-free AML **demonstration**, not a regulated transaction monitoring solution.

## Quick start (Windows PowerShell; run from project root)

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
copy .env.example .env
streamlit run app.py
```

Python 3.11 or 3.12 is recommended for dependency compatibility; your existing Python 3.14 venv is not required. On macOS/Linux replace activation with `source .venv/bin/activate` and `copy` with `cp`.

Open the localhost URL Streamlit prints (usually http://localhost:8501).

1. The app seeds 240 **synthetic** banking records deterministically into SQLite on first run.
2. Click **Fetch live Bitcoin mempool** to retrieve up to ten real, public Bitcoin transactions (Internet needed). Duplicate IDs are ignored. Repeat later for more events. The API can rate-limit or have temporary outages.
3. Explore transaction provenance, rule-generated alerts, and analyst dispositions.
4. Open **RAG Analyst** and ask a question. Without API credentials, it retrieves and displays source evidence. To get LLM-generated narrative answers, set `OPENAI_API_KEY` in `.env`, then restart Streamlit.

## Pipeline

Blockstream `/mempool/recent` -> `/tx/{txid}` (detailed data) -> normalized collector-schema-compatible event -> local SQLite `bronze` raw JSON -> `silver` typed values -> `gold_alerts` transparent rule engine -> Streamlit dashboard + document retrieval.

Source `synthetic_banking` is separate and clearly identified. The pipeline does not actually use Azure, Spark, Delta Lake, Unity Catalog, RBAC, Power BI, MCP servers, or ML training. It reproduces the *logical layers* as local SQLite tables, not the original infrastructure.

## RAG

Retrieval uses locally computed TF-IDF word/ngram document vectors and cosine similarity across `docs/*.md` and up to 300 stored alert summaries. If configured, an OpenAI chat model synthesizes a cited answer from retrieved evidence. Retrieval is lexical rather than embedding-based semantic search. No customer secrets or API credentials are built into the project. With no API key, evidence-only retrieval stays functional.

## Key integrity caveats

- Bitcoin transaction output total includes change and potentially multiple recipients; it is *not* a reliable amount exchanged between two parties.
- The app intentionally does not infer or fabricate USD value for Bitcoin events.
- Repeated polling returns the last 10 recent mempool entries and may miss events; it is not lossless streaming.
- `event_time` for real Bitcoin events is observation time, not an authoritative blockchain timestamp.
- Rule-based alerts do not establish suspicious activity; flags require human investigation.
- A sample of unlabeled events cannot demonstrate 30% fewer false positives, 55% less investigator time, or 20 analyst hours/week saved. Measure these only with baselines and ground truth.
- The old test event flat schema should be mapped to the canonical schema separately before any migration to production.

## Next iteration

Implement a background WebSocket consumer with retries/checkpointing, external case notes, labeled synthetic outcomes, deterministic evaluation metrics, offline embedding/vector retrieval and a Dockerfile. Replace SQLite with cloud services only after connectivity is restored.

## Step 1: run ingestion from the CLI

From the project root, once dependencies are installed:

```powershell
python -m collectors.synthetic_collector --count 100
python -m collectors.bitcoin_collector --limit 5
```

Inspect the local raw event count with:

```powershell
python -c "from aml.core import connect; db=connect(); print(db.execute('SELECT source, COUNT(*) FROM bronze GROUP BY source').fetchall()); db.close()"
```

The Bitcoin collector makes public HTTP requests at execution time and does not use Azure credentials. Repeated polling of the latest few records is **not** continuous streaming; it can skip mempool transactions between polls. Ingestion currently runs the silver and gold transforms too (through `aml.core.ingest`), which we will separate and refactor when implementing those stages individually.
