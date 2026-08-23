"""Free-text secret redaction for log lines and webhook bodies.

The Estate loader's secret detection walks keyed YAML structures; raw log
lines are opaque strings, so ingest needs its own detector. This redactor is
regex + entropy based and errs toward redaction on ambiguity. It runs before
records are routed anywhere — including the unmapped and DLQ topics, which
would otherwise concentrate exactly the credential-laden records.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

PLACEHOLDER = "[REDACTED]"

# Order matters: structured patterns first, generic entropy sweep last.
_PATTERNS: list[re.Pattern[str]] = [
    # Authorization headers: keep the scheme, drop the credential.
    re.compile(
        r"(?i)(?<=authorization)(\s*[:=]\s*)(basic|bearer|digest)?\s*[^\s,;]+"
    ),
    # JWTs (three base64url segments).
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    # AWS-style access key ids.
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    # Private key blocks.
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    # Passwords embedded in connection strings: scheme://user:password@host
    re.compile(r"(?<=://)([^\s:@/]+):([^@\s]+)(?=@)"),
    # key=value / key: value where the key is secret-shaped.
    re.compile(
        r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|apikey|access[_-]?key|"
        r"private[_-]?key|client[_-]?secret|session[_-]?key)\b"
        r"(\s*[=:]\s*)(\"[^\"]*\"|'[^']*'|[^\s,;&]+)"
    ),
]

# Generic long-token sweep: only redact when entropy is high enough that the
# string looks like key material rather than a word, path, or UUID.
_CANDIDATE_TOKEN = re.compile(r"\b[A-Za-z0-9+/_=-]{32,}\b")
_ENTROPY_THRESHOLD = 4.2


def _shannon_entropy(s: str) -> float:
    counts: dict[str, int] = {}
    for ch in s:
        counts[ch] = counts.get(ch, 0) + 1
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def _redact_high_entropy(text: str) -> tuple[str, int]:
    hits = 0

    def _sub(match: re.Match[str]) -> str:
        nonlocal hits
        token = match.group(0)
        has_alpha = any(ch.isalpha() for ch in token)
        has_digit = any(ch.isdigit() for ch in token)
        if has_alpha and has_digit and _shannon_entropy(token) >= _ENTROPY_THRESHOLD:
            hits += 1
            return PLACEHOLDER
        return token

    return _CANDIDATE_TOKEN.sub(_sub, text), hits


@dataclass(frozen=True)
class RedactionResult:
    text: str
    hits: int


def redact(text: str) -> RedactionResult:
    """Redact secret-shaped content from free text."""
    hits = 0
    for pattern in _PATTERNS:
        if pattern is _PATTERNS[0]:
            # Authorization header: preserve separator + scheme groups.
            def _auth_sub(match: re.Match[str]) -> str:
                nonlocal hits
                hits += 1
                scheme = match.group(2) or ""
                sep = match.group(1)
                joiner = " " if scheme else ""
                return f"{sep}{scheme}{joiner}{PLACEHOLDER}"

            text = pattern.sub(_auth_sub, text)
            continue
        if pattern.groups >= 3:
            # key=value form: keep key and separator, drop value.
            def _kv_sub(match: re.Match[str]) -> str:
                nonlocal hits
                hits += 1
                return f"{match.group(1)}{match.group(2)}{PLACEHOLDER}"

            text = pattern.sub(_kv_sub, text)
            continue
        if pattern.groups == 2:
            # connection string: keep user, drop password.
            def _conn_sub(match: re.Match[str]) -> str:
                nonlocal hits
                hits += 1
                return f"{match.group(1)}:{PLACEHOLDER}"

            text = pattern.sub(_conn_sub, text)
            continue

        text, n = pattern.subn(PLACEHOLDER, text)
        hits += n

    text, entropy_hits = _redact_high_entropy(text)
    hits += entropy_hits
    return RedactionResult(text=text, hits=hits)
