from __future__ import annotations

import hashlib
import json
import logging
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import httpx

_log = logging.getLogger(__name__)


class LLMCancelled(Exception):
    """Raised when a caller's ``should_cancel`` hook signals cancellation."""


def _is_retryable(exc: BaseException) -> bool:
    """Retry on transient network failures and 5xx; never on 4xx client errors.

    Keeping this narrow is important: retrying a 400 (malformed request) or
    401 (bad credentials) only delays a permanent failure and wastes quota.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return status >= 500 or status == 429
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)):
        return True
    return False


class LLMClient:
    def __init__(self, config_path: str | Path | None = None) -> None:
        if config_path is None:
            config_path = Path(__file__).parent.parent / "config" / "llm.toml"
        self.config = self._load_config(config_path)
        # Priority: env var > config file fallback
        api_key_env = self.config.get("api_key_env", "GLM_API_KEY")
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
        self.fast_model = self.config.get("fast_model", self.model)
        self.temperature = self.config.get("temperature", 0.2)
        self.json_temperature = self.config.get("json_temperature", 0.2)
        self.max_tokens = self.config.get("max_tokens", 4096)
        self.timeout = self.config.get("timeout_seconds", 60)
        self.max_retries = self.config.get("max_retries", 2)
        self._thinking_enabled = True

        # LLM call logging
        self._log_dir: Path | None = None
        self._redact = os.environ.get("APTGENT_LLM_REDACT", "1") != "0"

    def set_log_dir(self, log_dir: str | Path) -> None:
        self._log_dir = Path(log_dir)
        self._log_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _redact_text(text: str) -> str:
        return "sha256:" + hashlib.sha256(text.encode()).hexdigest()[:16]

    def _log_call(
        self,
        *,
        method: str,
        system_prompt: str,
        user_prompt: str,
        response: Any = None,
    ) -> None:
        if self._log_dir is None:
            return
        entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "method": method,
            "provider": "openai",
            "model": self.model,
            "system_prompt": system_prompt[:200] if len(system_prompt) > 200 else system_prompt,
            "user_message": (
                self._redact_text(user_prompt) if self._redact else user_prompt
            ),
        }
        if response is not None:
            entry["response"] = response
        log_file = self._log_dir / "llm_calls.jsonl"
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            _log.debug("Failed to write LLM log entry", exc_info=True)

    def _supports_thinking(self, model: str | None = None) -> bool:
        m = model or self.model
        return m.startswith("glm-") or m.startswith("kimi-")

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

    @contextmanager
    def without_thinking(self):
        previous = self._thinking_enabled
        self._thinking_enabled = False
        try:
            yield self
        finally:
            self._thinking_enabled = previous

    def _payload(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float | None,
        stream: bool = False,
        response_format: dict[str, Any] | None = None,
        enable_thinking: bool | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        use_model = model or self.model
        payload: dict[str, Any] = {
            "model": use_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": self.max_tokens,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if enable_thinking is None:
            thinking_enabled = (
                False if response_format is not None else self._thinking_enabled
            )
        else:
            thinking_enabled = enable_thinking
        if self._supports_thinking(use_model) and thinking_enabled:
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

    def _iter_sse_events(
        self,
        resp: httpx.Response,
        should_cancel: Callable[[], bool] | None = None,
    ):
        """Yield reasoning/content events from an SSE stream response.

        If ``should_cancel`` is supplied, the stream is polled between
        lines and :class:`LLMCancelled` is raised when it returns True so
        workers can abort without waiting for the full ``read`` timeout.
        """
        for line in resp.iter_lines():
            if should_cancel is not None and should_cancel():
                raise LLMCancelled()
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

    def _raise_after_retries(self, label: str, exc: BaseException) -> None:
        raise RuntimeError(
            f"LLM {label} failed after {self.max_retries} retries: {exc}"
        ) from exc

    def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        should_cancel: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        timeout = self._stream_timeout()
        last_exc: BaseException | None = None
        for attempt in range(self.max_retries + 1):
            if should_cancel is not None and should_cancel():
                raise LLMCancelled()
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
                        enable_thinking=False,
                        model=self.fast_model,
                    ),
                    timeout=timeout,
                ) as resp:
                    resp.raise_for_status()
                    for event in self._iter_sse_events(resp, should_cancel):
                        if event.get("type") == "content":
                            collected.append(event.get("text", ""))
                content = "".join(collected)
                if not content:
                    raise ValueError("LLM returned empty content")
                parsed = json.loads(content)
                self._log_call(
                    method="chat_json",
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    response=parsed,
                )
                return parsed
            except LLMCancelled:
                raise
            except Exception as exc:
                last_exc = exc
                if not _is_retryable(exc) or attempt == self.max_retries:
                    self._raise_after_retries("request", exc)
                _log.warning(
                    "LLM chat_json attempt %d/%d failed (retryable): %s",
                    attempt + 1,
                    self.max_retries + 1,
                    exc,
                )
        assert last_exc is not None
        self._raise_after_retries("request", last_exc)
        raise AssertionError("unreachable")

    def chat_json_events(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        should_cancel: Callable[[], bool] | None = None,
    ):
        timeout = self._stream_timeout()
        last_exc: BaseException | None = None
        for attempt in range(self.max_retries + 1):
            if should_cancel is not None and should_cancel():
                raise LLMCancelled()
            try:
                collected: list[str] = []
                reasoning_preview: list[str] = []
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
                        enable_thinking=True,
                        model=self.model,
                    ),
                    timeout=timeout,
                ) as resp:
                    resp.raise_for_status()
                    for event in self._iter_sse_events(resp, should_cancel):
                        event_type = event.get("type")
                        text = event.get("text", "")
                        if event_type == "reasoning" and text:
                            reasoning_preview.append(text)
                            yield event
                        elif event_type == "content" and text:
                            collected.append(text)
                content = "".join(collected)
                if not content:
                    raise ValueError("LLM returned empty content")
                parsed = json.loads(content)
                self._log_call(
                    method="chat_json_events",
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    response={
                        "reasoning_preview": "".join(reasoning_preview)[:200],
                        "json": parsed,
                    },
                )
                yield {"type": "result", "value": parsed}
                return
            except LLMCancelled:
                raise
            except Exception as exc:
                last_exc = exc
                if not _is_retryable(exc) or attempt == self.max_retries:
                    self._raise_after_retries("request", exc)
                _log.warning(
                    "LLM chat_json_events attempt %d/%d failed (retryable): %s",
                    attempt + 1,
                    self.max_retries + 1,
                    exc,
                )
        assert last_exc is not None
        self._raise_after_retries("request", last_exc)
        raise AssertionError("unreachable")

    def chat_stream(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        should_cancel: Callable[[], bool] | None = None,
    ):
        """Stream LLM response as text chunks (generator)."""
        timeout = self._stream_timeout()
        chunks: list[str] = []
        try:
            for attempt in range(self.max_retries + 1):
                chunks = []
                if should_cancel is not None and should_cancel():
                    raise LLMCancelled()
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
                            enable_thinking=False,
                            model=self.fast_model,
                        ),
                        timeout=timeout,
                    ) as resp:
                        resp.raise_for_status()
                        for event in self._iter_sse_events(resp, should_cancel):
                            if event.get("type") == "content":
                                text = event.get("text", "")
                                if text:
                                    chunks.append(text)
                                    yield text
                    return
                except LLMCancelled:
                    raise
                except Exception as exc:
                    if not _is_retryable(exc) or attempt == self.max_retries:
                        self._raise_after_retries("streaming request", exc)
                    _log.warning(
                        "LLM chat_stream attempt %d/%d failed (retryable): %s",
                        attempt + 1,
                        self.max_retries + 1,
                        exc,
                    )
        finally:
            self._log_call(
                method="chat_stream",
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response="".join(chunks)[:500] if chunks else None,
            )

    def chat_text_stream(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        should_cancel: Callable[[], bool] | None = None,
    ):
        """Stream plain-language text for direct user display."""
        timeout = self._stream_timeout()
        events: list[dict] = []
        try:
            for attempt in range(self.max_retries + 1):
                events = []
                if should_cancel is not None and should_cancel():
                    raise LLMCancelled()
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
                        for event in self._iter_sse_events(resp, should_cancel):
                            events.append(event)
                            yield event
                    return
                except LLMCancelled:
                    raise
                except Exception as exc:
                    if not _is_retryable(exc) or attempt == self.max_retries:
                        self._raise_after_retries("text streaming request", exc)
                    _log.warning(
                        "LLM chat_text_stream attempt %d/%d failed (retryable): %s",
                        attempt + 1,
                        self.max_retries + 1,
                        exc,
                    )
        finally:
            self._log_call(
                method="chat_text_stream",
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response={
                    "event_count": len(events),
                    "preview": "".join(
                        e.get("text", "") for e in events if e.get("type") == "content"
                    )[:200],
                },
            )
