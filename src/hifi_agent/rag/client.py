"""Minimal OpenAI-compatible DeepSeek client for structured explanations."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

from hifi_agent.exceptions import LLMProviderError

DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-pro"


@dataclass(frozen=True)
class LLMClientResult:
    """Parsed JSON object and non-secret API response metadata."""

    output: dict[str, Any]
    metadata: dict[str, bool | int | float | str | None]


class StructuredLLMClient(Protocol):
    """Provider-neutral interface required by the constrained explainer."""

    model: str

    def complete_json(self, *, system_prompt: str, user_prompt: str) -> LLMClientResult:
        """Return one parsed structured output and safe metadata."""


class DeepSeekClient:
    """Call DeepSeek through its OpenAI-compatible chat completions endpoint."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = DEFAULT_DEEPSEEK_BASE_URL,
        model: str = DEFAULT_DEEPSEEK_MODEL,
        timeout_seconds: float = 90.0,
        max_tokens: int = 3000,
    ) -> None:
        if not api_key:
            raise LLMProviderError("DEEPSEEK_API_KEY is not set")
        self._api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_tokens = max_tokens

    @classmethod
    def from_environment(cls) -> DeepSeekClient:
        """Create a client from non-repository environment variables."""
        return cls(
            api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
            base_url=os.environ.get("DEEPSEEK_BASE_URL", DEFAULT_DEEPSEEK_BASE_URL),
            model=os.environ.get("DEEPSEEK_MODEL", DEFAULT_DEEPSEEK_MODEL),
        )

    def complete_json(self, *, system_prompt: str, user_prompt: str) -> LLMClientResult:
        """Request one deterministic JSON object without exposing the API key."""
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0,
            "max_tokens": self.max_tokens,
            "response_format": {"type": "json_object"},
            "stream": False,
        }
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                response_data = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:500]
            raise LLMProviderError(
                f"DeepSeek API returned HTTP {exc.code}: "
                f"{_redact_provider_error(detail, self._api_key)}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise LLMProviderError(f"DeepSeek API request failed: {exc}") from exc
        content = _extract_content(response_data)
        try:
            output = json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMProviderError("DeepSeek response content was not valid JSON") from exc
        if not isinstance(output, dict):
            raise LLMProviderError("DeepSeek structured response must be a JSON object")
        usage = response_data.get("usage") if isinstance(response_data, dict) else None
        metadata: dict[str, bool | int | float | str | None] = {
            "response_id": response_data.get("id") if isinstance(response_data, dict) else None,
            "response_model": (
                response_data.get("model") if isinstance(response_data, dict) else None
            ),
        }
        if isinstance(usage, dict):
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                value = usage.get(key)
                if isinstance(value, int) and not isinstance(value, bool):
                    metadata[key] = value
        return LLMClientResult(output=output, metadata=metadata)


def _extract_content(response_data: object) -> str:
    if not isinstance(response_data, dict):
        raise LLMProviderError("DeepSeek response was not a JSON object")
    choices = response_data.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise LLMProviderError("DeepSeek response did not contain choices")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise LLMProviderError("DeepSeek response did not contain message content")
    content = message.get("content")
    if not isinstance(content, str):
        raise LLMProviderError("DeepSeek response did not contain message content")
    return content


def _redact_provider_error(detail: str, key: str) -> str:
    return detail.replace(key, "<redacted>") if key else detail
