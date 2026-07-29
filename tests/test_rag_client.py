import io
import json
import urllib.error
import urllib.request
from email.message import Message
from typing import Any

import pytest

from hifi_agent.exceptions import LLMProviderError
from hifi_agent.rag.client import DeepSeekClient, _extract_content


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        if isinstance(self.payload, bytes):
            return self.payload
        return json.dumps(self.payload).encode()


def test_deepseek_client_requires_key_and_loads_non_secret_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(LLMProviderError, match="not set"):
        DeepSeekClient(api_key="")

    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret-key")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://provider.test/")
    monkeypatch.setenv("DEEPSEEK_MODEL", "test-model")
    client = DeepSeekClient.from_environment()

    assert client.base_url == "https://provider.test"
    assert client.model == "test-model"


def test_deepseek_success_parses_structured_output_and_safe_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}
    response = {
        "id": "response-1",
        "model": "provider-model",
        "choices": [{"message": {"content": '{"schema_version":"2.0","proposals":[]}'}}],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
            "ignored": 999,
        },
    }

    def fake_urlopen(request: urllib.request.Request, *, timeout: float) -> FakeResponse:
        observed["url"] = request.full_url
        observed["authorization"] = request.get_header("Authorization")
        assert isinstance(request.data, bytes)
        observed["payload"] = json.loads(request.data)
        observed["timeout"] = timeout
        return FakeResponse(response)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    client = DeepSeekClient(
        api_key="secret-key",
        base_url="https://provider.test/",
        model="test-model",
        timeout_seconds=12,
        max_tokens=123,
    )

    result = client.complete_json(system_prompt="system", user_prompt="user")

    assert result.output == {"schema_version": "2.0", "proposals": []}
    assert result.metadata == {
        "response_id": "response-1",
        "response_model": "provider-model",
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_tokens": 15,
    }
    assert observed["url"] == "https://provider.test/chat/completions"
    assert observed["authorization"] == "Bearer secret-key"
    assert observed["timeout"] == 12
    payload = observed["payload"]
    assert payload["temperature"] == 0
    assert payload["max_tokens"] == 123
    assert payload["response_format"] == {"type": "json_object"}


def test_http_error_redacts_key(monkeypatch: pytest.MonkeyPatch) -> None:
    error = urllib.error.HTTPError(
        "https://provider.test",
        429,
        "rate limited",
        Message(),
        io.BytesIO(b"request secret-key was rejected"),
    )

    def raise_http_error(*args: object, **kwargs: object) -> FakeResponse:
        del args, kwargs
        raise error

    monkeypatch.setattr(urllib.request, "urlopen", raise_http_error)

    with pytest.raises(LLMProviderError, match=r"HTTP 429.*<redacted>") as captured:
        DeepSeekClient(api_key="secret-key").complete_json(
            system_prompt="system",
            user_prompt="user",
        )

    assert "secret-key" not in str(captured.value)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (b"not-json", "request failed"),
        (
            {"choices": [{"message": {"content": "not-json"}}]},
            "content was not valid JSON",
        ),
        (
            {"choices": [{"message": {"content": "[1,2,3]"}}]},
            "must be a JSON object",
        ),
    ],
)
def test_invalid_provider_payloads_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    payload: object,
    message: str,
) -> None:
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *args, **kwargs: FakeResponse(payload),
    )

    with pytest.raises(LLMProviderError, match=message):
        DeepSeekClient(api_key="secret").complete_json(
            system_prompt="system",
            user_prompt="user",
        )


def test_network_error_is_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    error = urllib.error.URLError("timeout")

    def raise_network_error(*args: object, **kwargs: object) -> FakeResponse:
        del args, kwargs
        raise error

    monkeypatch.setattr(urllib.request, "urlopen", raise_network_error)

    with pytest.raises(LLMProviderError, match="request failed"):
        DeepSeekClient(api_key="secret").complete_json(
            system_prompt="system",
            user_prompt="user",
        )


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"choices": []},
        {"choices": [None]},
        {"choices": [{}]},
        {"choices": [{"message": None}]},
        {"choices": [{"message": {}}]},
    ],
)
def test_extract_content_rejects_malformed_response_shapes(payload: object) -> None:
    with pytest.raises(LLMProviderError):
        _extract_content(payload)
