"""Local-first AML demo: transparent synthetic banking data and real Bitcoin mempool events."""
import datetime as dt
import hashlib
import json
import os
import random
import sqlite3
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / 'data' / 'aml.db'
SAT = 100_000_000
API = 'https://blockstream.info/api'


def utcnow():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')


def connect():
    DB.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB, timeout=20)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    db.executescript('''
        CREATE TABLE IF NOT EXISTS bronze (
          event_id TEXT PRIMARY KEY, ingested_at TEXT NOT NULL,
          source TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS silver (
          event_id TEXT PRIMARY KEY, event_time TEXT NOT NULL, source TEXT NOT NULL,
          network TEXT, status TEXT, amount_btc REAL NOT NULL, fee_btc REAL,
          input_count INTEGER, output_count INTEGER, input_addresses TEXT,
          output_addresses TEXT, amount_usd REAL, customer_id TEXT,
          is_synthetic INTEGER NOT NULL, data_quality TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS gold_alerts (
          event_id TEXT PRIMARY KEY, risk_score INTEGER, severity TEXT,
          reasons TEXT, generated_at TEXT, disposition TEXT DEFAULT 'Open');
    ''')
    return db


def risk_score(event):
    """Simple investigatory heuristics, not a trained model or evidence of crime."""
    score = 0
    reasons = []
    usd = event.get('amount_usd')
    amount_btc = event['amount_btc']
    outputs = event.get('output_count') or 0
    inputs = event.get('input_count') or 0
    if usd is not None and usd >= 100_000:
        score += 35
        reasons.append('Value >= $100,000 (available only for synthetic bank data)')
    if amount_btc >= 5:
        score += 35
        reasons.append('Large Bitcoin amount >= 5 BTC (output sum, not a single transfer)')
    if outputs >= 10:
        score += 25
        reasons.append('Many outputs (>= 10); common legitimate batching is possible')
    if inputs >= 15:
        score += 20
        reasons.append('Many inputs (>= 15); consolidation may be legitimate')
    if event.get('is_synthetic') and event.get('customer_id', '').endswith('R'):
        score += 30
        reasons.append('Synthetic elevated-risk customer marker')
    score = min(score, 100)
    severity = 'High' if score >= 65 else 'Medium' if score >= 35 else 'Low'
    return score, severity, reasons


def normalize_esplora(tx):
    txid = tx['txid']
    ins = tx.get('vin', [])
    outs = tx.get('vout', [])
    input_addresses = sorted({i.get('prevout', {}).get('scriptpubkey_address') for i in ins if i.get('prevout') and i['prevout'].get('scriptpubkey_address')})
    output_addresses = sorted({o.get('scriptpubkey_address') for o in outs if o.get('scriptpubkey_address')})
    confirmed = bool(tx.get('status', {}).get('confirmed'))
    status = 'confirmed' if confirmed else 'unconfirmed'
    # Canonical event_id and schema_version are compatible with existing Bitcoin collector.
    return {'schema_version': '1.0', 'event_id': f'bitcoin:{txid}',
            'transaction_id': txid, 'source': 'blockstream_esplora', 'network': 'bitcoin',
            'event_time': utcnow(), 'status': status, 'inputs': ins, 'outputs': outs,
            'input_addresses': input_addresses, 'output_addresses': output_addresses,
            'input_count': len(ins), 'output_count': len(outs),
            'output_satoshis': sum(o.get('value', 0) for o in outs),
            'output_btc': sum(o.get('value', 0) for o in outs) / SAT,
            'fee_satoshis': tx.get('fee'),
            'fee_btc': tx.get('fee', 0) / SAT if tx.get('fee') is not None else None,
            'is_synthetic': False}


def normalize_synthetic(idx, rng):
    amount = round(rng.choices([rng.uniform(100, 9000), rng.uniform(12_000, 80_000), rng.uniform(100_000, 350_000)], weights=[65, 25, 10])[0], 2)
    sender = f'CUST-{rng.randrange(1, 160):04d}'
    if idx % 13 == 0: sender += 'R'
    txid = hashlib.sha256(f'aml-synthetic-{idx}'.encode()).hexdigest()
    return {'schema_version': '1.0', 'event_id': f'synthetic:{txid}',
            'transaction_id': txid, 'source': 'synthetic_banking', 'network': 'simulated_bank',
            'event_time': (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=idx*7)).isoformat(timespec='seconds'),
            'status': 'posted', 'input_addresses': [sender],
            'output_addresses': [f'MERCHANT-{rng.randrange(1,80):03d}'],
            'input_count': 1, 'output_count': 1,
            'output_btc': 0.0, 'fee_btc': None,
            'amount_usd': amount, 'customer_id': sender,
            'is_synthetic': True}


def ingest(events):
    inserted = 0
    with connect() as db:
        for event in events:
            event_id = event.get('event_id')
            if not event_id: continue
            try:
                cur = db.execute('INSERT OR IGNORE INTO bronze VALUES (?,?,?,?)',
                     (event_id, utcnow(), event.get('source', 'unknown'), json.dumps(event, default=str)))
                if cur.rowcount == 0: continue
                inserted += 1
                amount_btc = float(event.get('output_btc') or 0)
                silver = {'event_id': event_id, 'event_time': event.get('event_time', utcnow()),
                          'source': event.get('source', 'unknown'), 'network': event.get('network', ''),
                          'status': event.get('status', 'unknown'), 'amount_btc': amount_btc,
                          'fee_btc': event.get('fee_btc'), 'input_count': event.get('input_count', 0),
                          'output_count': event.get('output_count', 0), 'input_addresses': event.get('input_addresses', []),
                          'output_addresses': event.get('output_addresses', []),
                          'amount_usd': event.get('amount_usd'), 'customer_id': event.get('customer_id', ''),
                          'is_synthetic': bool(event.get('is_synthetic')),
                          'data_quality': 'valid' if event.get('schema_version') == '1.0' else 'review'}
                db.execute('''INSERT OR IGNORE INTO silver VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                           (silver['event_id'], silver['event_time'], silver['source'], silver['network'], silver['status'],
                            silver['amount_btc'], silver['fee_btc'], silver['input_count'], silver['output_count'],
                            json.dumps(silver['input_addresses']), json.dumps(silver['output_addresses']),
                            silver['amount_usd'], silver['customer_id'], int(silver['is_synthetic']), silver['data_quality']))
                score, severity, reasons = risk_score(silver)
                if score >= 35:
                    db.execute('''INSERT OR IGNORE INTO gold_alerts(event_id,risk_score,severity,reasons,generated_at)
                                  VALUES (?,?,?,?,?)''', (event_id, score, severity, json.dumps(reasons), utcnow()))
            except (ValueError, TypeError, KeyError, sqlite3.Error):
                # Roll back just this record's partially written changes.
                db.execute('DELETE FROM silver WHERE event_id=?', (event_id,))
                db.execute('DELETE FROM gold_alerts WHERE event_id=?', (event_id,))
                db.execute('DELETE FROM bronze WHERE event_id=?', (event_id,))
    return inserted


def seed(n=240):
    rng = random.Random(42)
    return ingest(normalize_synthetic(i, rng) for i in range(n))


def fetch_live(limit=10):
    """Recent mempool tx IDs -> full detail; network failures raised to caller."""
    r = requests.get(f'{API}/mempool/recent', timeout=12)
    r.raise_for_status()
    recent = r.json()[:max(1, min(int(limit), 10))]
    transactions = []
    for item in recent:
        try:
            resp = requests.get(f"{API}/tx/{item['txid']}", timeout=12)
            resp.raise_for_status()
            transactions.append(normalize_esplora(resp.json()))
        except (requests.RequestException, KeyError, ValueError):
            continue
    return transactions


def frames():
    import pandas as pd
    with connect() as db:
        events = pd.read_sql_query('SELECT * FROM silver ORDER BY event_time DESC', db)
        alerts = pd.read_sql_query('''SELECT a.*, s.source, s.network, s.amount_btc, s.amount_usd,
                           s.customer_id, s.event_time, s.is_synthetic FROM gold_alerts a
                           JOIN silver s ON s.event_id=a.event_id ORDER BY a.generated_at DESC''', db)
    return events, alerts


def alert_documents(max_items=300):
    with connect() as db:
        rows = db.execute('''SELECT a.event_id,a.risk_score,a.severity,a.reasons,
                        s.source,s.network,s.amount_btc,s.amount_usd,s.customer_id,s.event_time,
                        s.is_synthetic FROM gold_alerts a JOIN silver s ON a.event_id=s.event_id
                        ORDER BY a.generated_at DESC LIMIT ?''', (max_items,)).fetchall()
    docs = []
    for r in rows:
        x = dict(r)
        x['reasons'] = ', '.join(json.loads(x['reasons']))
        docs.append((x['event_id'], 'ALERT EVIDENCE: ' + json.dumps(x, default=str)))
    return docs
