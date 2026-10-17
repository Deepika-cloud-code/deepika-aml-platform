
"""Bitcoin AML detection rules."""

from datetime import datetime, timedelta
from statistics import median


RULE_POINTS = {
    "BTC001": 25,
    "BTC002": 20,
    "BTC003": 25,
    "BTC004": 15
}


def score_bitcoin_transaction(event, history):
    """
    Calculate risk score for one Bitcoin transaction.

    event:
        Current normalized Bitcoin transaction.

    history:
        Previously processed Bitcoin transactions.

    Returns:
        risk_score, triggered_rules, should_alert
    """

    score = 0
    rules = []

    current_time = event["observation_time"]

    if (
        not isinstance(current_time, datetime)
        or current_time.tzinfo is None
    ):
        raise ValueError(
            "observation_time must be timezone-aware"
        )

    amount = float(event.get("output_btc") or 0)

    output_count = int(
        event.get("output_count") or 0
    )

    addresses = set(
        event.get("input_addresses") or []
    )

    # ---------------------------------
    # BTC001: High transaction value
    # ---------------------------------

    if amount >= 5:

        score += RULE_POINTS["BTC001"]

        rules.append({
            "rule": "BTC001",
            "reason": "Total outputs >= 5 BTC",
            "points": 25
        })

    # ---------------------------------
    # Identify related address history
    # ---------------------------------

    cutoff = current_time - timedelta(hours=24)

    related = []

    for previous in history:

        shared_addresses = (
            addresses & previous["addresses"]
        )

        within_window = (
            cutoff <= previous["event_time"]
            <= current_time
        )

        if shared_addresses and within_window:
            related.append(previous)

    # ---------------------------------
    # BTC002: Transaction frequency
    # ---------------------------------

    if len(related) + 1 >= 5:

        score += RULE_POINTS["BTC002"]

        rules.append({
            "rule": "BTC002",
            "reason": (
                "Input address observed in "
                "at least 5 transactions in 24h"
            ),
            "points": 20
        })

    # ---------------------------------
    # BTC003: Historical amount anomaly
    # ---------------------------------

    previous_amounts = [
        float(tx["amount_btc"])
        for tx in related
        if float(tx["amount_btc"]) > 0
    ]

    if len(previous_amounts) >= 5:

        baseline = median(previous_amounts)

        if baseline > 0 and amount >= 3 * baseline:

            score += RULE_POINTS["BTC003"]

            rules.append({
                "rule": "BTC003",
                "reason": (
                    "Transaction outputs are >= 3x "
                    "historical median"
                ),
                "points": 25
            })

    # ---------------------------------
    # BTC004: Multiple outputs
    # ---------------------------------

    if output_count >= 10:

        score += RULE_POINTS["BTC004"]

        rules.append({
            "rule": "BTC004",
            "reason": "Transaction has >= 10 outputs",
            "points": 15
        })

    score = min(score, 100)

    # Require multiple independent factors.
    should_alert = (
        len(rules) >= 3
        and score >= 60
    )

    return score, rules, should_alert
