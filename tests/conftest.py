"""Root test fixtures shared across the whole suite.

Hosts the single vcrpy configuration used by every cassette-replay test (ADR-0006):
one fixture, one scrubbing policy — so request credentials and account-identifying
response headers never reach a committed cassette (privacy + the stranger test).
"""

from __future__ import annotations

import os

import pytest
import vcr

# Request headers carrying credentials — OpenAI sends `authorization`, Anthropic `x-api-key`,
# Google Gemini (google-genai) sends `x-goog-api-key`.
_FILTER_REQUEST_HEADERS = ["authorization", "x-api-key", "x-goog-api-key"]

# Query params carrying credentials — the google-genai SDK can pass the key as `?key=`.
_FILTER_QUERY_PARAMS = ["key"]

# Response headers that identify the recording account or carry session state. These must
# never land in a public cassette; vcrpy 6's `filter_headers` only covers request headers,
# so response scrubbing goes through `before_record_response`.
_SCRUB_RESPONSE_HEADERS = {
    "anthropic-organization-id",
    "openai-organization",
    "set-cookie",
    "cf-ray",
    "request-id",
}


def _scrub_response(response: dict) -> dict:
    """Drop identifying response headers before a cassette is written (record-time only)."""
    headers = response.get("headers")
    if headers:
        for name in list(headers):
            if name.lower() in _SCRUB_RESPONSE_HEADERS:
                headers.pop(name)
    return response


@pytest.fixture
def vcr_record() -> vcr.VCR:
    """Shared VCR config: scrubs request credentials and identifying response headers.

    Defaults to `record_mode="none"` (offline replay only, ADR-0006); override with the
    `VCR_RECORD_MODE` env var to re-record. Cassettes live in `tests/eval/cassettes`.
    """
    return vcr.VCR(
        cassette_library_dir="tests/eval/cassettes",
        record_mode=os.environ.get("VCR_RECORD_MODE", "none"),
        filter_headers=_FILTER_REQUEST_HEADERS,
        filter_query_parameters=_FILTER_QUERY_PARAMS,
        before_record_response=_scrub_response,
    )
