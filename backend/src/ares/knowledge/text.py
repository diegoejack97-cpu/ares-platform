"""UTF-8 text only: no macros, HTML execution, archive extraction, or remote URLs."""

import hashlib
import re

from ares.intelligence.context_builder import ContextUnavailable

SENSITIVE = re.compile(
    r"(?i)(-----BEGIN .*PRIVATE KEY|\bBearer\s+[\w.\-]{12,}|\bsk-[\w\-]{16,}"
    r"|\beyJ[\w\-]+\.[\w\-]+\.[\w\-]+|\b[\w.+-]+@[\w.-]+\.[a-z]{2,}\b"
    r"|\b\d{3}\.\d{3}\.\d{3}-\d{2}\b"
    r"|(?:api[_ -]?key|password|senha|secret|token)\s*[:=]\s*\S+)"
)


def safe_text(value: str) -> str:
    if "\x00" in value or any(ord(c) < 32 and c not in "\n\r\t" for c in value):
        raise ContextUnavailable("document_encoding_invalid", 422)
    value = value.replace("\r\n", "\n").strip()
    if len(value.encode("utf-8")) > 262144:
        raise ContextUnavailable("document_too_large", 413)
    if SENSITIVE.search(value):
        raise ContextUnavailable("document_sensitive_content", 422)
    return value


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def chunks(value: str) -> list[str]:
    # Character boundaries, byte-bounded, disjoint source spans; citations remain literal.
    result, part = [], ""
    for word in value.splitlines(keepends=True):
        for char in word:
            if len((part + char).encode()) > 1800:
                result.append(part)
                part = ""
            part += char
    if part:
        result.append(part)
    if len(result) > 160:
        raise ContextUnavailable("document_chunk_limit", 422)
    return result
