
"""Unit tests for Bitcoin AML detection rules."""

import unittest

from datetime import datetime, timezone, timedelta

from detection.bitcoin_rules import (
    score_bitcoin_transaction
)


TEST_TIME = datetime(
    2026, 10, 17, 12, 0,
    tzinfo=timezone.utc
)


def make_event(
    amount=1,
    output_count=2,
    addresses=None
):
    return {
        "output_btc": amount,
        "output_count": output_count,
        "input_addresses": addresses or ["test-address-A"],
        "observation_time": TEST_TIME
    }


def make_history(count=5, amount=1):

    history = []

    for i in range(count):

        history.append({
            "event_time": (
                TEST_TIME
                - timedelta(minutes=5 * (count - i))
            ),
            "addresses": {"test-address-A"},
            "amount_btc": amount
        })

    return history


class TestBitcoinRules(unittest.TestCase):

    def test_large_value(self):

        score, rules, alert = score_bitcoin_transaction(
            make_event(amount=8),
            []
        )

        self.assertEqual(score, 25)
        self.assertFalse(alert)
        self.assertEqual(rules[0]["rule"], "BTC001")

    def test_high_frequency(self):

        score, rules, alert = score_bitcoin_transaction(
            make_event(),
            make_history(count=4)
        )

        self.assertEqual(score, 20)
        self.assertFalse(alert)
        self.assertEqual(rules[0]["rule"], "BTC002")

    def test_history_anomaly(self):

        score, rules, alert = score_bitcoin_transaction(
            make_event(amount=4),
            make_history(count=5, amount=1)
        )

        rule_ids = [r["rule"] for r in rules]

        self.assertIn("BTC003", rule_ids)
        self.assertFalse(alert)

    def test_multiple_outputs(self):

        score, rules, alert = score_bitcoin_transaction(
            make_event(output_count=12),
            []
        )

        self.assertEqual(score, 15)
        self.assertFalse(alert)
        self.assertEqual(rules[0]["rule"], "BTC004")

    def test_three_factors(self):

        score, rules, alert = score_bitcoin_transaction(
            make_event(amount=6),
            make_history(count=5, amount=1)
        )

        self.assertEqual(score, 70)
        self.assertEqual(len(rules), 3)
        self.assertTrue(alert)

    def test_four_factors(self):

        score, rules, alert = score_bitcoin_transaction(
            make_event(
                amount=6,
                output_count=12
            ),
            make_history(count=5, amount=1)
        )

        self.assertEqual(score, 85)
        self.assertEqual(len(rules), 4)
        self.assertTrue(alert)

    def test_insufficient_history(self):

        score, rules, alert = score_bitcoin_transaction(
            make_event(
                amount=6,
                output_count=12
            ),
            make_history(count=2)
        )

        self.assertEqual(score, 40)
        self.assertEqual(len(rules), 2)
        self.assertFalse(alert)


if __name__ == "__main__":
    unittest.main()
