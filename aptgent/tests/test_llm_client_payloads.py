from __future__ import annotations

from aptgent.llm.client import LLMClient


def test_glm_payload_includes_temperature_and_thinking_by_default(tmp_path):
    config_path = tmp_path / "llm.toml"
    config_path.write_text(
        "\n".join(
            [
                "[provider.openai]",
                'base_url = "https://open.bigmodel.cn/api/paas/v4"',
                'model = "glm-5.1"',
                'api_key = "test-key"',
                "temperature = 1",
            ]
        ),
        encoding="utf-8",
    )

    client = LLMClient(config_path=config_path)
    payload = client._payload(
        "system",
        "user",
        temperature=0.2,
    )

    assert payload["temperature"] == 0.2
    assert payload["thinking"] == {"type": "enabled"}
    assert payload["model"] == "glm-5.1"
def test_json_payload_disables_thinking(tmp_path):
    config_path = tmp_path / "llm.toml"
    config_path.write_text(
        "\n".join(
            [
                "[provider.openai]",
                'base_url = "https://open.bigmodel.cn/api/paas/v4"',
                'model = "glm-5.1"',
                'api_key = "test-key"',
            ]
        ),
        encoding="utf-8",
    )

    client = LLMClient(config_path=config_path)
    payload = client._payload(
        "system",
        "user",
        temperature=0.2,
        response_format={"type": "json_object"},
        enable_thinking=False,
    )

    assert payload["model"] == "glm-5.1"
    assert "thinking" not in payload


def test_iter_sse_events_emits_reasoning_before_content(tmp_path):
    config_path = tmp_path / "llm.toml"
    config_path.write_text(
        "\n".join(
            [
                "[provider.openai]",
                'base_url = "https://open.bigmodel.cn/api/paas/v4"',
                'model = "glm-5.1"',
                'api_key = "test-key"',
            ]
        ),
        encoding="utf-8",
    )

    class FakeResponse:
        def iter_lines(self):
            yield 'data: {"choices":[{"delta":{"reasoning_content":"thinking "}}]}'
            yield 'data: {"choices":[{"delta":{"content":"answer"}}]}'
            yield "data: [DONE]"

    client = LLMClient(config_path=config_path)
    events = list(client._iter_sse_events(FakeResponse()))

    assert events == [
        {"type": "reasoning", "text": "thinking "},
        {"type": "content", "text": "answer"},
    ]
