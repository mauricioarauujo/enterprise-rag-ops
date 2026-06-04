"""Tests for the RawCall typed transport model (AC-1)."""

import pytest
from pydantic import ValidationError

from enterprise_rag_ops.eval.raw_call import RawCall


def test_raw_call_round_trip():
    """Assert RawCall can round-trip through JSON serialization and forbids extra fields."""
    request_payload = {"model": "test-model", "messages": [{"role": "user", "content": "hi"}]}
    response_payload = {"choices": [{"message": {"content": "hello"}}]}

    call = RawCall(request=request_payload, response=response_payload)
    assert call.request == request_payload
    assert call.response == response_payload

    # Test round trip
    json_str = call.model_dump_json()
    parsed = RawCall.model_validate_json(json_str)
    assert parsed.request == request_payload
    assert parsed.response == response_payload

    # Test extra forbid config
    with pytest.raises(ValidationError):
        RawCall(request=request_payload, response=response_payload, extra_field="forbidden")
