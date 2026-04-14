from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx

from aptgent.domain.models import TargetMolecule


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
        self.max_tokens = self.config.get("max_tokens", 4096)
        self.timeout = self.config.get("timeout_seconds", 60)
        self.max_retries = self.config.get("max_retries", 2)

    def _load_config(self, path: Path) -> dict[str, Any]:
        import tomli

        with open(path, "rb") as f:
            data = tomli.load(f)
        return data.get("provider", {}).get("openai", {})

    def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "response_format": {"type": "json_object"},
        }

        for attempt in range(self.max_retries + 1):
            try:
                resp = httpx.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                return json.loads(content)
            except Exception as e:
                if attempt == self.max_retries:
                    raise RuntimeError(f"LLM request failed after {self.max_retries} retries: {e}")
        return {}
