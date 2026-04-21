"""Tests for retry discrimination and cancellation in :class:`LLMClient`."""

from __future__ import annotations

import httpx
import pytest

from aptgent.llm.client import LLMCancelled, _is_retryable


def _http_status(code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://example.com")
    response = httpx.Response(code, request=request)
    return httpx.HTTPStatusError("boom", request=request, response=response)


def test_is_retryable_server_errors_and_rate_limit():
    assert _is_retryable(_http_status(500)) is True
    assert _is_retryable(_http_status(502)) is True
    assert _is_retryable(_http_status(429)) is True


def test_is_retryable_client_errors_are_not():
    assert _is_retryable(_http_status(400)) is False
    assert _is_retryable(_http_status(401)) is False
    assert _is_retryable(_http_status(404)) is False


def test_is_retryable_network_and_timeout():
    assert _is_retryable(httpx.TimeoutException("slow")) is True
    assert _is_retryable(httpx.ConnectError("down")) is True
    assert _is_retryable(httpx.RemoteProtocolError("closed")) is True


def test_is_retryable_does_not_retry_value_errors():
    assert _is_retryable(ValueError("bad json")) is False


def test_llm_cancelled_is_a_distinct_exception():
    with pytest.raises(LLMCancelled):
        raise LLMCancelled()
