
"""Deterministic hallucination checks for AML RAG output."""

import re


KNOWN_RULES = {
    "R001", "R002", "R003",
    "BTC001", "BTC002", "BTC003", "BTC004"
}

CITATION_PATTERN = re.compile(
    r"\[([^\[\]\n]+)\]"
)

NUMERIC_CITATION_PATTERN = re.compile(
    r"【[^】]+】"
)

RISK_SCORE_PATTERN = re.compile(
    r"\b(?:risk\s+score|score)"
    r"\s*(?:of|is|:|=)?\s*"
    r"(\d{1,3})(?:\s*/\s*100)?",
    re.IGNORECASE
)


def extract_citations(answer):
    return CITATION_PATTERN.findall(answer)


def detect_hallucinations(
    answer,
    retrieved_sources,
    expected_facts=None
):
    """
    Returns deterministic validation results.

    expected_facts, when supplied:
      risk_score: integer
      risk_level: string
      rule_ids: list of triggered rule IDs
    """

    issues = []
    allowed = set(retrieved_sources)

    if not isinstance(answer, str) or not answer.strip():
        issues.append("Empty model response.")
        return {
            "passed": False,
            "issues": issues
        }

    citations = extract_citations(answer)

    if NUMERIC_CITATION_PATTERN.search(answer):
        issues.append(
            "Unmapped numerical citations detected."
        )

    if not citations:
        issues.append("No source citations in answer.")

    for citation in citations:
        if citation not in allowed:
            issues.append(
                f"Unknown citation: [{citation}]"
            )

    mentioned_rules = set(
        re.findall(
            r"\b(?:BTC\d{3}|R\d{3})\b",
            answer,
            flags=re.IGNORECASE
        )
    )

    unknown_rules = mentioned_rules - KNOWN_RULES

    if unknown_rules:
        issues.append(
            "Unknown AML rule IDs: "
            + ", ".join(sorted(unknown_rules))
        )

    if expected_facts:
        expected_score = expected_facts.get("risk_score")
        expected_level = expected_facts.get("risk_level")
        triggered = set(expected_facts.get("rule_ids", []))

        if expected_score is not None:
            claimed_scores = [
                int(match)
                for match in RISK_SCORE_PATTERN.findall(answer)
            ]

            for score in claimed_scores:
                if score != expected_score:
                    issues.append(
                        f"Risk score mismatch: model={score}, "
                        f"database={expected_score}"
                    )

        # Check explicit final risk classifications.
        classifications = re.findall(
            r"\b(?:risk\s+level|risk\s+category)"
            r"\s*(?:is|:|=)?\s*"
            r"(LOW|MEDIUM|HIGH|CRITICAL)\b",
            answer,
            re.IGNORECASE
        )

        for level in classifications:
            if (
                expected_level
                and level.upper() != expected_level.upper()
            ):
                issues.append(
                    "Risk category contradicts database."
                )

        # Check direct claims that a rule was triggered.
        for rule in mentioned_rules:
            explicit_trigger = (
                re.search(
                    rf"\b{re.escape(rule)}\b"
                    rf"[^\n.]{{0,100}}"
                    rf"\b(?:triggered|flagged|activated)\b",
                    answer,
                    flags=re.IGNORECASE
                )
                or re.search(
                    rf"\b(?:triggered|flagged|activated)\b"
                    rf"[^\n.]{{0,100}}"
                    rf"\b{re.escape(rule)}\b",
                    answer,
                    flags=re.IGNORECASE
                )
            )

            if explicit_trigger and rule not in triggered:
                issues.append(
                    f"Unsupported triggered-rule claim: {rule}"
                )

    return {
        "passed": len(issues) == 0,
        "issues": sorted(set(issues)),
        "citations": citations
    }
