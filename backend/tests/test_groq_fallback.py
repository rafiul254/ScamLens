"""Groq fallback tests. Every HTTP call is mocked; no API key or network is used."""
from __future__ import annotations

import json

import httpx
import pytest

from app.services.llm import (
    FallbackLLMClient,
    GeminiClient,
    GroqClient,
    LLMUnavailable,
    extract_json_object,
)


class _FailingGemini(GeminiClient):
    """Gemini that fails exactly like a free-tier quota error, without a request."""

    def __init__(self, message: str = "429 RESOURCE_EXHAUSTED") -> None:
        super().__init__("gemini-test-key", "gemini-3.8-flash")
        self._message = message

    def messages_create(self, **kwargs):
        raise LLMUnavailable(self._message)


def _groq(handler) -> GroqClient:
    return GroqClient(
        "groq-test-key",
        "llama-3.3-70b-versatile",
        client=httpx.Client(transport=httpx.MockTransport(handler), timeout=5),
    )


def _completion(content: str, finish_reason: str = "stop") -> dict:
    return {
        "choices": [{"message": {"content": content}, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }


def test_gemini_failure_falls_back_to_groq():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=_completion('{"verdict":"SCAM"}'))

    llm = FallbackLLMClient(_FailingGemini(), _groq(handler))
    response = llm.messages_create(
        system="Follow the rules.",
        messages=[{"role": "user", "content": "Check this."}],
        temperature=0.2,
    )

    assert response.text == '{"verdict":"SCAM"}'
    assert response.usage == {"input_tokens": 10, "output_tokens": 5}
    assert llm.last_provider == "groq"
    assert seen["auth"] == "Bearer groq-test-key"
    assert seen["body"]["model"] == "llama-3.3-70b-versatile"
    assert seen["body"]["temperature"] == 0.2
    assert seen["body"]["messages"] == [
        {"role": "system", "content": "Follow the rules."},
        {"role": "user", "content": "Check this."},
    ]


def test_groq_tool_call_round_trip_uses_openai_shape():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["tools"][0]["function"]["name"] == "classify_text"
        return httpx.Response(200, json={
            "choices": [{
                "message": {
                    "content": None,
                    "tool_calls": [{
                        "id": "call-1",
                        "type": "function",
                        "function": {
                            "name": "classify_text",
                            "arguments": '{"text": "claim prize"}',
                        },
                    }],
                },
                "finish_reason": "tool_calls",
            }],
        })

    client = _groq(handler)
    response = client.messages_create(
        system="Use tools.",
        messages=[{"role": "user", "content": "Check it."}],
        tools=[{
            "name": "classify_text",
            "description": "Classify a message.",
            "input_schema": {"type": "object", "properties": {"text": {"type": "string"}}},
        }],
    )

    assert response.tool_calls == [{
        "id": "call-1", "name": "classify_text", "input": {"text": "claim prize"},
    }]
    assert response.raw_blocks[0]["type"] == "tool_use"

    converted = client._convert_messages("Use tools.", [
        {"role": "user", "content": "Check it."},
        {"role": "assistant", "content": response.raw_blocks},
        {"role": "user", "content": [{
            "type": "tool_result",
            "tool_use_id": "call-1",
            "name": "classify_text",
            "content": '{"score": 0.9}',
        }]},
    ])
    assert converted[-1] == {
        "role": "tool", "tool_call_id": "call-1", "content": '{"score": 0.9}',
    }


def test_groq_retries_once_on_429():
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(429, headers={"retry-after": "0"}, json={"error": "rate"})
        return httpx.Response(200, json=_completion('{"verdict":"SAFE"}'))

    response = _groq(handler).messages_create(
        system="x", messages=[{"role": "user", "content": "y"}],
    )

    assert calls["count"] == 2
    assert response.text == '{"verdict":"SAFE"}'


def test_both_providers_failing_raises_for_the_local_agent():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "upstream"})

    llm = FallbackLLMClient(_FailingGemini(), _groq(handler))

    with pytest.raises(LLMUnavailable) as excinfo:
        llm.messages_create(system="x", messages=[{"role": "user", "content": "y"}])

    message = str(excinfo.value)
    assert "gemini" in message and "groq" in message


def test_missing_groq_key_is_not_called():
    fallback = GroqClient(None)
    llm = FallbackLLMClient(_FailingGemini(), fallback)
    assert not fallback.available

    with pytest.raises(LLMUnavailable):
        llm.messages_create(system="x", messages=[{"role": "user", "content": "y"}])


def test_json_mode_and_code_fence_parsing():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=_completion('```json\n{"verdict":"SCAM"}\n```'))

    data = _groq(handler).complete_json("Be strict.", "Return JSON.")

    assert data == {"verdict": "SCAM"}
    assert seen["body"]["response_format"] == {"type": "json_object"}
    assert extract_json_object('Here you go: {"a": 1}') == {"a": 1}
