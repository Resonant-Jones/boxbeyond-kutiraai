"""Redaction helpers used before any execution record becomes a candidate."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

_CREDENTIAL_KEYS = re.compile(
    r"(?:api[_-]?key|access[_-]?key|secret|password|token|authorization|cookie|credential|private[_-]?key)",
    re.IGNORECASE,
)
_ACCOUNT_KEYS = re.compile(
    r"(?:email|phone|user[_-]?id|account(?:[_-]?id)?|customer[_-]?id|org(?:anization)?[_-]?id)",
    re.IGNORECASE,
)
_PRIVATE_KEYS = re.compile(
    r"(?:prompt|message|conversation|transcript|body|content|raw[_-]?text)",
    re.IGNORECASE,
)
_TOKEN = re.compile(
    r"(?i)\b(?:ghp_[A-Za-z0-9_\-]{20,}|sk-[A-Za-z0-9_\-]{20,}|xox[baprs]-[A-Za-z0-9-]{10,})\b"
)
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+\-/]+=*")
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)


def _redact_string(value: str, findings: List[str]) -> str:
    result = _TOKEN.sub("[REDACTED_CREDENTIAL]", value)
    result = _BEARER.sub("Bearer [REDACTED_CREDENTIAL]", result)
    if result != value:
        findings.append("credential-pattern")
    if _EMAIL.search(result):
        result = _EMAIL.sub("[REDACTED_ACCOUNT]", result)
        findings.append("account-pattern")
    return result


def redact_value(
    value: Any,
    *,
    key: str = "",
    allow_private_content: bool = False,
    findings: List[str] | None = None,
) -> Any:
    """Return a JSON-compatible redacted copy and record what was removed.

    When private content is not explicitly allowed, free-form prompt/message
    fields are replaced rather than copied into a candidate. Structured keys
    and shapes remain available for procedure extraction.
    """

    findings = findings if findings is not None else []
    if _CREDENTIAL_KEYS.search(key):
        findings.append(f"credential-key:{key}")
        return "[REDACTED_CREDENTIAL]"
    if _ACCOUNT_KEYS.search(key):
        findings.append(f"account-key:{key}")
        return "[REDACTED_ACCOUNT]"
    if key == "content_hash":
        return value
    if _PRIVATE_KEYS.search(key) and not allow_private_content:
        findings.append(f"private-content-key:{key}")
        return "[REDACTED_PRIVATE_CONTENT]"
    if isinstance(value, dict):
        return {
            str(child_key): redact_value(
                child_value,
                key=str(child_key),
                allow_private_content=allow_private_content,
                findings=findings,
            )
            for child_key, child_value in value.items()
        }
    if isinstance(value, list):
        return [
            redact_value(
                item,
                key=key,
                allow_private_content=allow_private_content,
                findings=findings,
            )
            for item in value
        ]
    if isinstance(value, str):
        return _redact_string(value, findings)
    return value


def redact_record_payload(
    payload: Dict[str, Any], *, allow_private_content: bool = False
) -> Tuple[Dict[str, Any], List[str]]:
    """Redact a record-shaped dictionary without mutating the input."""

    findings: List[str] = []
    redacted = redact_value(
        payload,
        allow_private_content=allow_private_content,
        findings=findings,
    )
    return redacted, sorted(set(findings))
