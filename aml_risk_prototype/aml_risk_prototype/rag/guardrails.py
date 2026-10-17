
"""Basic application guardrails for the AML RAG chatbot."""

import hashlib
import json
import re
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = ROOT / "data" / "guardrail_audit.jsonl"

MAX_QUESTION_LENGTH = 1000
MAX_DOCUMENT_LENGTH = 5500
MAX_REQUESTS_PER_MINUTE = 20

INJECTION_PATTERNS = [
    r"ignore (?:all |your |the )?(?:previous|prior|system) instructions",
    r"disregard (?:all |your )?(?:previous|system) instructions",
    r"reveal (?:your |the )?(?:system prompt|developer instructions)",
    r"bypass (?:all |the )?(?:security|guardrails|safety checks)",
    r"disable (?:the )?(?:guardrails|validation|security)",
    r"you are now (?:in )?(?:developer|admin|unrestricted) mode",
]

SECRET_PATTERNS = [
    (
        r"(?i)(?:sk-[A-Za-z0-9_-]{16,})",
        "[REDACTED_API_KEY]"
    ),
    (
        r"(?i)(?:bearer\s+)[A-Za-z0-9._-]{12,}",
        "[REDACTED_TOKEN]"
    ),
    (
        r"(?i)(?:AccountKey|SharedAccessKey)\s*=\s*[^;\s]+",
        "[REDACTED_SECRET]"
    ),
]

CUSTOMER_PATTERN = re.compile(
    r"\bCUST-[A-Za-z0-9_-]+\b",
    re.IGNORECASE
)

EMAIL_PATTERN = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
)

PHONE_PATTERN = re.compile(
    r"(?<!\w)(?:\+1[-. ]?)?\(?\d{3}\)?[-. ]?\d{3}[-. ]?\d{4}(?!\w)"
)


class GuardrailError(Exception):
    """Raised when an application security check fails."""


def validate_input(question):
    if not isinstance(question, str):
        raise GuardrailError("Question must be text.")

    question = question.strip()

    if not question:
        raise GuardrailError("Please enter an AML question.")

    if len(question) > MAX_QUESTION_LENGTH:
        raise GuardrailError(
            f"Question exceeds {MAX_QUESTION_LENGTH} characters."
        )

    if "\x00" in question:
        raise GuardrailError("Invalid control character detected.")

    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, question, re.IGNORECASE):
            raise GuardrailError(
                "Question contains a disallowed instruction pattern."
            )

    return question


def redact_sensitive(text):
    """Mask common credentials and personal identifiers."""
    if not isinstance(text, str):
        return ""

    result = text

    for pattern, replacement in SECRET_PATTERNS:
        result = re.sub(pattern, replacement, result)

    result = CUSTOMER_PATTERN.sub(
        "[REDACTED_CUSTOMER]", result
    )
    result = EMAIL_PATTERN.sub("[REDACTED_EMAIL]", result)
    result = PHONE_PATTERN.sub("[REDACTED_PHONE]", result)

    return result


def validate_context(documents):
    """Allowlist sources and sanitize external LLM context."""

    if not isinstance(documents, list):
        raise GuardrailError("Invalid retrieval result.")

    if len(documents) > 12:
        raise GuardrailError("Too many retrieved documents.")

    sanitized = []
    seen = set()

    for doc in documents:
        if not isinstance(doc, dict):
            raise GuardrailError("Invalid document.")

        doc_id = doc.get("id")
        text = doc.get("text")

        if not isinstance(doc_id, str):
            raise GuardrailError("Missing source identifier.")

        if not isinstance(text, str):
            raise GuardrailError("Invalid document content.")

        allowed = (
            doc_id.startswith("bitcoin:")
            or doc_id.startswith("synthetic:")
            or re.fullmatch(r"policy:\d+", doc_id) is not None
        )

        if not allowed:
            raise GuardrailError(
                "Unrecognized retrieval source."
            )

        if doc_id in seen:
            continue

        seen.add(doc_id)

        # Remove lines matching obvious injected commands.
        safe_lines = []

        for line in text.splitlines():
            if any(
                re.search(p, line, re.IGNORECASE)
                for p in INJECTION_PATTERNS
            ):
                continue
            safe_lines.append(line)

        cleaned = redact_sensitive(
            "\n".join(safe_lines)
        )

        sanitized.append({
            "id": doc_id,
            "text": cleaned[:MAX_DOCUMENT_LENGTH]
        })

    return sanitized


class RateLimiter:
    """Simple per-process request limiter."""

    def __init__(self, limit=MAX_REQUESTS_PER_MINUTE):
        self.limit = limit
        self.calls = deque()

    def check(self):
        now = time.monotonic()

        while self.calls and now - self.calls[0] >= 60:
            self.calls.popleft()

        if len(self.calls) >= self.limit:
            raise GuardrailError(
                "Request limit reached. Try again shortly."
            )

        self.calls.append(now)


def audit_event(event_type, status, details=""):
    """Log minimal metadata, not raw questions or evidence."""

    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)

    record = {
        "timestamp": datetime.now(
            timezone.utc
        ).isoformat(),
        "event_type": event_type,
        "status": status,
        "details_hash": hashlib.sha256(
            str(details).encode("utf-8")
        ).hexdigest()[:16]
    }

    with AUDIT_PATH.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record) + "\n")


def safe_failure_response(
    reason,
    facts=None,
    sources=None,
    issues=None
):
    """Return a clear fallback without inventing evidence."""

    sources = sources or []
    issues = issues or []

    if reason == "NO_EVIDENCE":
        return {
            "answer": (
                "I couldn't find sufficient supporting evidence "
                "in the current AML knowledge base to answer "
                "that question reliably.\n\n"
                "Try specifying a transaction ID, risk rule, "
                "or a supported SQL analytics query."
            ),
            "sources": [],
            "guardrail_status": "INSUFFICIENT_EVIDENCE",
            "hallucination_issues": []
        }

    if reason == "CITATION_FAILURE":
        return {
            "answer": (
                "I found potentially relevant AML documents, "
                "but the generated explanation did not contain "
                "verifiable source references.\n\n"
                "I have withheld that explanation rather than "
                "presenting unsupported claims. You can retry "
                "the question or inspect the retrieved evidence."
            ),
            "sources": sources,
            "guardrail_status": "CITATION_FAILED",
            "hallucination_issues": issues
        }

    if reason == "FACT_MISMATCH":
        if facts:
            rules = facts.get("rules", [])

            rule_text = "\n".join(
                f"- {rule['rule']}: +{rule['points']} points"
                for rule in rules
            ) or "- No triggered rules"

            answer = (
                "The generated answer contradicted a verified "
                "transaction fact, so it was withheld.\n\n"
                "**Verified Gold database values:**\n"
                f"- Transaction: {facts['event_id']}\n"
                f"- Risk score: {facts['risk_score']}/100\n"
                f"- Risk level: {facts['risk_level']}\n"
                f"- Triggered rules:\n{rule_text}\n\n"
                f"Source: [{facts['event_id']}]"
            )
        else:
            answer = (
                "The generated explanation failed factual "
                "validation. No verified alternative answer "
                "is available for this question."
            )

        return {
            "answer": answer,
            "sources": sources,
            "guardrail_status": "FACT_CHECK_FAILED",
            "hallucination_issues": issues
        }

    return {
        "answer": (
            "The answer could not be verified using the "
            "available AML evidence. No unsupported explanation "
            "was returned."
        ),
        "sources": sources,
        "guardrail_status": "FALLBACK",
        "hallucination_issues": issues
    }
