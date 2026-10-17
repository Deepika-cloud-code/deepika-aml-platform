
"""Read-only AML analytics with evidence-aware responses."""

import re
import json

from aml.core import connect


LEVELS = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}

NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "ten": 10
}


def parse_limit(question):
    q = question.lower()

    match = re.search(
        r"\btop\s+(\d+|one|two|three|four|five|ten)\b",
        q
    )

    if match:
        value = match.group(1)
        number = (
            int(value) if value.isdigit()
            else NUMBER_WORDS[value]
        )
        return min(max(number, 1), 20)

    return 5


def detect_analytics_query(question):
    """Recognize supported numerical risk queries."""

    q = question.lower().strip()

    ranking = bool(re.search(
        r"\b(top|highest|riskiest|show|list|find)\b",
        q
    ))

    if not ranking:
        return None

    level_match = re.search(
        r"\b(critical|high|medium|low)"
        r"(?:[- ]risk)?\b",
        q
    )

    score_match = re.search(
        r"\b(?:risk\s+)?scor(?:e|ed|es|ing)"
        r"\s*(?:of|is|are|was|were|:)?\s*"
        r"(?:more than|greater than|above|over|"
        r"at least|minimum of|less than|below|under|"
        r">=|<=|>|<|equal to|exactly)\s*\d+",
        q
    )

    # Also recognize: "events with risk score > 60"
    if not score_match:
        score_match = re.search(
            r"(?:more than|greater than|above|over|"
            r"at least|less than|below|under|"
            r">=|<=|>|<|equal to|exactly)"
            r"\s*\d+\b",
            q
        )

    if not level_match and not score_match:
        return None

    intent = {
        "limit": parse_limit(question),
        "risk_level": (
            level_match.group(1).upper()
            if level_match else None
        ),
        "operator": None,
        "threshold": None
    }

    if score_match:
        expression = score_match.group(0)

        number_match = re.search(r"\d+\b", expression)

        if number_match:
            intent["threshold"] = int(
                number_match.group()
            )

            if re.search(
                r"more than|greater than|above|over|(?<![<>=])>(?!=)",
                expression
            ):
                intent["operator"] = ">"

            elif re.search(
                r"at least|minimum of|>=",
                expression
            ):
                intent["operator"] = ">="

            elif re.search(
                r"less than|below|under|(?<![<>=])<(?!=)",
                expression
            ):
                intent["operator"] = "<"

            elif "<=" in expression:
                intent["operator"] = "<="

            elif re.search(r"equal to|exactly", expression):
                intent["operator"] = "="

    return intent


def run_risk_query(intent):
    """Execute an allowlisted, parameterized SQL query."""

    conditions = []
    params = []

    if intent["risk_level"]:
        if intent["risk_level"] not in LEVELS:
            raise ValueError("Invalid risk level")

        conditions.append("g.risk_level = ?")
        params.append(intent["risk_level"])

    operator = intent["operator"]
    threshold = intent["threshold"]

    allowed_operators = {
        ">", ">=", "<", "<=", "="
    }

    if operator is not None:
        if operator not in allowed_operators:
            raise ValueError("Invalid comparison")

        if threshold is None or not 0 <= threshold <= 100:
            raise ValueError("Invalid risk threshold")

        # SQL operator is chosen only from the allowlist.
        conditions.append(f"g.risk_score {operator} ?")
        params.append(threshold)

    where_clause = (
        " WHERE " + " AND ".join(conditions)
        if conditions else ""
    )

    with connect() as db:
        total = db.execute(
            """
            SELECT COUNT(*) AS total
            FROM gold_risk_scores g
            """ + where_clause,
            tuple(params)
        ).fetchone()["total"]

        rows = db.execute(
            """
            SELECT
                g.event_id,
                g.source,
                g.risk_score,
                g.risk_level,
                g.amount_usd,
                g.amount_btc,
                g.triggered_rules,
                a.status AS alert_status
            FROM gold_risk_scores g
            LEFT JOIN gold_aml_alerts a
                ON g.event_id = a.event_id
            """ + where_clause + """
            ORDER BY g.risk_score DESC, g.event_id
            LIMIT ?
            """,
            tuple(params + [intent["limit"]])
        ).fetchall()

    return total, [dict(row) for row in rows]


def describe_filter(intent):
    labels = []

    if intent["risk_level"]:
        labels.append(
            f"{intent['risk_level']} risk"
        )

    if intent["operator"]:
        labels.append(
            f"risk score {intent['operator']} "
            f"{intent['threshold']}"
        )

    return " and ".join(labels)


def answer_analytics(question):
    """Return deterministic SQL results or None if not supported."""

    intent = detect_analytics_query(question)

    if intent is None:
        return None

    total, records = run_risk_query(intent)
    description = describe_filter(intent)

    if not records:
        return {
            "answer": (
                f"No transactions matching **{description}** "
                "were found in the current Gold risk-score table.\n\n"
                "**Matching records: 0.** "
                "This result was verified directly against SQLite.\n\n"
                "This does not mean the detection rules are "
                "incorrect; it means the currently scored dataset "
                "contains no matching records."
            ),
            "sources": [],
            "guardrail_status": "NO_MATCH",
            "hallucination_issues": []
        }

    lines = [
        f"### Top {len(records)} transactions matching {description}",
        "",
        f"**Total matching transactions:** {total}",
        ""
    ]

    for index, tx in enumerate(records, 1):
        if tx["amount_btc"] is not None:
            amount = f"{tx['amount_btc']:.8f} BTC"
        elif tx["amount_usd"] is not None:
            amount = f"${tx['amount_usd']:,.2f}"
        else:
            amount = "Not available"

        rules = json.loads(tx["triggered_rules"] or "[]")

        rule_ids = [
            rule.get("rule", "Unknown")
            for rule in rules
        ]

        lines.extend([
            f"**{index}. {tx['event_id']}**",
            f"- Source: {tx['source']}",
            f"- Risk score: {tx['risk_score']}/100",
            f"- Risk level: {tx['risk_level']}",
            f"- Amount: {amount}",
            f"- Triggered rules: "
            + (", ".join(rule_ids) if rule_ids else "None"),
            f"- Alert status: "
            + (tx["alert_status"] or "No alert"),
            ""
        ])

    lines.append(
        "Source: Live query of the local "
        "`gold_risk_scores` table. "
        "Scores are review priorities, not fraud probabilities."
    )

    return {
        "answer": "\n".join(lines),
        "sources": [r["event_id"] for r in records],
        "guardrail_status": "SQL_VERIFIED",
        "hallucination_issues": []
    }
