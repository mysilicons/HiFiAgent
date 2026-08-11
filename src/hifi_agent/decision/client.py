"""Provider-neutral current structured LLM client interfaces."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from hifi_agent.exceptions import LLMProviderError


@dataclass(frozen=True)
class LLMClientResult:
    """Parsed provider JSON plus non-secret metadata."""

    output: dict[str, Any]
    metadata: dict[str, bool | int | float | str | None]


class StructuredLLMClient(Protocol):
    """The only provider interface available to all current decision modes."""

    provider: str
    model: str

    def complete_json(self, *, system_prompt: str, user_prompt: str) -> LLMClientResult:
        """Return one strict JSON object without executing any returned text."""


class RecordedLLMResponse(BaseModel):
    """One round-bound structured response in an offline replay transcript."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    round_index: int = Field(ge=1, le=3)
    output: dict[str, Any]
    metadata: dict[str, bool | int | float | str | None] = Field(default_factory=dict)


class RecordedLLMTranscript(BaseModel):
    """Audited offline transcript used to replay provider responses without a network."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_id: Literal["hifi-agent"] = "hifi-agent"
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    responses: tuple[RecordedLLMResponse, ...] = Field(min_length=1)


class RecordedLLMClient:
    """Replay a checksummed config input, selecting exactly one response per round."""

    def __init__(self, transcript_path: Path) -> None:
        self.transcript_path = transcript_path.resolve()
        try:
            self.transcript = RecordedLLMTranscript.model_validate_json(
                self.transcript_path.read_text()
            )
        except (OSError, ValidationError) as exc:
            raise LLMProviderError(f"Recorded LLM transcript is invalid: {exc}") from exc
        rounds = [item.round_index for item in self.transcript.responses]
        if len(rounds) != len(set(rounds)):
            raise LLMProviderError("Recorded LLM transcript contains duplicate round responses")
        self.provider = f"recorded:{self.transcript.provider}"
        self.model = self.transcript.model

    def complete_json(self, *, system_prompt: str, user_prompt: str) -> LLMClientResult:
        """Return only the response explicitly bound to the prompt's round index."""
        if not system_prompt.strip():
            raise LLMProviderError("Recorded LLM replay requires the governed system prompt")
        try:
            prompt = json.loads(user_prompt)
            context = prompt["context"]
            round_index = context["round_index"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise LLMProviderError("Recorded LLM replay prompt has no round binding") from exc
        if not isinstance(round_index, int) or isinstance(round_index, bool):
            raise LLMProviderError("Recorded LLM replay round binding is invalid")
        response = next(
            (item for item in self.transcript.responses if item.round_index == round_index),
            None,
        )
        if response is None:
            raise LLMProviderError(
                f"Recorded LLM transcript has no response for round {round_index}"
            )
        metadata = dict(response.metadata)
        metadata["replay_round_index"] = round_index
        return LLMClientResult(output=dict(response.output), metadata=metadata)


class DeepSeekClient:
    """Minimal OpenAI-compatible client used only behind the safety arbiter."""

    provider = "deepseek"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-chat",
        timeout_seconds: float = 90.0,
    ) -> None:
        if not api_key:
            raise LLMProviderError("DEEPSEEK_API_KEY is not set")
        self._api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

    @classmethod
    def from_environment(cls) -> DeepSeekClient:
        """Create a provider from environment variables without persisting secrets."""
        return cls(
            api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
            base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            model=os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
        )

    def complete_json(self, *, system_prompt: str, user_prompt: str) -> LLMClientResult:
        """Call the provider with deterministic structured-output settings."""
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0,
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
            detail = exc.read().decode(errors="replace")[:500].replace(self._api_key, "<redacted>")
            raise LLMProviderError(f"DeepSeek returned HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise LLMProviderError(f"DeepSeek request failed: {exc}") from exc
        content = _extract_content(response_data)
        try:
            output = json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMProviderError("DeepSeek content was not valid JSON") from exc
        if not isinstance(output, dict):
            raise LLMProviderError("DeepSeek structured output must be a JSON object")
        usage = response_data.get("usage") if isinstance(response_data, dict) else None
        metadata: dict[str, bool | int | float | str | None] = {}
        if isinstance(usage, dict):
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                value = usage.get(key)
                if isinstance(value, int) and not isinstance(value, bool):
                    metadata[key] = value
        return LLMClientResult(output=output, metadata=metadata)


def _extract_content(response_data: object) -> str:
    if not isinstance(response_data, dict):
        raise LLMProviderError("Provider response is not an object")
    choices = response_data.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise LLMProviderError("Provider response has no choices")
    message = choices[0].get("message")
    if not isinstance(message, dict) or not isinstance(message.get("content"), str):
        raise LLMProviderError("Provider response has no message content")
    return str(message["content"])
