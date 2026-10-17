
import json
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from aml.core import connect

st.set_page_config(
    page_title="AML Risk Intelligence",
    page_icon="🛡️",
    layout="wide"
)

PAGES = [
    "Overview",
    "Bronze Layer",
    "Silver Layer",
    "Gold Layer",
    "KPI Analytics",
    "RAG Architecture",
    "AML AI Chatbot"
]


# =========================================
# SHARED DATABASE HELPERS
# =========================================

def table_exists(db, table):
    return db.execute(
        """
        SELECT 1 FROM sqlite_master
        WHERE type IN ('table', 'view')
        AND name = ?
        """,
        (table,)
    ).fetchone() is not None


def query(sql, params=()):
    with connect() as db:
        return pd.read_sql_query(sql, db, params=params)


def count(table):
    allowed = {
        "bronze", "silver_transactions",
        "silver_rejections", "gold_risk_scores",
        "gold_aml_alerts", "aml_evidence", "rag_fts"
    }

    if table not in allowed:
        raise ValueError("Unknown table")

    with connect() as db:
        if not table_exists(db, table):
            return 0

        return db.execute(
            f"SELECT COUNT(*) FROM {table}"
        ).fetchone()[0]


def active_alerts():
    if not count("gold_aml_alerts"):
        return 0

    return query("""
        SELECT COUNT(*) AS total
        FROM gold_aml_alerts
        WHERE status <> 'NO_LONGER_TRIGGERED'
    """).iloc[0]["total"]


def show_table(df, height=330):
    if df.empty:
        st.info("No records available.")
    else:
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            height=height
        )


def parse_rules(value):
    try:
        return json.loads(value) if value else []
    except (ValueError, TypeError):
        return []


def page_header(title, description):
    st.title(title)
    st.caption(description)


def show_kpis():
    items = [
        ("Bronze Events", count("bronze")),
        ("Silver Transactions", count("silver_transactions")),
        ("Silver Rejections", count("silver_rejections")),
        ("Gold Risk Scores", count("gold_risk_scores")),
        ("Active Alerts", active_alerts()),
        ("RAG Documents", count("aml_evidence"))
    ]

    for start in (0, 3):
        columns = st.columns(3)

        for col, (name, value) in zip(
            columns, items[start:start + 3]
        ):
            col.metric(name, value)


# =========================================
# PAGE 1: OVERVIEW
# =========================================

def overview():
    page_header(
        "AML Risk Intelligence Platform",
        "End-to-end AML data engineering and AI investigation"
    )

    show_kpis()

    st.subheader("Platform Architecture")

    st.info("""
    Bitcoin Esplora + Synthetic Banking Events
    → Bronze Raw Ingestion
    → Silver Data Validation
    → Gold AML Detection
    → Investigation Evidence
    → Hybrid RAG Retrieval
    → Guarded AI Chatbot
    """)

    left, right = st.columns(2)

    with left:
        st.subheader("Transactions by Source")

        if count("silver_transactions"):
            df = query("""
                SELECT source, COUNT(*) AS transactions
                FROM silver_transactions
                GROUP BY source
            """)

            fig = px.pie(
                df,
                names="source",
                values="transactions",
                hole=0.45
            )

            st.plotly_chart(
                fig, use_container_width=True
            )

    with right:
        st.subheader("Pipeline Health")

        bronze = count("bronze")
        silver = count("silver_transactions")
        rejected = count("silver_rejections")
        gold = count("gold_risk_scores")
        evidence = count("aml_evidence")

        st.metric(
            "Bronze Events Accounted For",
            f"{silver + rejected} / {bronze}"
        )

        st.metric(
            "Gold Scoring Coverage",
            f"{gold} / {silver}"
        )

        st.metric(
            "Evidence Coverage",
            f"{evidence} / {gold}"
        )

    st.subheader("What Each Layer Does")

    st.markdown("""
    **Bronze:** Stores the original transaction JSON and
    source metadata.

    **Silver:** Validates transaction IDs, timestamps,
    schema versions and monetary values.

    **Gold:** Calculates rule-based risk scores and
    generates investigation alerts.

    **RAG:** Retrieves transaction evidence and AML
    policies using exact SQL, BM25 and semantic search.

    **AI Chatbot:** Explains the evidence using GroqCloud,
    with input and output guardrails.
    """)

    st.caption(
        "The dashboard reads existing data. "
        "It does not automatically run ETL jobs."
    )


# =========================================
# PAGE 2: BRONZE LAYER
# =========================================

def bronze_page():
    page_header(
        "Bronze Layer — Raw Ingestion",
        "Original JSON transactions, metadata and traceability"
    )

    st.metric("Total Bronze Events", count("bronze"))

    st.info("""
    Live Bitcoin API / Synthetic Banking Generator
    → Event normalization at source
    → Raw JSON storage
    → Event ID deduplication
    """)

    if not count("bronze"):
        return

    sources = query("""
        SELECT DISTINCT source
        FROM bronze
        ORDER BY source
    """)["source"].tolist()

    selected_source = st.selectbox(
        "Select Source",
        ["All"] + sources
    )

    sql = """
        SELECT event_id, source, ingested_at
        FROM bronze
    """
    params = ()

    if selected_source != "All":
        sql += " WHERE source = ?"
        params = (selected_source,)

    df = query(
        sql + " ORDER BY ingested_at DESC LIMIT 250",
        params
    )

    st.subheader("Ingested Events")
    show_table(df)

    st.subheader("Raw JSON Explorer")

    if not df.empty:
        event_id = st.selectbox(
            "Select Event ID",
            df["event_id"].tolist()
        )

        with connect() as db:
            row = db.execute("""
                SELECT payload
                FROM bronze
                WHERE event_id = ?
            """, (event_id,)).fetchone()

        if row:
            try:
                st.json(json.loads(row["payload"]))
            except json.JSONDecodeError:
                st.code(row["payload"])

    st.caption(
        "Bronze retains raw source evidence. "
        "Silver performs validation separately."
    )


# =========================================
# PAGE 3: SILVER LAYER
# =========================================

def silver_page():
    page_header(
        "Silver Layer — Data Quality",
        "Schema validation, standardization and rejected records"
    )

    bronze = count("bronze")
    silver = count("silver_transactions")
    rejected = count("silver_rejections")

    c1, c2, c3 = st.columns(3)

    c1.metric("Validated Transactions", silver)
    c2.metric("Rejected Transactions", rejected)

    acceptance = (
        100 * silver / (silver + rejected)
        if silver + rejected else 0
    )

    c3.metric(
        "Acceptance Rate",
        f"{acceptance:.1f}%"
    )

    st.info("""
    Bronze JSON
    → Schema Validation
    → Type Conversion
    → Timestamp Standardization
    → NULL Handling
    → Silver Transactions / Rejections
    """)

    if silver:
        st.subheader("Validated Transactions")

        df = query("""
            SELECT
                event_id,
                source,
                event_time,
                amount_usd,
                amount_btc,
                status,
                customer_id
            FROM silver_transactions
            ORDER BY ingested_at DESC
            LIMIT 250
        """)

        show_table(df)

        st.subheader("Source Data Quality")

        quality = query("""
            SELECT
                source,
                COUNT(*) AS records,
                COUNT(amount_usd) AS usd_values,
                COUNT(amount_btc) AS btc_values
            FROM silver_transactions
            GROUP BY source
        """)

        show_table(quality, 180)

    st.subheader("Rejected Records")

    if rejected:
        show_table(query("""
            SELECT event_id, source, reason, rejected_at
            FROM silver_rejections
            ORDER BY rejected_at DESC
            LIMIT 100
        """))
    else:
        st.success("No Silver rejections recorded.")

    st.caption(
        f"Processed or rejected: {silver + rejected} "
        f"out of {bronze} Bronze records."
    )


# =========================================
# PAGE 4: GOLD LAYER
# =========================================

def gold_page():
    page_header(
        "Gold Layer — AML Risk Detection",
        "Rule-based transaction scoring and review alerts"
    )

    c1, c2, c3 = st.columns(3)
    c1.metric("Scored Transactions", count("gold_risk_scores"))
    c2.metric("Active Alerts", active_alerts())
    c3.metric("Total Alert Records", count("gold_aml_alerts"))

    st.info("""
    Banking: R001, R002, R003 → Alert when score >= 30.

    Bitcoin: BTC001, BTC002, BTC003, BTC004
    → Alert when at least 3 factors trigger
    AND score >= 60.
    """)

    if not count("gold_risk_scores"):
        return

    source = st.selectbox(
        "Source",
        ["All", "blockstream_esplora", "synthetic_banking"]
    )

    level = st.selectbox(
        "Risk Level",
        ["All", "LOW", "MEDIUM", "HIGH", "CRITICAL"]
    )

    sql = """
        SELECT
            event_id, source, amount_usd, amount_btc,
            risk_score, risk_level, triggered_rules
        FROM gold_risk_scores
        WHERE 1=1
    """
    params = []

    if source != "All":
        sql += " AND source = ?"
        params.append(source)

    if level != "All":
        sql += " AND risk_level = ?"
        params.append(level)

    scores = query(
        sql + " ORDER BY risk_score DESC LIMIT 500",
        tuple(params)
    )

    display = scores.copy()

    if not display.empty:
        display["rules"] = display["triggered_rules"].map(
            lambda value: ", ".join(
                r.get("rule", "?")
                for r in parse_rules(value)
            )
        )
        display = display.drop(columns=["triggered_rules"])

    st.subheader("Risk-Scored Transactions")
    show_table(display)

    st.subheader("Transaction Investigation")

    if not scores.empty:
        event_id = st.selectbox(
            "Investigate Transaction",
            scores["event_id"].tolist()
        )

        with connect() as db:
            row = db.execute("""
                SELECT
                    g.*,
                    a.status AS alert_status,
                    a.explanation
                FROM gold_risk_scores g
                LEFT JOIN gold_aml_alerts a
                    ON g.event_id = a.event_id
                WHERE g.event_id = ?
            """, (event_id,)).fetchone()

        if row:
            x, y, z = st.columns(3)
            x.metric("Risk Score", f"{row['risk_score']}/100")
            y.metric("Risk Level", row["risk_level"])
            z.metric(
                "Alert Status",
                row["alert_status"] or "Not Generated"
            )

            rules = parse_rules(row["triggered_rules"])

            if rules:
                st.table(pd.DataFrame(rules))
            else:
                st.info("No rules triggered.")

            if row["explanation"]:
                st.write(
                    "**Alert Explanation:**",
                    row["explanation"]
                )

    st.subheader("Active AML Alerts")

    if count("gold_aml_alerts"):
        alerts = query("""
            SELECT
                a.event_id,
                g.source,
                a.risk_score,
                a.severity,
                a.status,
                a.explanation
            FROM gold_aml_alerts a
            JOIN gold_risk_scores g
                ON a.event_id = g.event_id
            WHERE a.status <> 'NO_LONGER_TRIGGERED'
            ORDER BY a.risk_score DESC
            LIMIT 200
        """)

        show_table(alerts)

    st.caption(
        "Risk scores are screening priorities, "
        "not fraud probabilities."
    )


# =========================================
# PAGE 5: KPI ANALYTICS
# =========================================

def kpi_page():
    page_header(
        "AML KPI Analytics",
        "Actual detection metrics calculated from Gold tables"
    )

    show_kpis()

    if not count("gold_risk_scores"):
        return

    left, right = st.columns(2)

    with left:
        st.subheader("Risk Distribution")

        df = query("""
            SELECT
                source,
                risk_level,
                COUNT(*) AS transactions
            FROM gold_risk_scores
            GROUP BY source, risk_level
        """)

        fig = px.bar(
            df,
            x="risk_level",
            y="transactions",
            color="source",
            barmode="group"
        )

        st.plotly_chart(fig, use_container_width=True)

    with right:
        st.subheader("Active Alerts by Source")

        df = query("""
            SELECT
                g.source,
                COUNT(*) AS alerts
            FROM gold_aml_alerts a
            JOIN gold_risk_scores g
                ON a.event_id = g.event_id
            WHERE a.status <> 'NO_LONGER_TRIGGERED'
            GROUP BY g.source
        """) if count("gold_aml_alerts") else pd.DataFrame()

        if not df.empty:
            st.plotly_chart(
                px.bar(df, x="source", y="alerts"),
                use_container_width=True
            )
        else:
            st.info("No active alerts.")

    st.subheader("Detection Rule Frequency")

    df = query("""
        SELECT source, triggered_rules
        FROM gold_risk_scores
    """)

    frequencies = {}

    for row in df.itertuples(index=False):
        for rule in parse_rules(row.triggered_rules):
            key = (row.source, rule.get("rule", "UNKNOWN"))
            frequencies[key] = frequencies.get(key, 0) + 1

    if frequencies:
        rule_df = pd.DataFrame([
            {
                "source": source,
                "rule": rule,
                "trigger_count": total
            }
            for (source, rule), total in frequencies.items()
        ])

        st.plotly_chart(
            px.bar(
                rule_df,
                x="rule",
                y="trigger_count",
                color="source"
            ),
            use_container_width=True
        )

    st.warning(
        "Precision, recall, false-positive reduction and "
        "investigation time savings are not measured yet. "
        "They require labeled transactions and benchmarking."
    )


# =========================================
# PAGE 6: HYBRID RAG
# =========================================

def rag_page():
    page_header(
        "RAG Architecture & Retrieval",
        "Exact SQL + Keyword BM25 + Semantic Embeddings"
    )

    st.info("""
    AML Evidence Documents
    → Exact SQL / SQLite FTS5 / MiniLM Embeddings
    → Reciprocal Rank Fusion
    → Retrieved Evidence
    → Groq LLM + Output Guardrails
    """)

    c1, c2, c3 = st.columns(3)

    c1.metric("Evidence Documents", count("aml_evidence"))
    c2.metric("FTS Documents", count("rag_fts"))

    index_path = (
        Path(__file__).resolve().parent
        / "data" / "rag_vectors.npz"
    )

    c3.metric(
        "Embedding Index",
        "Available" if index_path.exists() else "Missing"
    )

    st.markdown("""
    **Exact SQL:** Finds a transaction by unique ID.

    **Keyword Search:** Uses SQLite FTS5 and BM25.

    **Semantic Search:** Uses MiniLM's 384-dimensional
    embeddings stored in the NumPy NPZ file.

    **RRF:** Combines ranked search results.

    **Grounding:** Returns evidence documents and policies
    that the chatbot can cite.
    """)

    st.subheader("Test Hybrid Retrieval")

    if st.button("Load RAG Retriever"):
        st.session_state["rag_ready"] = True

    if st.session_state.get("rag_ready"):
        try:
            from rag.hybrid_retriever import HybridAMLRetriever

            if "rag_engine" not in st.session_state:
                engine = HybridAMLRetriever()
                engine.load_index()
                st.session_state["rag_engine"] = engine

            question = st.text_input(
                "Search AML evidence",
                key="rag_question"
            )

            if st.button("Search Documents"):
                if question.strip():
                    results = (
                        st.session_state["rag_engine"]
                        .hybrid_search(question, top_k=5)
                    )

                    if not results:
                        st.info("No matching documents.")

                    for result in results:
                        with st.expander(
                            f"{result['title']} — "
                            f"{', '.join(result['matched_by'])}"
                        ):
                            st.write(
                                "Source:", result["citation"]
                            )
                            st.write(
                                "RRF:", result["rrf_score"]
                            )
                            st.text(result["text"][:4500])

        except Exception as exc:
            st.error(f"Retriever unavailable: {exc}")

    st.caption(
        "Rebuild the RAG index after updating "
        "Gold scores or evidence documents."
    )


# =========================================
# PAGE 7: AML AI CHATBOT
# =========================================

def chatbot_page():
    page_header(
        "AML AI Investigation Assistant",
        "Groq LLM + Hybrid RAG + Hallucination Guardrails"
    )

    st.warning(
        "For demonstration use only. Retrieved evidence "
        "may be sent to GroqCloud. Use synthetic or "
        "appropriately de-identified banking records."
    )

    if "messages" not in st.session_state:
        st.session_state["messages"] = []

    for message in st.session_state["messages"]:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

            if message.get("status"):
                st.caption(
                    f"Guardrail status: {message['status']}"
                )

                st.caption(
                    "Sources: "
                    + ", ".join(message.get("sources", []))
                )

                if message.get("issues"):
                    st.caption(
                        "Validation issues: "
                        + "; ".join(message["issues"])
                    )

    question = st.chat_input(
        "Ask about AML rules, risk scores or transactions..."
    )

    if question:
        st.session_state["messages"].append({
            "role": "user",
            "content": question
        })

        with st.chat_message("user"):
            st.markdown(question)

        with st.chat_message("assistant"):
            try:
                if "aml_chatbot" not in st.session_state:
                    from rag.chatbot import AMLChatbot
                    st.session_state["aml_chatbot"] = AMLChatbot()

                with st.spinner("Analyzing AML evidence..."):
                    result = (
                        st.session_state["aml_chatbot"]
                        .ask(question)
                    )

                answer = result.get(
                    "answer", "No answer returned."
                )
                status = result.get(
                    "guardrail_status", "UNKNOWN"
                )
                sources = result.get("sources", [])
                issues = result.get(
                    "hallucination_issues", []
                )

                st.markdown(answer)
                st.caption(f"Guardrail status: {status}")

                if sources:
                    st.caption(
                        "Sources: " + ", ".join(sources)
                    )

                if issues:
                    st.warning(
                        "Validation findings: "
                        + "; ".join(issues)
                    )

            except Exception as exc:
                answer = f"Chatbot unavailable: {exc}"
                status = "ERROR"
                sources = []
                issues = []
                st.error(answer)

        st.session_state["messages"].append({
            "role": "assistant",
            "content": answer,
            "status": status,
            "sources": sources,
            "issues": issues
        })

    if st.button("Clear Conversation"):
        st.session_state["messages"] = []
        st.rerun()


# =========================================
# APPLICATION NAVIGATION
# =========================================

with st.sidebar:
    st.header("🛡️ AML Intelligence")

    page = st.radio(
        "Navigation",
        PAGES,
        label_visibility="collapsed"
    )

    st.divider()

    st.caption(
        "Bitcoin + Banking | Medallion | Hybrid RAG"
    )

    if st.button("Refresh Dashboard"):
        st.rerun()


try:
    router = {
        "Overview": overview,
        "Bronze Layer": bronze_page,
        "Silver Layer": silver_page,
        "Gold Layer": gold_page,
        "KPI Analytics": kpi_page,
        "RAG Architecture": rag_page,
        "AML AI Chatbot": chatbot_page
    }

    router[page]()

except Exception as exc:
    st.error(f"Unable to load page: {exc}")
    st.caption(
        "Check your database and run the corresponding "
        "pipeline if its tables are missing."
    )
