
import unittest

from rag.hybrid_retriever import HybridAMLRetriever
from aml.core import connect


class TestHybridRetriever(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.retriever = HybridAMLRetriever()
        cls.retriever.load_index()

    def test_exact_sql(self):
        with connect() as db:
            row = db.execute("""
                SELECT event_id, transaction_id
                FROM aml_evidence
                WHERE source = 'blockstream_esplora'
                LIMIT 1
            """).fetchone()

        self.assertIsNotNone(row)

        results = self.retriever.exact_search(
            "Explain transaction " + row["transaction_id"]
        )

        self.assertIn(row["event_id"], results)

    def test_keyword_search(self):
        results = self.retriever.keyword_search(
            "BTC003 historical amount anomaly"
        )
        self.assertGreater(len(results), 0)

    def test_semantic_search(self):
        results = self.retriever.semantic_search(
            "unusual cryptocurrency transaction activity"
        )
        self.assertGreater(len(results), 0)

    def test_hybrid_exact_priority(self):
        with connect() as db:
            row = db.execute("""
                SELECT event_id, transaction_id
                FROM aml_evidence
                LIMIT 1
            """).fetchone()

        results = self.retriever.hybrid_search(
            "Why was transaction "
            + row["transaction_id"]
            + " given this risk score?"
        )

        self.assertEqual(results[0]["id"], row["event_id"])
        self.assertIn("exact_sql", results[0]["matched_by"])

    def test_no_duplicate_results(self):
        results = self.retriever.hybrid_search(
            "Why are large Bitcoin transfers considered risky?"
        )

        ids = [item["id"] for item in results]
        self.assertEqual(len(ids), len(set(ids)))


if __name__ == "__main__":
    unittest.main()
