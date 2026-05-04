from __future__ import annotations

import re
from typing import Iterable


NON_RETRYABLE_ERROR_MARKERS: tuple[str, ...] = (
    "401",
    "403",
    "authentication",
    "unauthorized",
    "not authorized",
    "forbidden",
    "authentication failed",
    "authentication error",
    "permission denied",
    "access denied",
    "permission error",
    "unsupported parameter",
    "unsupported service_tier",
    "model not found",
    "does not exist",
    "invalid api key",
    "incorrect api key",
    "insufficient_quota",
    "quota exceeded",
    "billing hard limit",
    "billing limit",
    "billing_limit_reached",
    "hard limit reached",
    "payment required",
    "context_length_exceeded",
    "maximum context length",
    "context window",
)


RETRYABLE_ERROR_MARKERS: tuple[str, ...] = (
    "timeout",
    "timed out",
    "408",
    "409",
    "429",
    "524",
    "522",
    "520",
    "502",
    "503",
    "504",
    "network error",
    "too many requests",
    "rate limit",
    "rate_limit",
    "remote end closed connection",
    "incompleteread",
    "connection reset",
    "connection aborted",
    "broken pipe",
    "ssl eof",
    "unexpected eof",
    "unexpected eof while reading",
    "stream_read_error",
    "stream read error",
    "streaming response completed without text",
    "could not extract text from responses payload",
    "provider stream request failed without an error",
    "failed to read request body",
    "invalid_request_error",
    "concurrency limit exceeded",
    "concurrency limit exceeded for user",
    "concurrency limit exceeded for account",
    "please retry later",
    "upstream request failed",
    "server had an error processing your request",
    "an error occurred while processing your request",
    "please retry your request",
    "clientconn.close",
    "force closed via clientconn.close",
    "client connection force closed",
    "http2: client connection force closed",
)


SOFT_RETRYABLE_UPSTREAM_MARKERS: tuple[str, ...] = (
    "internal_error",
    "internal error",
    "received from peer",
    "stream id",
    "stream error",
    "temporary failure",
    "temporarily unavailable",
    "service unavailable",
    "bad gateway",
    "gateway timeout",
    "upstream",
    "provider",
    "relay",
    "processing your request",
    "request failed",
    "request body",
    "read error",
    "connection closed",
    "connection dropped",
    "connection terminated",
    "force closed",
    "request timeout",
)


UPSTREAM_CONTEXT_MARKERS: tuple[str, ...] = (
    "stream",
    "gateway",
    "provider",
    "relay",
    "upstream",
    "server",
    "peer",
    "request",
    "connection",
    "network",
    "ssl",
    "http",
)


RETRYABLE_OVERRIDE_MARKERS: tuple[str, ...] = (
    "upstream access forbidden, please contact administrator",
)


def is_non_retryable_error_text(text: str, *, extra_markers: Iterable[str] = ()) -> bool:
    haystack = text.lower()
    markers = (*NON_RETRYABLE_ERROR_MARKERS, *(marker.lower() for marker in extra_markers))
    return any(marker in haystack for marker in markers)


def is_retryable_error_text(text: str, *, extra_markers: Iterable[str] = ()) -> bool:
    haystack = text.lower()
    override_markers = (*RETRYABLE_OVERRIDE_MARKERS, *(marker.lower() for marker in extra_markers))
    if any(marker in haystack for marker in override_markers):
        return True
    if is_non_retryable_error_text(haystack):
        return False
    markers = (*RETRYABLE_ERROR_MARKERS, *(marker.lower() for marker in extra_markers))
    if any(marker in haystack for marker in markers):
        return True
    if re.search(r"\bhttp\s*(5\d\d)\b", haystack) or re.search(r"\berror code:\s*5\d\d\b", haystack):
        return True
    if any(marker in haystack for marker in SOFT_RETRYABLE_UPSTREAM_MARKERS):
        return True
    if "error" in haystack and any(marker in haystack for marker in UPSTREAM_CONTEXT_MARKERS):
        return True
    return False
