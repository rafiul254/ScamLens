"""LLM provider clients: Google Gemini (primary) and Groq (fallback).

Used for:
* the agent loop (function/tool calling, max 6 steps)
* vision OCR on screenshots (Gemini only)
* in-language lesson / report / family-alert generation

Provider order is Gemini -> Groq -> deterministic local agent. Every provider
failure is raised as ``LLMUnavailable`` so the agent can fall back cleanly.
The API keys are server-side only and are never logged.
"""
from __future__ import annotations

import base64
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..config import Settings

log = logging.getLogger("scamlens.llm")

GROQ_DEFAULT_MODEL = "openai/gpt-oss-120b"
GROQ_DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"


def _redact_secret(text: str, secret: str | None) -> str:
    """Keep a provider error message but never echo the API key."""
    if secret and len(secret) >= 6:
        return text.replace(secret, "***")
    return text


class LLMUnavailable(RuntimeError):
    """Raised when Gemini cannot be used (no key, network error, or bad model id)."""


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[dict[str, Any]]
    stop_reason: str | None
    usage: dict[str, Any]
    raw_blocks: list[dict[str, Any]]


class GeminiClient:
    """Small compatibility wrapper around Google's ``google-genai`` SDK.

    The rest of ScamLens uses a provider-neutral message shape. This adapter
    translates it to Gemini's Content/Part schema and translates function calls
    back, keeping the agent loop and its local tool implementations unchanged.
    """

    def __init__(self, api_key: str | None, model: str, max_tokens: int = 2400,
                 timeout: float = 45.0, cooldown_seconds: float = 60.0,
                 thinking_budget: int = 0) -> None:
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.cooldown_seconds = cooldown_seconds
        # -1 means "omit thinkingConfig and let the model decide".
        self.thinking_budget = thinking_budget
        self._client = None
        self._types = None
        self.last_error: str | None = None
        # Circuit breaker: after a 429 RESOURCE_EXHAUSTED we stop calling the API
        # until the cooldown expires, so user requests fall back to the local
        # agent instantly instead of paying a doomed round-trip every time.
        self._cooldown_until: float = 0.0

    @property
    def available(self) -> bool:
        return bool(self.api_key) and time.monotonic() >= self._cooldown_until

    @property
    def provider(self) -> str:
        return "gemini"

    @property
    def cooldown_remaining(self) -> float:
        """Seconds left in the quota cooldown (0 when the API is usable)."""
        return max(0.0, self._cooldown_until - time.monotonic())

    def _trip_cooldown(self, exc: Exception) -> None:
        text = f"{type(exc).__name__}: {exc}"
        if "429" in text or "RESOURCE_EXHAUSTED" in text:
            self._cooldown_until = time.monotonic() + self.cooldown_seconds
            log.warning(
                "Gemini quota exhausted — pausing API calls for %.0fs (local agent takes over)",
                self.cooldown_seconds,
            )

    def _get_client(self):
        if self._client is None:
            if not self.api_key:
                raise LLMUnavailable("GEMINI_API_KEY is not set")
            try:
                from google import genai
                from google.genai import types

                self._types = types
                self._client = genai.Client(
                    api_key=self.api_key,
                    http_options=types.HttpOptions(timeout=int(self.timeout * 1000)),
                )
            except Exception as exc:  # pragma: no cover - depends on SDK installation
                raise LLMUnavailable(f"could not initialise Gemini client: {exc}") from exc
        return self._client

    @staticmethod
    def _system_text(system: str | list[dict[str, Any]]) -> str:
        if isinstance(system, str):
            return system
        return "\n".join(
            str(block.get("text", ""))
            for block in system
            if isinstance(block, dict) and block.get("type") == "text"
        ).strip()

    def _convert_messages(self, messages: list[dict[str, Any]]) -> list[Any]:
        """Translate the agent's messages into Gemini Content objects.

        In particular, Gemini function responses must contain the original
        function name and call id. Both are preserved across agent turns.
        """
        types = self._types
        if types is None:
            # This also makes conversion helpers convenient to unit test.
            try:
                from google.genai import types as genai_types
                types = genai_types
                self._types = types
            except Exception as exc:  # pragma: no cover
                raise LLMUnavailable(f"google-genai is not installed: {exc}") from exc

        call_names: dict[str, str] = {}
        for message in messages:
            if message.get("role") != "assistant":
                continue
            blocks = message.get("content", [])
            if isinstance(blocks, list):
                for block in blocks:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        if block.get("id") and block.get("name"):
                            call_names[str(block["id"])] = str(block["name"])

        contents: list[Any] = []
        for message in messages:
            role = "model" if message.get("role") == "assistant" else "user"
            raw = message.get("content", "")
            blocks = raw if isinstance(raw, list) else [{"type": "text", "text": str(raw)}]
            parts: list[Any] = []

            for block in blocks:
                if not isinstance(block, dict):
                    parts.append(types.Part(text=str(block)))
                    continue
                block_type = block.get("type")

                if block_type == "text":
                    text = str(block.get("text", ""))
                    if text:
                        parts.append(types.Part(text=text))
                elif block_type == "image":
                    source = block.get("source") or {}
                    if source.get("type") == "base64" and source.get("data"):
                        try:
                            image_bytes = base64.b64decode(source["data"], validate=True)
                            parts.append(types.Part.from_bytes(
                                data=image_bytes,
                                mime_type=str(source.get("media_type") or "image/png"),
                            ))
                        except Exception as exc:
                            raise LLMUnavailable(f"could not prepare screenshot for Gemini: {exc}") from exc
                elif block_type == "tool_use":
                    call_id = str(block.get("id") or f"call_{uuid.uuid4().hex}")
                    call = types.FunctionCall(
                        id=call_id,
                        name=str(block.get("name", "")),
                        args=block.get("input") or {},
                    )
                    kwargs: dict[str, Any] = {"function_call": call}
                    signature = block.get("thought_signature")
                    if signature is not None:
                        kwargs["thought_signature"] = signature
                    parts.append(types.Part(**kwargs))
                elif block_type == "tool_result":
                    call_id = str(block.get("tool_use_id") or "")
                    name = str(block.get("name") or call_names.get(call_id) or "unknown_tool")
                    raw_result = block.get("content", "")
                    try:
                        result = json.loads(raw_result) if isinstance(raw_result, str) else raw_result
                    except (json.JSONDecodeError, TypeError):
                        result = {"output": str(raw_result)}
                    if not isinstance(result, dict):
                        result = {"output": result}
                    response = {"error": result} if block.get("is_error") else {"output": result}
                    parts.append(types.Part(
                        function_response=types.FunctionResponse(
                            id=call_id or None,
                            name=name,
                            response=response,
                        )
                    ))

            if parts:
                contents.append(types.Content(role=role, parts=parts))

        return contents

    @staticmethod
    def _function_declarations(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        declarations: list[dict[str, Any]] = []
        for tool in tools or []:
            declarations.append({
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("input_schema") or {"type": "object", "properties": {}},
            })
        return declarations

    def _request_config(self, **kwargs: Any) -> Any:
        """Build the GenerateContentConfig shared by the text and vision paths.

        ``thinkingConfig`` is attached only when the configured budget is >= 0;
        a budget of -1 omits it entirely so the model keeps its default
        thinking behaviour. The installed google-genai SDK (2.x) takes a
        ``types.ThinkingConfig`` object on ``thinking_config``, not a raw dict.
        """
        types = self._types
        if types is None:  # populated by _get_client; defensive for injected test clients
            from google.genai import types as genai_types
            types = genai_types
            self._types = types
        if self.thinking_budget is not None and self.thinking_budget >= 0:
            kwargs["thinking_config"] = types.ThinkingConfig(
                thinking_budget=int(self.thinking_budget)
            )
        return types.GenerateContentConfig(**kwargs)

    # ------------------------------------------------------------------ calls
    def messages_create(self, *, system: str | list[dict[str, Any]], messages: list[dict[str, Any]],
                        tools: list[dict[str, Any]] | None = None, max_tokens: int | None = None,
                        temperature: float = 0.2, json_mode: bool = False) -> LLMResponse:
        client = self._get_client()
        types = self._types
        if types is None:  # populated by _get_client; defensive for injected test clients
            from google.genai import types
            self._types = types

        declarations = self._function_declarations(tools)
        config_kwargs: dict[str, Any] = {
            "system_instruction": self._system_text(system),
            "max_output_tokens": max_tokens or self.max_tokens,
            "temperature": temperature,
        }
        if declarations:
            config_kwargs["tools"] = [types.Tool(function_declarations=declarations)]
        # ``json_mode`` is accepted for interface parity with GroqClient; Gemini
        # already follows the JSON instruction in the prompt.

        try:
            response = client.models.generate_content(
                model=self.model,
                contents=self._convert_messages(messages),
                config=self._request_config(**config_kwargs),
            )
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"[:400]
            self._trip_cooldown(exc)
            raise LLMUnavailable(self.last_error) from exc

        blocks: list[dict[str, Any]] = []
        tool_calls: list[dict[str, Any]] = []
        texts: list[str] = []
        candidates = getattr(response, "candidates", None) or []
        if candidates:
            candidate = candidates[0]
            content = getattr(candidate, "content", None)
            for part in getattr(content, "parts", []) or []:
                text = getattr(part, "text", None)
                if text:
                    texts.append(str(text))
                    blocks.append({"type": "text", "text": str(text)})
                function_call = getattr(part, "function_call", None)
                if function_call is not None and getattr(function_call, "name", None):
                    call_id = getattr(function_call, "id", None) or f"call_{uuid.uuid4().hex}"
                    args = getattr(function_call, "args", None) or {}
                    call = {
                        "id": str(call_id),
                        "name": str(function_call.name),
                        "input": dict(args),
                    }
                    tool_calls.append(call)
                    raw_block: dict[str, Any] = {"type": "tool_use", **call}
                    signature = getattr(part, "thought_signature", None)
                    if signature is not None:
                        raw_block["thought_signature"] = signature
                    blocks.append(raw_block)

        if not blocks:
            # Some SDK/model responses may not expose candidate parts, but still
            # provide their aggregate text property.
            text = getattr(response, "text", None)
            if text:
                texts.append(str(text))
                blocks.append({"type": "text", "text": str(text)})

        candidate = candidates[0] if candidates else None
        finish_reason = getattr(candidate, "finish_reason", None) if candidate else None
        stop_reason = getattr(finish_reason, "name", None) or (
            str(finish_reason) if finish_reason is not None else None
        )
        usage_meta = getattr(response, "usage_metadata", None)
        usage: dict[str, Any] = {}
        if usage_meta is not None:
            usage = {
                "input_tokens": getattr(usage_meta, "prompt_token_count", None),
                "output_tokens": getattr(usage_meta, "response_token_count", None),
            }

        return LLMResponse(
            text="\n".join(text for text in texts if text).strip(),
            tool_calls=tool_calls,
            stop_reason=stop_reason,
            usage=usage,
            raw_blocks=blocks,
        )

    def vision_extract(self, image_bytes: bytes, media_type: str, instruction: str,
                       max_tokens: int = 1200) -> str:
        """Transcribe a screenshot using Gemini's image understanding."""
        client = self._get_client()
        types = self._types
        contents = [types.Content(
            role="user",
            parts=[
                types.Part.from_bytes(data=image_bytes, mime_type=media_type or "image/png"),
                types.Part(text=instruction),
            ],
        )]
        try:
            response = client.models.generate_content(
                model=self.model,
                contents=contents,
                config=self._request_config(
                    system_instruction=(
                        "You are the OCR/vision tool of ScamLens, an anti-scam assistant. "
                        "Transcribe the text visible in the screenshot exactly, preserving numbers and links. "
                        "If it is a chat screenshot, keep the sender labels. Do not invent unreadable text. "
                        "Reply with the transcription only, no commentary."
                    ),
                    max_output_tokens=max_tokens,
                    temperature=0.0,
                ),
            )
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"[:400]
            self._trip_cooldown(exc)
            raise LLMUnavailable(self.last_error) from exc
        text = getattr(response, "text", None)
        if not text:
            raise LLMUnavailable("Gemini returned no OCR text")
        return str(text).strip()

    def complete_json(self, system: str, user: str, max_tokens: int | None = None) -> dict[str, Any]:
        resp = self.messages_create(
            system=system,
            messages=[{"role": "user", "content": user}],
            max_tokens=max_tokens,
            json_mode=True,
        )
        return extract_json_object(resp.text)


class GroqClient:
    """OpenAI-compatible Groq chat-completions client (secondary provider).

    Mirrors the small surface the agent uses on ``GeminiClient`` so the loop and
    its tools are unchanged. Groq does not do screenshot OCR here, so
    ``vision_extract`` always raises; screenshots stay a Gemini-only feature.
    """

    def __init__(self, api_key: str | None, model: str = GROQ_DEFAULT_MODEL,
                 max_tokens: int = 2400, timeout: float = 25.0,
                 cooldown_seconds: float = 60.0, base_url: str = GROQ_DEFAULT_BASE_URL,
                 client: httpx.Client | None = None) -> None:
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.cooldown_seconds = cooldown_seconds
        self.base_url = base_url.rstrip("/")
        self._client = client
        self.last_error: str | None = None
        self._cooldown_until: float = 0.0

    @property
    def available(self) -> bool:
        return bool(self.api_key) and time.monotonic() >= self._cooldown_until

    @property
    def provider(self) -> str:
        return "groq"

    @property
    def cooldown_remaining(self) -> float:
        return max(0.0, self._cooldown_until - time.monotonic())

    def _trip_cooldown(self, exc: Exception) -> None:
        text = f"{type(exc).__name__}: {exc}"
        if "429" in text or "RESOURCE_EXHAUSTED" in text:
            self._cooldown_until = time.monotonic() + self.cooldown_seconds
            log.warning(
                "Groq quota exhausted — pausing fallback calls for %.0fs",
                self.cooldown_seconds,
            )

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout)
        return self._client

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.base_url}/chat/completions"
        client = self._http()
        try:
            response = client.post(url, headers=headers, json=payload)
            if response.status_code == 429:
                # Single short retry; the local agent is still available after this.
                retry_after = response.headers.get("retry-after")
                try:
                    delay = min(3.0, max(0.5, float(retry_after))) if retry_after else 1.5
                except ValueError:
                    delay = 1.5
                time.sleep(delay)
                response = client.post(url, headers=headers, json=payload)
        except httpx.HTTPError as exc:
            raise LLMUnavailable(f"Groq request failed: {type(exc).__name__}") from exc

        if response.status_code >= 400:
            detail = _redact_secret(response.text[:300], self.api_key)
            raise LLMUnavailable(f"Groq HTTP {response.status_code}: {detail}")
        try:
            return response.json()
        except ValueError as exc:
            raise LLMUnavailable(f"Groq returned invalid JSON: {exc}") from exc

    @staticmethod
    def _convert_messages(system: str | list[dict[str, Any]],
                          messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        converted: list[dict[str, Any]] = [
            {"role": "system", "content": GeminiClient._system_text(system)}
        ]
        for message in messages:
            role = message.get("role")
            raw = message.get("content", "")
            if isinstance(raw, str):
                converted.append({
                    "role": "assistant" if role == "assistant" else "user",
                    "content": raw,
                })
                continue

            blocks = raw if isinstance(raw, list) else [{"type": "text", "text": str(raw)}]
            texts: list[str] = []
            calls: list[dict[str, Any]] = []
            tool_results: list[dict[str, Any]] = []
            for block in blocks:
                if not isinstance(block, dict):
                    texts.append(str(block))
                    continue
                block_type = block.get("type")
                if block_type == "text":
                    if block.get("text"):
                        texts.append(str(block["text"]))
                elif block_type == "image":
                    raise LLMUnavailable("Groq fallback cannot read screenshots")
                elif block_type == "tool_use":
                    calls.append({
                        "id": str(block.get("id") or f"call_{uuid.uuid4().hex}"),
                        "type": "function",
                        "function": {
                            "name": str(block.get("name", "")),
                            "arguments": json.dumps(block.get("input") or {}),
                        },
                    })
                elif block_type == "tool_result":
                    result = block.get("content", "")
                    if not isinstance(result, str):
                        result = json.dumps(result, ensure_ascii=False)
                    tool_results.append({
                        "role": "tool",
                        "tool_call_id": str(block.get("tool_use_id") or ""),
                        "content": result,
                    })

            if role == "assistant":
                entry: dict[str, Any] = {"role": "assistant"}
                if texts:
                    entry["content"] = "\n".join(texts)
                if calls:
                    entry["tool_calls"] = calls
                if texts or calls:
                    converted.append(entry)
            else:
                # OpenAI requires tool replies immediately after the assistant turn.
                converted.extend(tool_results)
                if texts:
                    converted.append({"role": "user", "content": "\n".join(texts)})
        return converted

    def messages_create(self, *, system: str | list[dict[str, Any]], messages: list[dict[str, Any]],
                        tools: list[dict[str, Any]] | None = None, max_tokens: int | None = None,
                        temperature: float = 0.2, json_mode: bool = False) -> LLMResponse:
        if not self.api_key:
            raise LLMUnavailable("GROQ_API_KEY is not set")

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": self._convert_messages(system, messages),
            "temperature": temperature,
            "max_tokens": max_tokens or self.max_tokens,
        }
        declarations = [
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool.get("input_schema") or {"type": "object", "properties": {}},
                },
            }
            for tool in tools or []
        ]
        if declarations:
            payload["tools"] = declarations
            payload["tool_choice"] = "auto"
        elif json_mode:
            payload["response_format"] = {"type": "json_object"}

        try:
            data = self._post(payload)
        except LLMUnavailable as exc:
            self.last_error = _redact_secret(str(exc), self.api_key)[:400]
            self._trip_cooldown(exc)
            raise

        try:
            choice = (data.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            content = message.get("content") or ""
            if isinstance(content, list):
                content = "".join(
                    str(part.get("text", "")) if isinstance(part, dict) else str(part)
                    for part in content
                )
            content = str(content)

            blocks: list[dict[str, Any]] = []
            tool_calls: list[dict[str, Any]] = []
            if content:
                blocks.append({"type": "text", "text": content})
            for item in message.get("tool_calls") or []:
                function = item.get("function") or {}
                raw_args = function.get("arguments")
                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
                except json.JSONDecodeError:
                    args = {}
                if not isinstance(args, dict):
                    args = {"value": args}
                call = {
                    "id": str(item.get("id") or f"call_{uuid.uuid4().hex}"),
                    "name": str(function.get("name", "")),
                    "input": args,
                }
                tool_calls.append(call)
                blocks.append({"type": "tool_use", **call})

            usage_raw = data.get("usage") or {}
            usage = {
                "input_tokens": usage_raw.get("prompt_tokens"),
                "output_tokens": usage_raw.get("completion_tokens"),
            }
        except Exception as exc:  # noqa: BLE001 - malformed provider payload
            self.last_error = f"Groq response parse error: {type(exc).__name__}"[:400]
            raise LLMUnavailable(self.last_error) from exc

        return LLMResponse(
            text=content.strip(),
            tool_calls=tool_calls,
            stop_reason=choice.get("finish_reason"),
            usage=usage,
            raw_blocks=blocks,
        )

    def vision_extract(self, image_bytes: bytes, media_type: str, instruction: str,
                       max_tokens: int = 1200) -> str:
        raise LLMUnavailable("Groq fallback does not support screenshot OCR")

    def complete_json(self, system: str, user: str, max_tokens: int | None = None) -> dict[str, Any]:
        resp = self.messages_create(
            system=system,
            messages=[{"role": "user", "content": user}],
            max_tokens=max_tokens,
            json_mode=True,
        )
        return extract_json_object(resp.text)


class FallbackLLMClient:
    """Gemini first, Groq second, deterministic local agent last.

    The agent loop talks to this object exactly as it talked to ``GeminiClient``.
    A Gemini 429 trips Gemini's cooldown, and the next call (and this one, via
    the retry below) goes straight to Groq instead of dropping to offline mode.
    """

    def __init__(self, primary: GeminiClient, fallback: GroqClient | None = None) -> None:
        self.primary = primary
        self.fallback = fallback
        self.last_provider: str | None = None

    @property
    def api_key(self) -> str | None:
        return self.primary.api_key

    @property
    def model(self) -> str:
        if self.primary.available:
            return self.primary.model
        if self.fallback is not None and self.fallback.available:
            return self.fallback.model
        return self.primary.model

    @property
    def available(self) -> bool:
        return self.primary.available or bool(self.fallback and self.fallback.available)

    @property
    def cooldown_remaining(self) -> float:
        fallback_cooldown = self.fallback.cooldown_remaining if self.fallback else 0.0
        return max(self.primary.cooldown_remaining, fallback_cooldown)

    @property
    def primary_configured(self) -> bool:
        return bool(self.primary.api_key)

    @property
    def fallback_configured(self) -> bool:
        return bool(self.fallback and self.fallback.api_key)

    @property
    def provider(self) -> str:
        if self.primary.available:
            return self.primary.provider
        if self.fallback is not None and self.fallback.available:
            return self.fallback.provider
        return "none"

    def messages_create(self, *, system: str | list[dict[str, Any]], messages: list[dict[str, Any]],
                        tools: list[dict[str, Any]] | None = None, max_tokens: int | None = None,
                        temperature: float = 0.2, json_mode: bool = False) -> LLMResponse:
        errors: list[str] = []

        if self.primary.available:
            try:
                response = self.primary.messages_create(
                    system=system, messages=messages, tools=tools,
                    max_tokens=max_tokens, temperature=temperature, json_mode=json_mode,
                )
                self.last_provider = self.primary.provider
                log.debug("llm_event=gemini_used model=%s", self.primary.model)
                return response
            except LLMUnavailable as exc:
                errors.append(f"gemini: {exc}")
                log.warning("llm_event=gemini_failed error=%s", exc)
        else:
            if self.primary.api_key:
                log.warning("llm_event=gemini_failed reason=cooldown")
            else:
                log.info("llm_event=gemini_failed reason=no_key")

        if self.fallback is not None and self.fallback.available:
            try:
                response = self.fallback.messages_create(
                    system=system, messages=messages, tools=tools,
                    max_tokens=max_tokens, temperature=temperature, json_mode=json_mode,
                )
                self.last_provider = self.fallback.provider
                log.info("llm_event=groq_used model=%s", self.fallback.model)
                return response
            except LLMUnavailable as exc:
                errors.append(f"groq: {exc}")
                log.warning("llm_event=groq_failed error=%s", exc)
        else:
            if self.fallback is not None and self.fallback.api_key:
                log.warning("llm_event=groq_failed reason=cooldown")
            else:
                log.info("llm_event=groq_failed reason=no_key")

        log.error("llm_event=both_failed_offline")
        raise LLMUnavailable("; ".join(errors) or "no LLM provider configured")

    def vision_extract(self, image_bytes: bytes, media_type: str, instruction: str,
                       max_tokens: int = 1200) -> str:
        if not self.primary.available:
            reason = "cooldown" if self.primary.api_key else "no_key"
            log.warning("llm_event=gemini_failed reason=%s", reason)
            log.error("llm_event=both_failed_offline reason=vision_requires_gemini")
            raise LLMUnavailable("screenshot OCR requires an available Gemini client")
        try:
            text = self.primary.vision_extract(image_bytes, media_type, instruction, max_tokens)
            self.last_provider = self.primary.provider
            return text
        except LLMUnavailable as exc:
            log.warning("llm_event=gemini_failed error=%s", exc)
            log.error("llm_event=both_failed_offline reason=vision_requires_gemini")
            raise LLMUnavailable(f"screenshot OCR requires Gemini: {exc}") from exc

    def complete_json(self, system: str, user: str, max_tokens: int | None = None) -> dict[str, Any]:
        resp = self.messages_create(
            system=system,
            messages=[{"role": "user", "content": user}],
            max_tokens=max_tokens,
            json_mode=True,
        )
        return extract_json_object(resp.text)


def build_llm_client(settings: Settings) -> FallbackLLMClient:
    """Build the provider chain from settings: Gemini -> Groq -> offline."""
    primary = GeminiClient(
        api_key=settings.gemini_api_key,
        model=settings.gemini_model,
        max_tokens=settings.gemini_max_tokens,
        timeout=settings.gemini_timeout_seconds,
        cooldown_seconds=settings.llm_cooldown_seconds,
        thinking_budget=settings.gemini_thinking_budget,
    )
    fallback = None
    if settings.groq_api_key:
        fallback = GroqClient(
            api_key=settings.groq_api_key,
            model=settings.groq_model,
            max_tokens=settings.gemini_max_tokens,
            timeout=settings.groq_timeout_seconds,
            cooldown_seconds=settings.llm_cooldown_seconds,
            base_url=settings.groq_base_url,
        )
    return FallbackLLMClient(primary, fallback)



def extract_json_object(text: str) -> dict[str, Any]:
    """Pull the first balanced JSON object out of a model reply."""
    if not text:
        raise LLMUnavailable("empty model reply")
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        if cleaned.lstrip().lower().startswith("json"):
            cleaned = cleaned.lstrip()[4:]
    start = cleaned.find("{")
    if start == -1:
        raise LLMUnavailable("no JSON object in reply")
    depth, in_str, esc = 0, False, False
    for i, ch in enumerate(cleaned[start:], start=start):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = cleaned[start:i + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError as exc:
                    raise LLMUnavailable(f"invalid JSON from model: {exc}") from exc
    raise LLMUnavailable("unterminated JSON object in reply")
