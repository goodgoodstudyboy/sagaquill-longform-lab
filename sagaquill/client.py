from __future__ import annotations

import hashlib
import http.client
import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import urlparse

from .models import ProviderConfig
from .retrying import is_retryable_error_text
from .util import extract_json_object


class ModelClientError(RuntimeError):
    pass


class JsonParseModelClientError(ModelClientError):
    def __init__(self, message: str, *, raw_text: str) -> None:
        super().__init__(message)
        self.raw_text = raw_text


StreamObserver = Callable[[str], None]


@dataclass(slots=True)
class RequestOptions:
    model: str
    temperature: float
    max_output_tokens: int | None = None
    json_mode: bool = False
    provider_tier: str = "flagship"


@dataclass(slots=True)
class SessionMessage:
    role: str
    text: str


@dataclass(slots=True)
class SessionState:
    session_id: str
    system_prompt: str
    model: str
    max_history_chars: int
    history: list[SessionMessage] = field(default_factory=list)
    last_response_id: str | None = None


@dataclass(slots=True)
class ResponseResult:
    text: str
    response_id: str | None = None


class OpenAICompatibleClient:
    def __init__(
        self,
        provider: ProviderConfig,
        timeout_seconds: int = 180,
        retries: int = 2,
        default_session_max_chars: int = 80000,
        routing_namespace: str | None = None,
    ) -> None:
        self.provider = provider
        self.timeout_seconds = timeout_seconds
        self.retries = retries
        self.default_session_max_chars = default_session_max_chars
        self.sessions: dict[str, SessionState] = {}
        self.routing_namespace = routing_namespace or ""

    def request_time_budget_seconds(self) -> int:
        delay_budget = sum(self._retry_delay(attempt) for attempt in range(self.retries))
        return int(self.timeout_seconds * (self.retries + 1) + delay_budget)

    def set_routing_namespace(self, namespace: str | None) -> None:
        self.routing_namespace = str(namespace or "")

    def _is_retryable_model_error(self, exc: ModelClientError) -> bool:
        return is_retryable_error_text(str(exc))

    def generate_text(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        model: str | None = None,
        temperature: float = 0.3,
        max_output_tokens: int | None = None,
        json_mode: bool = False,
        session_id: str | None = None,
        session_max_chars: int | None = None,
        stream: bool = False,
        stream_observer: StreamObserver | None = None,
        provider_tier: str = "flagship",
    ) -> str:
        options = RequestOptions(
            model=model or self.provider.model,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            json_mode=json_mode,
            provider_tier=provider_tier,
        )
        session = self._resolve_session(session_id, system_prompt, options.model, session_max_chars)
        result = self._execute_request(
            system_prompt,
            user_prompt,
            options,
            session=session,
            stream=stream,
            stream_observer=stream_observer,
        )
        if session is not None:
            self._commit_session(session, user_prompt, result.text, result.response_id)
        return result.text.strip()

    def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        model: str | None = None,
        temperature: float = 0.2,
        max_output_tokens: int | None = None,
        session_id: str | None = None,
        session_max_chars: int | None = None,
        stream: bool = False,
        stream_observer: StreamObserver | None = None,
        provider_tier: str = "flagship",
    ) -> Any:
        options = RequestOptions(
            model=model or self.provider.model,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            json_mode=True,
            provider_tier=provider_tier,
        )
        session = self._resolve_session(session_id, system_prompt, options.model, session_max_chars)
        last_error: Exception | None = None
        last_raw_text = ""
        for attempt in range(self.retries + 1):
            result = self._execute_request(
                system_prompt,
                user_prompt,
                options,
                session=session,
                stream=stream,
                stream_observer=stream_observer,
            )
            last_raw_text = result.text
            try:
                payload = extract_json_object(result.text)
            except ValueError as exc:
                last_error = exc
                if attempt >= self.retries:
                    break
                time.sleep(0.8 * (attempt + 1))
                continue
            if session is not None:
                self._commit_session(session, user_prompt, result.text, result.response_id)
            return payload
        raise JsonParseModelClientError(
            f"Model did not return valid JSON: {last_error}",
            raw_text=last_raw_text,
        ) from last_error

    def reset_session(self, session_id: str) -> None:
        self.sessions.pop(session_id, None)

    def _resolve_session(
        self,
        session_id: str | None,
        system_prompt: str,
        model: str,
        session_max_chars: int | None,
    ) -> SessionState | None:
        if not session_id:
            return None
        session = self.sessions.get(session_id)
        max_chars = session_max_chars or self.default_session_max_chars
        if session is None or session.system_prompt != system_prompt or session.model != model:
            session = SessionState(
                session_id=session_id,
                system_prompt=system_prompt,
                model=model,
                max_history_chars=max_chars,
            )
            self.sessions[session_id] = session
            return session
        session.max_history_chars = max_chars
        return session

    def _execute_request(
        self,
        system_prompt: str,
        user_prompt: str,
        options: RequestOptions,
        *,
        session: SessionState | None,
        stream: bool,
        stream_observer: StreamObserver | None,
    ) -> ResponseResult:
        payload = self._build_payload(system_prompt, user_prompt, options, session=session, stream=stream)
        if stream and self.provider.wire_api in {"responses", "anthropic-messages"}:
            return self._request_stream(payload, stream_observer)
        raw = self._request_json(payload)
        return ResponseResult(text=self._extract_text(raw).strip(), response_id=self._extract_response_id(raw))

    def _build_payload(
        self,
        system_prompt: str,
        user_prompt: str,
        options: RequestOptions,
        *,
        session: SessionState | None,
        stream: bool,
    ) -> dict[str, Any]:
        if self.provider.wire_api == "anthropic-messages":
            payload = {
                "model": options.model,
                "messages": self._build_anthropic_messages(user_prompt, session),
                "max_tokens": options.max_output_tokens or 4096,
                "temperature": options.temperature,
            }
            if system_prompt.strip():
                payload["system"] = system_prompt
            if stream:
                payload["stream"] = True
            if session is not None:
                payload["_sagaquill_session_id"] = session.session_id
            return payload

        if self.provider.wire_api == "responses":
            input_items = self._build_responses_input(system_prompt, user_prompt, session)
            payload: dict[str, Any] = {
                "model": options.model,
                "input": input_items,
                "temperature": options.temperature,
            }
            self._apply_advanced_provider_fields(payload, wire_api="responses", provider_tier=options.provider_tier)
            if session is not None:
                payload["_sagaquill_session_id"] = session.session_id
            if self._use_provider_continuation(session):
                payload["previous_response_id"] = session.last_response_id
            if options.max_output_tokens is not None:
                payload["max_output_tokens"] = options.max_output_tokens
            if stream:
                payload["stream"] = True
            return payload

        messages = self._build_chat_messages(system_prompt, user_prompt, session)
        payload = {
            "model": options.model,
            "messages": messages,
            "temperature": options.temperature,
        }
        self._apply_advanced_provider_fields(payload, wire_api="chat-completions", provider_tier=options.provider_tier)
        if session is not None:
            payload["_sagaquill_session_id"] = session.session_id
        if options.max_output_tokens is not None:
            payload["max_tokens"] = options.max_output_tokens
        return payload

    def _apply_advanced_provider_fields(
        self,
        payload: dict[str, Any],
        *,
        wire_api: str,
        provider_tier: str,
    ) -> None:
        reasoning_effort = self._reasoning_effort_for_tier(provider_tier)
        if reasoning_effort:
            if wire_api == "responses":
                payload["reasoning"] = {"effort": reasoning_effort}
            else:
                payload["reasoning_effort"] = reasoning_effort
        service_tier = self._normalized_service_tier(self._service_tier_for_tier(provider_tier))
        if service_tier:
            payload["service_tier"] = service_tier

    def _reasoning_effort_for_tier(self, provider_tier: str) -> str | None:
        tier = provider_tier.strip().lower()
        if tier == "light":
            return self.provider.light_reasoning_effort or self.provider.reasoning_effort
        return self.provider.flagship_reasoning_effort or self.provider.reasoning_effort

    def _service_tier_for_tier(self, provider_tier: str) -> str | None:
        tier = provider_tier.strip().lower()
        if tier == "light":
            return self.provider.light_service_tier or self.provider.service_tier
        return self.provider.flagship_service_tier or self.provider.service_tier

    def _normalized_service_tier(self, value: str | None) -> str | None:
        tier = (value or "").strip().lower()
        if not tier:
            return None
        if tier == "fast" and self._gateway_profile() == "sub2api":
            # sub2api expects priority for Codex-style fast.
            return "priority"
        return tier

    def _gateway_profile(self) -> str:
        configured = (self.provider.gateway_profile or "").strip().lower()
        if configured and configured != "auto":
            return configured
        base_url = (self.provider.base_url or "").strip().lower()
        if "sub2api" in base_url:
            return "sub2api"
        return "generic"

    def _build_responses_input(
        self,
        system_prompt: str,
        user_prompt: str,
        session: SessionState | None,
    ) -> list[dict[str, Any]]:
        if self._use_provider_only_input(session):
            return [self._responses_message("user", user_prompt, "input_text")]
        input_items = [self._responses_message("system", system_prompt, "input_text")]
        if session is not None:
            input_items.extend(self._responses_history(session))
        input_items.append(self._responses_message("user", user_prompt, "input_text"))
        return input_items

    def _build_chat_messages(
        self,
        system_prompt: str,
        user_prompt: str,
        session: SessionState | None,
    ) -> list[dict[str, Any]]:
        messages = [{"role": "system", "content": system_prompt}]
        if session is not None:
            messages.extend({"role": message.role, "content": message.text} for message in self._trimmed_history(session))
        messages.append({"role": "user", "content": user_prompt})
        return messages

    def _build_anthropic_messages(
        self,
        user_prompt: str,
        session: SessionState | None,
    ) -> list[dict[str, Any]]:
        messages = [
            {"role": message.role, "content": message.text}
            for message in self._trimmed_history(session)
        ] if session is not None else []
        messages.append({"role": "user", "content": user_prompt})
        return messages

    def _responses_history(self, session: SessionState) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for message in self._trimmed_history(session):
            content_type = "output_text" if message.role == "assistant" else "input_text"
            items.append(self._responses_message(message.role, message.text, content_type))
        return items

    def _trimmed_history(self, session: SessionState) -> list[SessionMessage]:
        turns: list[list[SessionMessage]] = []
        current: list[SessionMessage] = []
        for message in session.history:
            current.append(message)
            if message.role == "assistant":
                turns.append(current)
                current = []
        if current:
            turns.append(current)

        kept_turns: list[list[SessionMessage]] = []
        total_chars = 0
        for turn in reversed(turns):
            turn_chars = sum(len(message.text) for message in turn)
            if kept_turns and total_chars + turn_chars > session.max_history_chars:
                break
            kept_turns.append(turn)
            total_chars += turn_chars
            if total_chars >= session.max_history_chars:
                break

        trimmed: list[SessionMessage] = []
        for turn in reversed(kept_turns):
            trimmed.extend(turn)
        return trimmed

    def _commit_session(
        self,
        session: SessionState,
        user_prompt: str,
        assistant_text: str,
        response_id: str | None,
    ) -> None:
        session.history.append(SessionMessage(role="user", text=user_prompt))
        session.history.append(SessionMessage(role="assistant", text=assistant_text))
        session.last_response_id = response_id

    def _request_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        errors: list[str] = []
        for url in self._candidate_urls():
            result, error = self._attempt_request(url, payload, stream=False, stream_observer=None)
            if result is not None:
                return result
            if error:
                errors.append(error)
        if errors:
            raise ModelClientError("All candidate endpoints failed: " + " | ".join(errors))
        raise ModelClientError("Provider request failed without an error.")

    def _request_stream(self, payload: dict[str, Any], stream_observer: StreamObserver | None) -> ResponseResult:
        errors: list[str] = []
        for url in self._candidate_urls():
            result, error = self._attempt_request(url, payload, stream=True, stream_observer=stream_observer)
            if result is not None:
                return result
            if error:
                errors.append(error)
        if errors:
            raise ModelClientError("All candidate stream endpoints failed: " + " | ".join(errors))
        raise ModelClientError("Provider stream request failed without an error.")

    def _attempt_request(
        self,
        url: str,
        payload: dict[str, Any],
        *,
        stream: bool,
        stream_observer: StreamObserver | None,
    ) -> tuple[dict[str, Any] | ResponseResult | None, str | None]:
        last_error: str | None = None
        for attempt in range(self.retries + 1):
            try:
                if stream:
                    return self._post_stream(url, payload, stream_observer), None
                return self._post_json(url, payload), None
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", "replace")
                exc.close()
                if exc.code in {404, 405, 502, 503, 504}:
                    return None, f"{url} -> HTTP {exc.code}: {body}"
                if self._is_retryable_http_status(exc.code) and attempt < self.retries:
                    last_error = f"{url} -> HTTP {exc.code}: {body}"
                    time.sleep(self._retry_delay(attempt))
                    continue
                if self._is_retryable_http_status(exc.code):
                    return None, f"{url} -> HTTP {exc.code}: {body}"
                raise ModelClientError(f"HTTP {exc.code} from provider at {url}: {body}") from exc
            except (
                urllib.error.URLError,
                http.client.RemoteDisconnected,
                http.client.IncompleteRead,
                ConnectionResetError,
                ConnectionAbortedError,
                BrokenPipeError,
            ) as exc:
                reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
                last_error = f"{url} -> network error: {reason}"
                if attempt >= self.retries:
                    return None, last_error
                time.sleep(self._retry_delay(attempt))
            except TimeoutError as exc:
                last_error = f"{url} -> timeout: {exc}"
                if attempt >= self.retries:
                    return None, last_error
                time.sleep(self._retry_delay(attempt))
            except ModelClientError as exc:
                last_error = f"{url} -> {exc}"
                if not self._is_retryable_model_error(exc) or attempt >= self.retries:
                    raise
                time.sleep(self._retry_delay(attempt))
        return None, last_error

    def _post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        body_payload, session = self._payload_and_session(payload)
        body = json.dumps(body_payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers=self._request_headers(session),
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            raw = response.read().decode(charset, "replace")
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise JsonParseModelClientError(
                "Model did not return valid JSON: Could not parse JSON payload from model output.",
                raw_text=raw.strip(),
            ) from exc

    def _post_stream(self, url: str, payload: dict[str, Any], stream_observer: StreamObserver | None) -> ResponseResult:
        body_payload, session = self._payload_and_session(payload)
        body = json.dumps(body_payload).encode("utf-8")
        headers = self._request_headers(session)
        headers["Accept"] = "text/event-stream"
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            content_type = response.headers.get("Content-Type", "")
            if "text/event-stream" not in content_type.lower():
                charset = response.headers.get_content_charset() or "utf-8"
                raw = response.read().decode(charset, "replace")
                try:
                    payload_json = json.loads(raw)
                except json.JSONDecodeError:
                    text = raw.strip()
                    if stream_observer and text:
                        stream_observer(text)
                    return ResponseResult(text=text, response_id=None)
                text = self._extract_text(payload_json).strip()
                if stream_observer and text:
                    stream_observer(text)
                return ResponseResult(text=text, response_id=self._extract_response_id(payload_json))
            if self.provider.wire_api == "anthropic-messages":
                return self._consume_anthropic_sse_stream(response, stream_observer)
            return self._consume_sse_stream(response, stream_observer)

    def _consume_anthropic_sse_stream(
        self,
        response: Any,
        stream_observer: StreamObserver | None,
    ) -> ResponseResult:
        charset = response.headers.get_content_charset() or "utf-8"
        event_name = ""
        data_lines: list[str] = []
        accumulated = ""
        final_message: dict[str, Any] | None = None
        response_id: str | None = None

        def append_text(text: str | None) -> None:
            nonlocal accumulated
            if isinstance(text, str) and text:
                accumulated += text
                if stream_observer:
                    stream_observer(text)

        def flush_event(current_event: str, current_lines: list[str]) -> tuple[str, list[str]]:
            nonlocal final_message
            nonlocal response_id
            if not current_lines:
                return "", []
            data = "\n".join(current_lines).strip()
            if not data or data == "[DONE]":
                return "", []
            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                return "", []

            payload_type = str(payload.get("type") or current_event or "")
            if payload_type == "error":
                error_payload = payload.get("error")
                if isinstance(error_payload, dict):
                    error_message = error_payload.get("message")
                else:
                    error_message = payload.get("message")
                raise ModelClientError(str(error_message or "Anthropic streaming request failed."))

            if payload_type == "message_start":
                message = payload.get("message")
                if isinstance(message, dict):
                    final_message = message
                    response_id = self._extract_response_id(message) or response_id
                return "", []

            if payload_type == "content_block_start":
                block = payload.get("content_block")
                if isinstance(block, dict):
                    append_text(block.get("text"))
                return "", []

            if payload_type == "content_block_delta":
                delta = payload.get("delta")
                if isinstance(delta, dict):
                    append_text(delta.get("text"))
                else:
                    append_text(payload.get("text"))
                return "", []

            if payload_type == "message_delta":
                delta = payload.get("delta")
                if isinstance(final_message, dict) and isinstance(delta, dict):
                    final_message.update(delta)
                return "", []

            if payload_type == "message_stop":
                return "", []

            message = payload.get("message")
            if isinstance(message, dict):
                final_message = message
                response_id = self._extract_response_id(message) or response_id
            return "", []

        while True:
            line = response.readline()
            if not line:
                break
            decoded = line.decode(charset, "replace")
            stripped = decoded.rstrip("\r\n")
            if not stripped:
                event_name, data_lines = flush_event(event_name, data_lines)
                continue
            if stripped.startswith("event:"):
                event_name = stripped[6:].strip()
                continue
            if stripped.startswith("data:"):
                data_lines.append(stripped[5:].strip())

        flush_event(event_name, data_lines)

        if not accumulated and final_message is not None:
            try:
                accumulated = self._extract_text(final_message).strip()
            except ModelClientError:
                accumulated = ""
        if not accumulated:
            raise ModelClientError("Streaming response completed without text.")
        return ResponseResult(text=accumulated, response_id=response_id)

    def _consume_sse_stream(
        self,
        response: Any,
        stream_observer: StreamObserver | None,
    ) -> ResponseResult:
        charset = response.headers.get_content_charset() or "utf-8"
        event_name = ""
        data_lines: list[str] = []
        accumulated = ""
        final_payload: dict[str, Any] | None = None
        output_items: list[dict[str, Any]] = []
        response_id: str | None = None

        def flush_event(current_event: str, current_lines: list[str]) -> tuple[str, list[str]]:
            nonlocal accumulated
            nonlocal final_payload
            nonlocal output_items
            nonlocal response_id
            if not current_lines:
                return "", []
            data = "\n".join(current_lines).strip()
            if not data or data == "[DONE]":
                return "", []
            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                return "", []

            payload_type = str(payload.get("type") or current_event or "")
            response_payload = payload.get("response") if isinstance(payload.get("response"), dict) else payload
            response_id = self._extract_response_id(response_payload) or response_id
            item_payload = payload.get("item") if isinstance(payload.get("item"), dict) else None

            if payload_type in {"error", "response.failed"}:
                error_message = (
                    payload.get("error", {}).get("message")
                    if isinstance(payload.get("error"), dict)
                    else payload.get("message")
                )
                raise ModelClientError(str(error_message or "Streaming request failed."))

            if payload_type == "response.output_text.delta":
                delta = payload.get("delta")
                if isinstance(delta, str) and delta:
                    accumulated += delta
                    if stream_observer:
                        stream_observer(delta)
                return "", []

            if payload_type == "response.output_text.done":
                done_text = payload.get("text")
                if not accumulated and isinstance(done_text, str) and done_text:
                    accumulated = done_text
                    if stream_observer:
                        stream_observer(done_text)
                return "", []

            if payload_type in {"response.output_item.added", "response.output_item.done"} and item_payload is not None:
                output_items.append(item_payload)
                return "", []

            if payload_type in {"response.content_part.added", "response.content_part.done"} and item_payload is not None:
                output_items.append(item_payload)
                return "", []

            if payload_type == "response.completed" and isinstance(response_payload, dict):
                final_payload = response_payload
                return "", []

            if isinstance(response_payload, dict):
                has_text = isinstance(response_payload.get("output_text"), str)
                has_output = isinstance(response_payload.get("output"), list)
                if has_text or has_output:
                    final_payload = response_payload
                    return "", []

            return "", []

        while True:
            line = response.readline()
            if not line:
                break
            decoded = line.decode(charset, "replace")
            stripped = decoded.rstrip("\r\n")
            if not stripped:
                event_name, data_lines = flush_event(event_name, data_lines)
                continue
            if stripped.startswith("event:"):
                event_name = stripped[6:].strip()
                continue
            if stripped.startswith("data:"):
                data_lines.append(stripped[5:].strip())

        flush_event(event_name, data_lines)

        if final_payload is not None and not accumulated:
            try:
                accumulated = self._extract_text(final_payload).strip()
            except ModelClientError:
                accumulated = ""
        if not accumulated and output_items:
            try:
                accumulated = self._extract_text({"output": output_items}).strip()
            except ModelClientError:
                accumulated = ""
        if not accumulated:
            raise ModelClientError("Streaming response completed without text.")
        return ResponseResult(text=accumulated, response_id=response_id)

    def _request_headers(self, session: SessionState | None = None) -> dict[str, str]:
        if self.provider.wire_api == "anthropic-messages":
            headers = {
                "x-api-key": self.provider.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
                "User-Agent": "sagaquill/0.2",
            }
        else:
            headers = {
                "Authorization": f"Bearer {self.provider.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "sagaquill/0.2",
            }
        sticky_session_id = self._sticky_session_id(session)
        if sticky_session_id:
            headers["session_id"] = sticky_session_id
        headers.update(self.provider.default_headers)
        return headers

    def _sticky_session_id(self, session: SessionState | None) -> str | None:
        if session is None:
            return None
        seed = f"{self.routing_namespace}\n{session.session_id}"
        digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]
        label = re.sub(r"[^A-Za-z0-9._-]+", "-", session.session_id).strip("-") or "session"
        return f"sagaquill-{label[:40]}-{digest}"

    def _payload_and_session(self, payload: dict[str, Any]) -> tuple[dict[str, Any], SessionState | None]:
        body_payload = dict(payload)
        marker = body_payload.pop("_sagaquill_session_id", None)
        if not isinstance(marker, str):
            return body_payload, None
        return body_payload, self.sessions.get(marker)

    def _use_provider_continuation(self, session: SessionState | None) -> bool:
        return (
            session is not None
            and bool(session.last_response_id)
            and self.provider.wire_api == "responses"
            and self.provider.continuation_mode in {"previous_response_id", "hybrid"}
        )

    def _use_provider_only_input(self, session: SessionState | None) -> bool:
        return self._use_provider_continuation(session) and self.provider.continuation_mode == "previous_response_id"

    def _candidate_urls(self) -> list[str]:
        if self.provider.wire_api == "anthropic-messages":
            base = self.provider.base_url.rstrip("/")
            parsed = urlparse(base)
            path = parsed.path.rstrip("/")
            if path.endswith("/v1"):
                return [f"{base}/messages"]
            return [f"{base}/v1/messages", f"{base}/messages"]
        suffix = "responses" if self.provider.wire_api == "responses" else "chat/completions"
        base = self.provider.base_url.rstrip("/")
        parsed = urlparse(base)
        path = parsed.path.rstrip("/")
        urls = [f"{base}/{suffix}"]
        if path.endswith("/v1"):
            return urls
        urls.append(f"{base}/v1/{suffix}")
        return urls

    def _responses_message(self, role: str, text: str, content_type: str) -> dict[str, Any]:
        return {"role": role, "content": [{"type": content_type, "text": text}]}

    def _extract_response_id(self, payload: Any) -> str | None:
        if isinstance(payload, dict):
            response_id = payload.get("id")
            if isinstance(response_id, str):
                return response_id
        return None

    def _extract_text(self, payload: dict[str, Any]) -> str:
        if self.provider.wire_api == "anthropic-messages":
            content = payload.get("content")
            if isinstance(content, list):
                parts: list[str] = []
                for item in content:
                    if not isinstance(item, dict):
                        continue
                    if item.get("type") == "text" and isinstance(item.get("text"), str):
                        parts.append(item["text"])
                combined = "".join(parts).strip()
                if combined:
                    return combined
            raise ModelClientError("Could not extract text from anthropic messages payload.")

        if self.provider.wire_api == "responses":
            extracted = self._extract_responses_text(payload)
            if extracted:
                return extracted
            raise ModelClientError("Could not extract text from responses payload.")

        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ModelClientError("Chat completion returned no choices.")
        message = choices[0].get("message", {})
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
            combined = "".join(parts).strip()
            if combined:
                return combined
        raise ModelClientError("Could not extract text from chat completions payload.")

    def _extract_responses_text(self, payload: Any) -> str:
        if not isinstance(payload, dict):
            return ""
        output_text = payload.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text
        content = payload.get("content")
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if not isinstance(item, dict):
                    continue
                text = item.get("text") or item.get("output_text")
                if isinstance(text, str):
                    parts.append(text)
            combined = "".join(parts).strip()
            if combined:
                return combined
        output = payload.get("output")
        if isinstance(output, list):
            parts: list[str] = []
            for item in output:
                if not isinstance(item, dict):
                    continue
                item_text = item.get("text") or item.get("output_text")
                if isinstance(item_text, str):
                    parts.append(item_text)
                nested = item.get("content", [])
                if isinstance(nested, list):
                    for content_item in nested:
                        if not isinstance(content_item, dict):
                            continue
                        text = content_item.get("text") or content_item.get("output_text")
                        if isinstance(text, str):
                            parts.append(text)
            combined = "".join(parts).strip()
            if combined:
                return combined
        for nested_key in ("response", "data"):
            nested_payload = payload.get(nested_key)
            extracted = self._extract_responses_text(nested_payload)
            if extracted:
                return extracted
        return ""

    def _is_retryable_http_status(self, status_code: int) -> bool:
        return status_code in {408, 409, 429, 500, 520, 522, 524}

    def _retry_delay(self, attempt: int) -> float:
        return 1.0 * (attempt + 1)
