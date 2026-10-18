"""Unit tests for the Gemini SDK adapter; no live API key or request is used."""
from __future__ import annotations

import base64
from types import SimpleNamespace

from google.genai import types

from app.services.llm import GeminiClient, LLMUnavailable


class _FakeModels:
    def __init__(self, response):
        self.response = response
        self.last_call = None

    def generate_content(self, **kwargs):
        self.last_call = kwargs
        return self.response


def _client_with_response(response):
    client = GeminiClient("unit-test-key", "gemini-3.8-flash")
    models = _FakeModels(response)
    client._client = SimpleNamespace(models=models)
    client._types = types
    return client, models


def test_tool_call_and_result_round_trip_preserves_name_id_and_signature():
    client = GeminiClient("unit-test-key", "gemini-3.8-flash")
    client._types = types
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "Check this message."}]},
        {"role": "assistant", "content": [{
            "type": "tool_use",
            "id": "call-123",
            "name": "detect_pii",
            "input": {"text": "Your code is [OTP_1]"},
            "thought_signature": b"opaque-signature",
        }]},
        {"role": "user", "content": [{
            "type": "tool_result",
            "tool_use_id": "call-123",
            "name": "detect_pii",
            "content": '{"count": 1, "redacted_text": "[OTP_1]"}',
            "is_error": False,
        }]},
    ]

    contents = client._convert_messages(messages)

    assert [item.role for item in contents] == ["user", "model", "user"]
    function_call = contents[1].parts[0].function_call
    assert function_call.name == "detect_pii"
    assert function_call.id == "call-123"
    assert function_call.args == {"text": "Your code is [OTP_1]"}
    assert contents[1].parts[0].thought_signature == b"opaque-signature"

    function_response = contents[2].parts[0].function_response
    assert function_response.name == "detect_pii"
    assert function_response.id == "call-123"
    assert function_response.response == {
        "output": {"count": 1, "redacted_text": "[OTP_1]"}
    }


def test_user_screenshot_is_encoded_as_inline_image_part():
    client = GeminiClient("unit-test-key", "gemini-3.8-flash")
    client._types = types
    image = base64.b64encode(b"fake-png-bytes").decode("ascii")

    contents = client._convert_messages([{
        "role": "user",
        "content": [
            {"type": "text", "text": "Transcribe this."},
            {"type": "image", "source": {
                "type": "base64", "media_type": "image/png", "data": image,
            }},
        ],
    }])

    assert contents[0].role == "user"
    assert contents[0].parts[0].text == "Transcribe this."
    assert contents[0].parts[1].inline_data.mime_type == "image/png"
    assert contents[0].parts[1].inline_data.data == b"fake-png-bytes"


def test_messages_create_maps_function_declarations_and_usage():
    candidate = SimpleNamespace(
        content=types.Content(role="model", parts=[types.Part(text='{"verdict":"SAFE"}')]),
        finish_reason="STOP",
    )
    response = SimpleNamespace(
        candidates=[candidate],
        usage_metadata=SimpleNamespace(prompt_token_count=17, response_token_count=6),
    )
    client, models = _client_with_response(response)
    tools = [{
        "name": "classify_text",
        "description": "Classify a message.",
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    }]

    result = client.messages_create(
        system="Follow the rules.",
        messages=[{"role": "user", "content": "Hello"}],
        tools=tools,
        max_tokens=111,
        temperature=0.1,
    )

    assert result.text == '{"verdict":"SAFE"}'
    assert result.stop_reason == "STOP"
    assert result.usage == {"input_tokens": 17, "output_tokens": 6}
    config = models.last_call["config"]
    assert config.system_instruction == "Follow the rules."
    assert config.max_output_tokens == 111
    assert config.tools[0].function_declarations[0].name == "classify_text"
    assert config.tools[0].function_declarations[0].parameters.required == ["text"]


def test_messages_create_returns_gemini_function_calls():
    call_part = types.Part(function_call=types.FunctionCall(
        id="call-456", name="match_pattern", args={"text": "claim prize"}
    ))
    candidate = SimpleNamespace(
        content=types.Content(role="model", parts=[call_part]),
        finish_reason="STOP",
    )
    client, _ = _client_with_response(SimpleNamespace(candidates=[candidate], usage_metadata=None))

    result = client.messages_create(
        system="Use tools.",
        messages=[{"role": "user", "content": "Check it."}],
        tools=[{"name": "match_pattern", "input_schema": {"type": "object"}}],
    )

    assert result.text == ""
    assert result.tool_calls == [{
        "id": "call-456", "name": "match_pattern", "input": {"text": "claim prize"}
    }]
    assert result.raw_blocks[0]["type"] == "tool_use"


def test_vision_extract_sends_inline_image_to_gemini():
    client, models = _client_with_response(SimpleNamespace(text="OTP message", candidates=[]))

    text = client.vision_extract(b"fake-image", "image/png", "Transcribe it.")

    assert text == "OTP message"
    contents = models.last_call["contents"]
    assert contents[0].parts[0].inline_data.data == b"fake-image"
    assert contents[0].parts[0].inline_data.mime_type == "image/png"
    assert contents[0].parts[1].text == "Transcribe it."
    assert "OCR/vision tool" in models.last_call["config"].system_instruction


def test_missing_api_key_is_reported_without_attempting_a_request():
    client = GeminiClient(None, "gemini-3.8-flash")
    assert not client.available

    try:
        client.messages_create(system="x", messages=[{"role": "user", "content": "y"}])
    except LLMUnavailable as exc:
        assert "GEMINI_API_KEY" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("missing key should disable Gemini")
