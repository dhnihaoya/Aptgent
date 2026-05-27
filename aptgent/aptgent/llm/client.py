from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, TypeVar

import httpx

_log = logging.getLogger(__name__)

T = TypeVar("T")


class LLMCancelled(Exception):
    """Raised when a caller's ``should_cancel`` hook signals cancellation."""


class LLMCallLogger:
    """Handles LLM call logging to JSONL files."""

    def __init__(self, *, redact: bool = True) -> None:
        self._log_dir: Path | None = None
        self._redact = redact

    def set_log_dir(self, log_dir: str | Path) -> None:
        self._log_dir = Path(log_dir)
        self._log_dir.mkdir(parents=True, exist_ok=True)

    @property
    def log_dir(self) -> Path | None:
        return self._log_dir

    @staticmethod
    def redact_text(text: str) -> str:
        return "sha256:" + hashlib.sha256(text.encode()).hexdigest()[:16]

    def log_call(
        self,
        *,
        method: str,
        system_prompt: str,
        user_prompt: str,
        response: Any = None,
        model: str = "",
    ) -> None:
        if self._log_dir is None:
            return
        entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "method": method,
            "provider": "openai",
            "model": model,
            "system_prompt": system_prompt[:200] if len(system_prompt) > 200 else system_prompt,
            "user_message": (
                self.redact_text(user_prompt) if self._redact else user_prompt
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


_BACKOFF_BASE = 1.0
_BACKOFF_MAX = 60.0


def _backoff_delay(attempt: int, exc: BaseException) -> float:
    """Exponential backoff with optional Retry-After from 429 responses."""
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
        retry_after = exc.response.headers.get("retry-after")
        if retry_after:
            try:
                return min(float(retry_after), _BACKOFF_MAX)
            except ValueError:
                pass
    delay = min(_BACKOFF_BASE * (2 ** attempt), _BACKOFF_MAX)
    return delay


class LLMClient:
    _REPETITION_WINDOW = 200
    _REPETITION_MIN_PATTERN = 40
    _REPETITION_THRESHOLD = 3

    def __init__(
        self,
        config_path: str | Path | None = None,
        *,
        config: dict[str, Any] | None = None,
    ) -> None:
        if config is not None:
            self.config = config
        else:
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
        self.max_reasoning_chars = self.config.get(
            "max_reasoning_tokens",
            self.config.get("max_reasoning_chars", 16384),
        )
        self.timeout = self.config.get("timeout_seconds", 60)
        self.max_retries = max(0, self.config.get("max_retries", 2))
        self._thinking_enabled = True
        self._logger = LLMCallLogger(
            redact=os.environ.get("APTGENT_LLM_REDACT", "1") != "0",
        )

    @classmethod
    def from_config(
        cls,
        llm_section: dict[str, Any],
        *,
        log_dir: Path | None = None,
    ) -> LLMClient:
        """Create from a pre-loaded config section (already env-expanded)."""
        instance = cls(config=llm_section)
        if log_dir is not None:
            instance.set_log_dir(log_dir)
        return instance

    # -- backward compat --------------------------------------------------

    @property
    def max_reasoning_tokens(self) -> int:
        return self.max_reasoning_chars

    @max_reasoning_tokens.setter
    def max_reasoning_tokens(self, value: int) -> None:
        self.max_reasoning_chars = value

    @property
    def _log_dir(self) -> Path | None:
        return self._logger.log_dir

    def set_log_dir(self, log_dir: str | Path) -> None:
        self._logger.set_log_dir(log_dir)

    @staticmethod
    def _redact_text(text: str) -> str:
        return LLMCallLogger.redact_text(text)

    def _log_call(self, **kwargs: Any) -> None:
        kwargs.setdefault("model", self.model)
        self._logger.log_call(**kwargs)

    # -- config / payload helpers -----------------------------------------

    def _supports_thinking(self, model: str | None = None) -> bool:
        m = model or self.model
        if "flash" in m:
            return False
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

    @staticmethod
    def _detect_repetition(
        buf: str,
        window: int = _REPETITION_WINDOW,
        min_pat: int = _REPETITION_MIN_PATTERN,
        threshold: int = _REPETITION_THRESHOLD,
    ) -> bool:
        """Return True if the tail of *buf* contains a repeating pattern.

        Uses prefix-hash pre-computation so each substring comparison is O(1)
        instead of O(pat_len), bringing overall complexity from O(n^2) to
        O(n log n).
        """
        tail = buf[-window:] if len(buf) > window else buf
        if len(tail) < min_pat * threshold:
            return False

        _BASE = 257
        _MOD = (1 << 61) - 1

        n = len(tail)
        ph = [0] * (n + 1)
        bp = [1] * (n + 1)
        for i, ch in enumerate(tail):
            ph[i + 1] = (ph[i] * _BASE + ord(ch)) % _MOD
            bp[i + 1] = (bp[i] * _BASE) % _MOD

        def _hash(lo: int, hi: int) -> int:
            return (ph[hi] - ph[lo] * bp[hi - lo]) % _MOD

        max_pat = n // threshold
        for pat_len in range(min_pat, max_pat + 1):
            pat_hash = _hash(n - pat_len, n)
            count = 0
            pos = n - pat_len
            while pos >= 0:
                if _hash(pos, pos + pat_len) == pat_hash:
                    count += 1
                    if count >= threshold:
                        return True
                    pos -= pat_len
                else:
                    break
        return False

    # -- core streaming + retry primitives --------------------------------

    def _iter_sse_events(
        self,
        resp: httpx.Response,
        should_cancel: Callable[[], bool] | None = None,
    ):
        """Yield reasoning/content events from an SSE stream response."""
        reasoning_buf: list[str] = []
        reasoning_chars = 0
        reasoning_suppressed = False
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
                if reasoning and not reasoning_suppressed:
                    reasoning_chars += len(reasoning)
                    reasoning_buf.append(reasoning)
                    if reasoning_chars > self.max_reasoning_chars:
                        reasoning_suppressed = True
                        _log.info(
                            "Reasoning suppressed: exceeded %d char limit",
                            self.max_reasoning_chars,
                        )
                        yield {
                            "type": "reasoning",
                            "text": "\n\n[reasoning truncated — token limit]",
                        }
                    elif len(reasoning_buf) % 8 == 0 and self._detect_repetition(
                        "".join(reasoning_buf)
                    ):
                        reasoning_suppressed = True
                        _log.info("Reasoning suppressed: repetitive loop detected")
                        yield {
                            "type": "reasoning",
                            "text": "\n\n[reasoning truncated — repetitive loop detected]",
                        }
                    else:
                        yield {"type": "reasoning", "text": reasoning}
                content = self._extract_content(delta.get("content", ""))
                if content:
                    yield {"type": "content", "text": content}
            except Exception as exc:
                _log.debug("SSE chunk parse failed: %s", exc)

    def _stream_chat(
        self,
        *,
        system: str,
        user: str,
        temperature: float | None = None,
        response_format: dict[str, Any] | None = None,
        enable_thinking: bool | None = None,
        model: str | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> Iterator[dict]:
        """Open one streaming request and yield parsed SSE events."""
        with httpx.stream(
            "POST",
            f"{self.base_url}/chat/completions",
            headers=self._headers(),
            json=self._payload(
                system,
                user,
                temperature=temperature,
                stream=True,
                response_format=response_format,
                enable_thinking=enable_thinking,
                model=model,
            ),
            timeout=self._stream_timeout(),
        ) as resp:
            resp.raise_for_status()
            yield from self._iter_sse_events(resp, should_cancel)

    def _with_retry(
        self,
        label: str,
        fn: Callable[[], T],
        *,
        should_cancel: Callable[[], bool] | None = None,
    ) -> T:
        """Run *fn* with retry logic for transient failures (non-generator)."""
        last_exc: BaseException | None = None
        for attempt in range(self.max_retries + 1):
            if should_cancel is not None and should_cancel():
                raise LLMCancelled()
            try:
                return fn()
            except LLMCancelled:
                raise
            except Exception as exc:
                last_exc = exc
                if not _is_retryable(exc) or attempt == self.max_retries:
                    self._raise_after_retries(label, exc)
                delay = _backoff_delay(attempt, exc)
                _log.warning(
                    "LLM %s attempt %d/%d failed (retryable, %.1fs backoff): %s",
                    label, attempt + 1, self.max_retries + 1, delay, exc,
                )
                time.sleep(delay)
        assert last_exc is not None
        self._raise_after_retries(label, last_exc)

    def _retry_gen(
        self,
        label: str,
        gen_factory: Callable[[], Iterator[dict]],
        *,
        should_cancel: Callable[[], bool] | None = None,
    ) -> Iterator[dict]:
        """Wrap a generator factory with retry logic for transient failures.

        Retries are only attempted when **no events have been yielded yet**.
        Once events have been delivered to the caller, retrying would produce
        duplicates (e.g. duplicate reasoning in the UI), so the exception is
        raised immediately instead.
        """
        last_exc: BaseException | None = None
        yielded_any = False
        for attempt in range(self.max_retries + 1):
            if should_cancel is not None and should_cancel():
                raise LLMCancelled()
            try:
                for event in gen_factory():
                    yielded_any = True
                    yield event
                return
            except LLMCancelled:
                raise
            except Exception as exc:
                last_exc = exc
                if yielded_any or not _is_retryable(exc) or attempt == self.max_retries:
                    self._raise_after_retries(label, exc)
                delay = _backoff_delay(attempt, exc)
                _log.warning(
                    "LLM %s attempt %d/%d failed (retryable, %.1fs backoff): %s",
                    label, attempt + 1, self.max_retries + 1, delay, exc,
                )
                time.sleep(delay)
        assert last_exc is not None
        self._raise_after_retries(label, last_exc)

    def _raise_after_retries(self, label: str, exc: BaseException) -> None:
        raise RuntimeError(
            f"LLM {label} failed after {self.max_retries} retries: {exc}"
        ) from exc

    # -- public API -------------------------------------------------------

    def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        should_cancel: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        def _attempt() -> dict[str, Any]:
            collected: list[str] = []
            for event in self._stream_chat(
                system=system_prompt,
                user=user_prompt,
                temperature=self.json_temperature,
                response_format={"type": "json_object"},
                enable_thinking=False,
                model=self.fast_model,
                should_cancel=should_cancel,
            ):
                if event.get("type") == "content":
                    collected.append(event.get("text", ""))
            content = "".join(collected)
            if not content:
                raise ValueError("LLM returned empty content")
            return json.loads(content)

        result = self._with_retry("request", _attempt, should_cancel=should_cancel)
        self._log_call(
            method="chat_json",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response=result,
        )
        return result

    def chat_json_events(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        should_cancel: Callable[[], bool] | None = None,
        enable_thinking: bool = True,
    ):
        use_model = self.model if enable_thinking else self.fast_model

        def _attempt():
            collected: list[str] = []
            reasoning_preview: list[str] = []
            for event in self._stream_chat(
                system=system_prompt,
                user=user_prompt,
                temperature=self.json_temperature,
                response_format={"type": "json_object"},
                enable_thinking=enable_thinking,
                model=use_model,
                should_cancel=should_cancel,
            ):
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

        yield from self._retry_gen("request", _attempt, should_cancel=should_cancel)

    def chat_json_stream(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        should_cancel: Callable[[], bool] | None = None,
    ):
        """Stream LLM JSON response as text chunks (generator)."""
        chunks: list[str] = []

        def _attempt():
            nonlocal chunks
            chunks = []
            for event in self._stream_chat(
                system=system_prompt,
                user=user_prompt,
                temperature=self.json_temperature,
                response_format={"type": "json_object"},
                enable_thinking=False,
                model=self.fast_model,
                should_cancel=should_cancel,
            ):
                if event.get("type") == "content":
                    text = event.get("text", "")
                    if text:
                        chunks.append(text)
                        yield text

        try:
            yield from self._retry_gen(
                "streaming request", _attempt, should_cancel=should_cancel,
            )
        finally:
            self._log_call(
                method="chat_json_stream",
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
        events: list[dict] = []

        def _attempt():
            nonlocal events
            events = []
            for event in self._stream_chat(
                system=system_prompt,
                user=user_prompt,
                temperature=self.temperature,
                should_cancel=should_cancel,
            ):
                events.append(event)
                yield event

        try:
            yield from self._retry_gen(
                "text streaming request", _attempt, should_cancel=should_cancel,
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
