# ADR 0006: Cassette Replay Pattern for Evaluation and E2E Tests

## Status

accepted

## Date

2026-05-24

## Context

Our coding conventions mandate that:

1. `make test` must run completely offline without hitting external networks and with no `OPENAI_API_KEY` required.
2. We must not mock the LLM API in evaluation tests because mocking is coupled to implementation details and fails to capture structural shifts in model outputs.

To test end-to-end features (like unanswerable question abstention scoring) where a real LLM is called, we need a way to capture the real API response and replay it deterministically during testing.

## Decision

We adopt the **Cassette Replay** pattern using the `vcrpy` library.

1. **How it works**: VCR intercepts outgoing HTTP requests made by the HTTP client (like the OpenAI SDK). If a matching request is found in a recorded YAML cassette, it is replayed immediately. Otherwise, it issues the real network call (if recording) or raises an error (if offline).
2. **Offline default**: Under pytest, the default VCR record mode is set to `"none"`. This ensures that if a cassette is missing or a request changes, the test fails rather than silently hitting the network.
3. **Record opt-in**: Developers and maintainers can opt-in to recording or updating cassettes by running tests with the `VCR_RECORD_MODE=once` environment variable.
4. **Header Scrubbing**: Cassettes scrub sensitive headers (specifically the HTTP `Authorization` header) before serializing to YAML, keeping keys safe.

## Consequences

- E2E and evaluation assertions can be run on real model responses without needing a live network or api key during testing.
- VCR cassettes are committed to the repository under `tests/eval/cassettes/`.
- If prompt templates or schemas change, cassettes must be re-recorded by a maintainer with `VCR_RECORD_MODE=once`.
