
"""Hybrid AML retrieval: exact SQL + FTS5 + semantic search."""

import re
import sqlite3
from collections import defaultdict
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer

from aml.core import connect


ROOT = Path(__file__).resolve().parents[1]
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
VECTOR_PATH = ROOT / "data" / "rag_vectors.npz"
POLICY_PATH = ROOT / "docs" / "aml_policy.md"


def policy_chunks():
    """Split the AML policy into searchable sections."""
    if not POLICY_PATH.exists():
        return []

    content = POLICY_PATH.read_text(encoding="utf-8")
    sections = re.split(r"(?=^#{2,3}\s)", content, flags=re.M)

    docs = []
    for i, section in enumerate(sections):
        if not section.strip():
            continue

        title = section.strip().splitlines()[0].strip("# ").strip()
        docs.append((
            f"policy:{i}",
            "policy",
            title,
            section.strip()
        ))
    return docs


def embedding_text(title, body):
    """Keep key transaction evidence within the model token limit."""
    if "Risk Assessment:" in body:
        beginning = body[:350]
        assessment = body.split("Risk Assessment:", 1)[1][:1100]
        return f"{title}\n{beginning}\nRisk Assessment:\n{assessment}"
    return f"{title}\n{body[:1400]}"


class HybridAMLRetriever:

    def __init__(self):
        self.model = SentenceTransformer(MODEL_NAME)
        self.ids = []
        self.vectors = None

    def build_index(self):
        """Rebuild keyword and semantic indexes from latest evidence."""
        with connect() as db:
            evidence = db.execute("""
                SELECT event_id, transaction_id, document_text
                FROM aml_evidence
                ORDER BY event_id
            """).fetchall()

            documents = [
                (
                    row["event_id"],
                    "transaction",
                    row["transaction_id"],
                    row["document_text"]
                )
                for row in evidence
            ]

            documents.extend(policy_chunks())

            if not documents:
                raise ValueError(
                    "No evidence or policy documents available"
                )

            try:
                db.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS rag_fts
                    USING fts5(
                        doc_id UNINDEXED,
                        kind UNINDEXED,
                        title,
                        body
                    )
                """)
            except sqlite3.OperationalError as exc:
                raise RuntimeError(
                    "SQLite FTS5 is unavailable in this Python build"
                ) from exc

            db.execute("DELETE FROM rag_fts")
            db.executemany("""
                INSERT INTO rag_fts(doc_id, kind, title, body)
                VALUES (?, ?, ?, ?)
            """, documents)
            db.commit()

        self.ids = [doc[0] for doc in documents]

        texts = [
            embedding_text(doc[2], doc[3])
            for doc in documents
        ]

        self.vectors = self.model.encode(
            texts,
            batch_size=32,
            normalize_embeddings=True,
            show_progress_bar=True
        ).astype(np.float32)

        VECTOR_PATH.parent.mkdir(parents=True, exist_ok=True)

        np.savez_compressed(
            VECTOR_PATH,
            ids=np.array(self.ids),
            vectors=self.vectors
        )

        print(f"Indexed {len(documents)} AML documents")
        print("Keyword index: SQLite FTS5")
        print("Semantic index:", VECTOR_PATH)

    def load_index(self):
        if not VECTOR_PATH.exists():
            raise FileNotFoundError(
                "Run build_index() before searching"
            )

        with np.load(VECTOR_PATH, allow_pickle=False) as data:
            self.ids = data["ids"].tolist()
            self.vectors = data["vectors"]

        with connect() as db:
            rows = db.execute("""
                SELECT doc_id FROM rag_fts ORDER BY rowid
            """).fetchall()

        sql_ids = [row["doc_id"] for row in rows]

        if sql_ids != self.ids:
            raise RuntimeError(
                "Keyword and vector indexes differ. Rebuild."
            )

    def exact_search(self, question, limit=5):
        """Find full or uniquely matching transaction IDs."""
        candidates = re.findall(
            r"(?i)(?:bitcoin:|synthetic:)?[a-f0-9]{8,64}",
            question
        )

        results = []

        with connect() as db:
            for candidate in candidates:
                suffix = candidate.split(":")[-1]

                rows = db.execute("""
                    SELECT event_id
                    FROM aml_evidence
                    WHERE lower(event_id) LIKE ?
                       OR lower(transaction_id) LIKE ?
                    LIMIT 10
                """, (
                    f"%:{suffix.lower()}%",
                    f"{suffix.lower()}%"
                )).fetchall()

                # Don't silently select one ambiguous prefix.
                if len(rows) == 1:
                    event_id = rows[0]["event_id"]

                    if event_id not in results:
                        results.append(event_id)

        return results[:limit]

    def keyword_search(self, question, limit=10):
        """Keyword search using SQLite FTS5 and BM25."""
        words = re.findall(r"[A-Za-z0-9]+", question)

        if not words:
            return []

        # Safe FTS5 OR expression: only alphanumeric tokens.
        expression = " OR ".join(
            f'"{word}"'
            for word in words[:12]
        )

        with connect() as db:
            rows = db.execute("""
                SELECT doc_id, bm25(rag_fts) AS relevance
                FROM rag_fts
                WHERE rag_fts MATCH ?
                ORDER BY relevance ASC
                LIMIT ?
            """, (expression, limit)).fetchall()

        return [row["doc_id"] for row in rows]

    def semantic_search(self, question, limit=10):
        """Cosine similarity over normalized local embeddings."""
        if self.vectors is None:
            self.load_index()

        query_vector = self.model.encode(
            [question],
            normalize_embeddings=True
        )[0]

        similarities = self.vectors @ query_vector
        ranked = np.argsort(-similarities)

        return [
            self.ids[int(i)]
            for i in ranked[:limit]
            if similarities[int(i)] > 0.15
        ]

    def hybrid_search(self, question, top_k=5):
        """Merge three retrieval paths with RRF."""
        if not question or not question.strip():
            return []

        if self.vectors is None:
            self.load_index()

        exact = self.exact_search(question)
        keyword = self.keyword_search(question, limit=15)
        semantic = self.semantic_search(question, limit=15)

        scores = defaultdict(float)
        matched_by = defaultdict(list)

        for method, ranked_ids, weight in [
            ("exact_sql", exact, 5.0),
            ("keyword", keyword, 1.0),
            ("semantic", semantic, 1.0)
        ]:
            for rank, doc_id in enumerate(ranked_ids, start=1):
                scores[doc_id] += weight / (60 + rank)
                matched_by[doc_id].append(method)

        # Exact ID queries must return their matching
        # transaction evidence ahead of approximate matches.
        ordered = sorted(
            scores,
            key=lambda doc_id: (
                doc_id not in exact,
                -scores[doc_id],
                doc_id
            )
        )[:top_k]

        results = []

        with connect() as db:
            for doc_id in ordered:
                row = db.execute("""
                    SELECT doc_id, kind, title, body
                    FROM rag_fts
                    WHERE doc_id = ?
                """, (doc_id,)).fetchone()

                if row is None:
                    continue

                results.append({
                    "id": doc_id,
                    "type": row["kind"],
                    "title": row["title"],
                    "text": row["body"],
                    "rrf_score": round(scores[doc_id], 6),
                    "matched_by": matched_by[doc_id],
                    "citation": f"[{doc_id}]"
                })

        return results


if __name__ == "__main__":
    retriever = HybridAMLRetriever()
    retriever.build_index()

    while True:
        question = input("\nAML question (or exit): ").strip()

        if question.lower() in ("exit", "quit"):
            break

        results = retriever.hybrid_search(question)

        for i, result in enumerate(results, 1):
            print("\n" + "=" * 65)
            print(f"RESULT {i}: {result['title']}")
            print("Type:", result["type"])
            print("Retrieved by:", result["matched_by"])
            print("RRF:", result["rrf_score"])
            print("Citation:", result["citation"])
            print(result["text"][:1000])
