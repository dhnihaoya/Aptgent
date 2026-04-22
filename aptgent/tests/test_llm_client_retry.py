"""Tests for retry discrimination and cancellation in :class:`LLMClient`."""

from __future__ import annotations

import httpx
import pytest

from aptgent.llm.client import LLMCancelled, LLMClient, _is_retryable


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


def test_chat_json_events_streams_reasoning_and_final_json(tmp_path, monkeypatch):
    config_path = tmp_path / "llm.toml"
    config_path.write_text(
        "\n".join(
            [
                "[provider.openai]",
                'base_url = "https://example.com/v1"',
                'model = "glm-5.1"',
                'fast_model = "glm-4.7-flashx"',
                'api_key = "test-key"',
                "temperature = 1",
                "json_temperature = 0.2",
            ]
        ),
        encoding="utf-8",
    )
    captured_payload = {}

    class FakeStreamResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def raise_for_status(self):
            return None

        def iter_lines(self):
            return iter(
                [
                    'data: {"choices":[{"delta":{"reasoning_content":"thinking"}}]}',
                    'data: {"choices":[{"delta":{"content":"{\\"proposals\\":[]}"}}]}',
                    "data: [DONE]",
                ]
            )

    def fake_stream(_method, _url, *, headers, json, timeout):
        captured_payload.update(json)
        return FakeStreamResponse()

    monkeypatch.setattr(httpx, "stream", fake_stream)

    client = LLMClient(config_path=config_path)
    events = list(client.chat_json_events("system", "user"))

    assert events == [
        {"type": "reasoning", "text": "thinking"},
        {"type": "result", "value": {"proposals": []}},
    ]
    assert captured_payload["response_format"] == {"type": "json_object"}
    assert captured_payload["thinking"] == {"type": "enabled"}
    assert captured_payload["model"] == "glm-5.1"
