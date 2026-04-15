from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx


class LLMClient:
    def __init__(self, config_path: str | Path | None = None) -> None:
        if config_path is None:
            config_path = Path(__file__).parent.parent / "config" / "llm.toml"
        self.config = self._load_config(config_path)
        # Priority: env var > config file fallback
        api_key_env = self.config.get("api_key_env", "KIMI_API_KEY")
        config_fallback = self.config.get("api_key", "")
        self.api_key = os.environ.get(api_key_env, "") or config_fallback
        if not self.api_key:
            import warnings
            warnings.warn(
                f"LLM API key not set. Set env var '{api_key_env}' or add 'api_key' to llm.toml. "
                "LLM-powered features will be unavailable.",
                stacklevel=2,
            )
        self.base_url = self.config["base_url"]
        self.model = self.config["model"]
        self.temperature = self.config.get("temperature", 0.2)
        self.json_temperature = self.config.get("json_temperature", 0.2)
        self.max_tokens = self.config.get("max_tokens", 4096)
        self.timeout = self.config.get("timeout_seconds", 60)
        self.max_retries = self.config.get("max_retries", 2)

    def _uses_kimi_k25(self) -> bool:
        return self.model.startswith("kimi-k2.5")

    def _load_config(self, path: Path) -> dict[str, Any]:
        import tomli

        with open(path, "rb") as f:
            data = tomli.load(f)
        return data.get("provider", {}).get("openai", {})

    @staticmethod
    def _extract_content(message: Any) -> str:
        if isinstance(message, str):
            return message
        if isinstance(message, list):
            parts: list[str] = []
            for item in message:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str):
                        parts.append(text)
            return "".join(parts)
        return ""

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _payload(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float | None,
        stream: bool = False,
        response_format: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": self.max_tokens,
        }
        # Kimi K2.5 rejects arbitrary temperature values; omit the field and use
        # the provider default instead of sending a value that triggers HTTP 400.
        if temperature is not None and not self._uses_kimi_k25():
            payload["temperature"] = temperature
        if self._uses_kimi_k25():
            payload["thinking"] = {"type": "enabled"}
        if stream:
            payload["stream"] = True
        if response_format is not None:
            payload["response_format"] = response_format
        return payload

    def _stream_timeout(self) -> httpx.Timeout:
        return httpx.Timeout(
            connect=15.0,
            read=max(self.timeout, 120.0),
            write=30.0,
            pool=30.0,
        )

    def _iter_sse_events(self, resp: httpx.Response):
        """Yield reasoning/content events from an SSE stream response."""
        for line in resp.iter_lines():
            if not line.startswith("data: "):
                continue
            data = line[6:]
            if data.strip() == "[DONE]":
                break
            try:
                chunk = json.loads(data)
                delta = chunk["choices"][0].get("delta", {})
                reasoning = self._extract_content(delta.get("reasoning_content", ""))
                if reasoning:
                    yield {"type": "reasoning", "text": reasoning}
                content = self._extract_content(delta.get("content", ""))
                if content:
                    yield {"type": "content", "text": content}
            except Exception:
                continue

    def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> dict[str, Any]:
        timeout = self._stream_timeout()
        for attempt in range(self.max_retries + 1):
            try:
                collected: list[str] = []
                with httpx.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    headers=self._headers(),
                    json=self._payload(
                        system_prompt,
                        user_prompt,
                        temperature=self.json_temperature,
                        stream=True,
                        response_format={"type": "json_object"},
                    ),
                    timeout=timeout,
                ) as resp:
                    resp.raise_for_status()
                    for event in self._iter_sse_events(resp):
                        if event.get("type") == "content":
                            collected.append(event.get("text", ""))
                content = "".join(collected)
                if not content:
                    raise ValueError("LLM returned empty content")
                return json.loads(content)
            except Exception as e:
                if attempt == self.max_retries:
                    raise RuntimeError(f"LLM request failed after {self.max_retries} retries: {e}")
        raise RuntimeError(f"LLM request failed after {self.max_retries} retries")

    def chat_stream(
        self,
        system_prompt: str,
        user_prompt: str,
    ):
        """Stream LLM response as text chunks (generator)."""
        timeout = self._stream_timeout()
        for attempt in range(self.max_retries + 1):
            try:
                with httpx.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    headers=self._headers(),
                    json=self._payload(
                        system_prompt,
                        user_prompt,
                        temperature=self.json_temperature,
                        stream=True,
                        response_format={"type": "json_object"},
                    ),
                    timeout=timeout,
                ) as resp:
                    resp.raise_for_status()
                    for event in self._iter_sse_events(resp):
                        if event.get("type") == "content":
                            text = event.get("text", "")
                            if text:
                                yield text
                return
            except Exception as e:
                if attempt == self.max_retries:
                    raise RuntimeError(f"LLM streaming request failed after {self.max_retries} retries: {e}")

    def chat_text_stream(
        self,
        system_prompt: str,
        user_prompt: str,
    ):
        """Stream plain-language text for direct user display."""
        timeout = self._stream_timeout()
        for attempt in range(self.max_retries + 1):
            try:
                with httpx.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    headers=self._headers(),
                    json=self._payload(
                        system_prompt,
                        user_prompt,
                        temperature=self.temperature,
                        stream=True,
                    ),
                    timeout=timeout,
                ) as resp:
                    resp.raise_for_status()
                    yield from self._iter_sse_events(resp)
                return
            except Exception as e:
                if attempt == self.max_retries:
                    raise RuntimeError(
                        f"LLM text streaming request failed after {self.max_retries} retries: {e}"
                    )
