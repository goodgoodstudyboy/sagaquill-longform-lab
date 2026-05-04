from __future__ import annotations

import json
import socket
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from sagaquill.client import OpenAICompatibleClient
from sagaquill.client import JsonParseModelClientError, ModelClientError, ResponseResult
from sagaquill.client import RequestOptions
from sagaquill.models import ProviderConfig


class _FallbackHandler(BaseHTTPRequestHandler):
    requests: list[str] = []

    def do_POST(self) -> None:  # noqa: N802
        _FallbackHandler.requests.append(self.path)
        if self.path == "/responses":
            self.send_response(502)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"id": "resp-ok", "output_text": '{"ok": true}'}).encode("utf-8"))

    def log_message(self, format: str, *args) -> None:
        return


class _StreamHandler(BaseHTTPRequestHandler):
    bodies: list[dict] = []

    def do_POST(self) -> None:  # noqa: N802
        content_length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(content_length).decode("utf-8"))
        _StreamHandler.bodies.append(body)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        frames = [
            'event: response.created\ndata: {"type":"response.created","response":{"id":"resp-stream"}}\n\n',
            'event: response.output_text.delta\ndata: {"type":"response.output_text.delta","delta":"Hello "}\n\n',
            'event: response.output_text.delta\ndata: {"type":"response.output_text.delta","delta":"world"}\n\n',
            'event: response.completed\ndata: {"type":"response.completed","response":{"id":"resp-stream","output":[{"type":"message","role":"assistant","content":[{"type":"output_text","text":"Hello world"}]}]}}\n\n',
            "data: [DONE]\n\n",
        ]
        for frame in frames:
            self.wfile.write(frame.encode("utf-8"))
            self.wfile.flush()

    def log_message(self, format: str, *args) -> None:
        return


class _StreamOutputItemDoneHandler(BaseHTTPRequestHandler):
    bodies: list[dict] = []

    def do_POST(self) -> None:  # noqa: N802
        content_length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(content_length).decode("utf-8"))
        _StreamOutputItemDoneHandler.bodies.append(body)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        frames = [
            'event: response.created\ndata: {"type":"response.created","response":{"id":"resp-item"}}\n\n',
            'event: response.output_item.done\ndata: {"type":"response.output_item.done","item":{"type":"message","role":"assistant","content":[{"type":"output_text","text":"Recovered from item"}]}}\n\n',
            'event: response.completed\ndata: {"type":"response.completed","response":{"id":"resp-item"}}\n\n',
            "data: [DONE]\n\n",
        ]
        for frame in frames:
            self.wfile.write(frame.encode("utf-8"))
            self.wfile.flush()

    def log_message(self, format: str, *args) -> None:
        return


class _SessionHandler(BaseHTTPRequestHandler):
    bodies: list[dict] = []

    def do_POST(self) -> None:  # noqa: N802
        content_length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(content_length).decode("utf-8"))
        _SessionHandler.bodies.append(body)
        reply_text = "First answer" if len(_SessionHandler.bodies) == 1 else "Second answer"
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(
            json.dumps(
                {
                    "id": f"resp-{len(_SessionHandler.bodies)}",
                    "output": [
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": reply_text}],
                        }
                    ],
                }
            ).encode("utf-8")
        )

    def log_message(self, format: str, *args) -> None:
        return


class _WrappedResponsesHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        content_length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(content_length)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(
            json.dumps(
                {
                    "response": {
                        "id": "resp-wrapped",
                        "output": [
                            {
                                "type": "message",
                                "role": "assistant",
                                "content": [{"type": "output_text", "text": "Wrapped OK"}],
                            }
                        ],
                    }
                }
            ).encode("utf-8")
        )

    def log_message(self, format: str, *args) -> None:
        return


class _ContinuationHandler(BaseHTTPRequestHandler):
    bodies: list[dict] = []

    def do_POST(self) -> None:  # noqa: N802
        content_length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(content_length).decode("utf-8"))
        _ContinuationHandler.bodies.append(body)
        reply_text = "First answer" if len(_ContinuationHandler.bodies) == 1 else "Second answer"
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(
            json.dumps(
                {
                    "id": f"resp-{len(_ContinuationHandler.bodies)}",
                    "output": [
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": reply_text}],
                        }
                    ],
                }
            ).encode("utf-8")
        )

    def log_message(self, format: str, *args) -> None:
        return


class _StickySessionHandler(BaseHTTPRequestHandler):
    bodies: list[dict] = []
    session_headers: list[str | None] = []

    def do_POST(self) -> None:  # noqa: N802
        content_length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(content_length).decode("utf-8"))
        _StickySessionHandler.bodies.append(body)
        _StickySessionHandler.session_headers.append(self.headers.get("session_id"))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"id": f"resp-{len(_StickySessionHandler.bodies)}", "output_text": "ok"}).encode("utf-8"))

    def log_message(self, format: str, *args) -> None:
        return


class _RetryHandler(BaseHTTPRequestHandler):
    attempts = 0

    def do_POST(self) -> None:  # noqa: N802
        _RetryHandler.attempts += 1
        if _RetryHandler.attempts < 3:
            self.send_response(524)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"upstream timeout")
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"id": "resp-ok", "output_text": "Recovered draft"}).encode("utf-8"))

    def log_message(self, format: str, *args) -> None:
        return


class _DisconnectOnceHandler(BaseHTTPRequestHandler):
    attempts = 0

    def do_POST(self) -> None:  # noqa: N802
        _DisconnectOnceHandler.attempts += 1
        if _DisconnectOnceHandler.attempts == 1:
            self.connection.shutdown(socket.SHUT_RDWR)
            self.connection.close()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"id": "resp-ok", "output_text": "Recovered after disconnect"}).encode("utf-8"))

    def log_message(self, format: str, *args) -> None:
        return


class _StreamErrorOnceHandler(BaseHTTPRequestHandler):
    attempts = 0

    def do_POST(self) -> None:  # noqa: N802
        _StreamErrorOnceHandler.attempts += 1
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        if _StreamErrorOnceHandler.attempts == 1:
            frames = [
                'event: response.created\ndata: {"type":"response.created","response":{"id":"resp-stream-error"}}\n\n',
                'event: error\ndata: {"type":"error","message":"stream_read_error"}\n\n',
                "data: [DONE]\n\n",
            ]
        else:
            frames = [
                'event: response.created\ndata: {"type":"response.created","response":{"id":"resp-stream-ok"}}\n\n',
                'event: response.output_text.delta\ndata: {"type":"response.output_text.delta","delta":"Recovered "}\n\n',
                'event: response.output_text.delta\ndata: {"type":"response.output_text.delta","delta":"stream"}\n\n',
                'event: response.completed\ndata: {"type":"response.completed","response":{"id":"resp-stream-ok","output":[{"type":"message","role":"assistant","content":[{"type":"output_text","text":"Recovered stream"}]}]}}\n\n',
                "data: [DONE]\n\n",
            ]
        for frame in frames:
            self.wfile.write(frame.encode("utf-8"))
            self.wfile.flush()

    def log_message(self, format: str, *args) -> None:
        return


class _AnthropicHandler(BaseHTTPRequestHandler):
    bodies: list[dict] = []
    session_headers: list[str | None] = []

    def do_POST(self) -> None:  # noqa: N802
        content_length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(content_length).decode("utf-8"))
        _AnthropicHandler.bodies.append(body)
        _AnthropicHandler.session_headers.append(self.headers.get("session_id"))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(
            json.dumps(
                {
                    "id": "msg-ok",
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Anthropic OK"}],
                    "stop_reason": "end_turn",
                }
            ).encode("utf-8")
        )

    def log_message(self, format: str, *args) -> None:
        return


class _AnthropicStreamHandler(BaseHTTPRequestHandler):
    bodies: list[dict] = []

    def do_POST(self) -> None:  # noqa: N802
        content_length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(content_length).decode("utf-8"))
        _AnthropicStreamHandler.bodies.append(body)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        frames = [
            'event: message_start\ndata: {"type":"message_start","message":{"id":"msg-stream","role":"assistant","content":[]}}\n\n',
            'event: content_block_delta\ndata: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Anthropic "}}\n\n',
            'event: content_block_delta\ndata: {"type":"content_block_delta","delta":{"type":"text_delta","text":"stream"}}\n\n',
            'event: message_stop\ndata: {"type":"message_stop"}\n\n',
        ]
        for frame in frames:
            self.wfile.write(frame.encode("utf-8"))
            self.wfile.flush()

    def log_message(self, format: str, *args) -> None:
        return


class _AnthropicNonJsonBodyHandler(BaseHTTPRequestHandler):
    bodies: list[dict] = []

    def do_POST(self) -> None:  # noqa: N802
        content_length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(content_length).decode("utf-8"))
        _AnthropicNonJsonBodyHandler.bodies.append(body)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b"temporary upstream body")

    def log_message(self, format: str, *args) -> None:
        return


class ClientTests(unittest.TestCase):
    def test_build_responses_payload_uses_flagship_advanced_settings(self) -> None:
        provider = ProviderConfig(
            base_url="https://sub2api.example.com",
            wire_api="responses",
            api_key="secret",
            model="gpt-test",
            review_model="gpt-test",
            reasoning_effort="high",
            service_tier="default",
            flagship_reasoning_effort="xhigh",
            flagship_service_tier="fast",
            light_reasoning_effort="medium",
            light_service_tier="flex",
        )
        client = OpenAICompatibleClient(provider)

        payload = client._build_payload(
            "system",
            "user",
            RequestOptions(model="gpt-test", temperature=0.3, provider_tier="flagship"),
            session=None,
            stream=False,
        )

        self.assertEqual(payload["reasoning"], {"effort": "xhigh"})
        self.assertEqual(payload["service_tier"], "priority")

    def test_build_chat_payload_uses_light_advanced_settings(self) -> None:
        provider = ProviderConfig(
            base_url="https://relay.example.com",
            wire_api="chat-completions",
            api_key="secret",
            model="gpt-test",
            review_model="gpt-test",
            reasoning_effort="high",
            service_tier="default",
            flagship_reasoning_effort="xhigh",
            flagship_service_tier="fast",
            light_reasoning_effort="medium",
            light_service_tier="flex",
        )
        client = OpenAICompatibleClient(provider)

        payload = client._build_payload(
            "system",
            "user",
            RequestOptions(model="gpt-test", temperature=0.3, provider_tier="light"),
            session=None,
            stream=False,
        )

        self.assertEqual(payload["reasoning_effort"], "medium")
        self.assertEqual(payload["service_tier"], "flex")

    def test_build_payload_falls_back_to_shared_advanced_settings_when_tier_specific_is_missing(self) -> None:
        provider = ProviderConfig(
            base_url="https://sub2api.example.com",
            wire_api="responses",
            api_key="secret",
            model="gpt-test",
            review_model="gpt-test",
            reasoning_effort="xhigh",
            service_tier="fast",
        )
        client = OpenAICompatibleClient(provider)

        payload = client._build_payload(
            "system",
            "user",
            RequestOptions(model="gpt-test", temperature=0.3, provider_tier="light"),
            session=None,
            stream=False,
        )

        self.assertEqual(payload["reasoning"], {"effort": "xhigh"})
        self.assertEqual(payload["service_tier"], "priority")

    def test_build_payload_keeps_fast_for_generic_gateway(self) -> None:
        provider = ProviderConfig(
            base_url="https://relay.example.com",
            wire_api="responses",
            api_key="secret",
            model="gpt-test",
            review_model="gpt-test",
            service_tier="fast",
        )
        client = OpenAICompatibleClient(provider)

        payload = client._build_payload(
            "system",
            "user",
            RequestOptions(model="gpt-test", temperature=0.3, provider_tier="flagship"),
            session=None,
            stream=False,
        )

        self.assertEqual(payload["service_tier"], "fast")

    def test_build_payload_uses_explicit_gateway_profile_for_fast_mapping(self) -> None:
        provider = ProviderConfig(
            base_url="https://relay.example.com",
            wire_api="responses",
            api_key="secret",
            model="gpt-test",
            review_model="gpt-test",
            gateway_profile="sub2api",
            service_tier="fast",
        )
        client = OpenAICompatibleClient(provider)

        payload = client._build_payload(
            "system",
            "user",
            RequestOptions(model="gpt-test", temperature=0.3, provider_tier="flagship"),
            session=None,
            stream=False,
        )

        self.assertEqual(payload["service_tier"], "priority")

    def test_generate_json_does_not_add_outer_retries_for_model_errors(self) -> None:
        provider = ProviderConfig(
            base_url="https://relay.example.com",
            wire_api="responses",
            api_key="secret",
            model="gpt-test",
            review_model="gpt-test",
        )

        class RecordingClient(OpenAICompatibleClient):
            def __init__(self) -> None:
                super().__init__(provider, timeout_seconds=5, retries=2)
                self.calls = 0

            def _execute_request(self, *args, **kwargs):  # type: ignore[override]
                self.calls += 1
                raise ModelClientError("timeout")

        client = RecordingClient()

        with self.assertRaises(ModelClientError):
            client.generate_json("system", "user")

        self.assertEqual(client.calls, 1)

    def test_generate_json_retries_on_parse_failure_only(self) -> None:
        provider = ProviderConfig(
            base_url="https://relay.example.com",
            wire_api="responses",
            api_key="secret",
            model="gpt-test",
            review_model="gpt-test",
        )

        class RecordingClient(OpenAICompatibleClient):
            def __init__(self) -> None:
                super().__init__(provider, timeout_seconds=5, retries=2)
                self.calls = 0

            def _execute_request(self, *args, **kwargs):  # type: ignore[override]
                self.calls += 1
                if self.calls == 1:
                    return ResponseResult(text="not-json")
                return ResponseResult(text='{"ok": true}')

        client = RecordingClient()

        payload = client.generate_json("system", "user")

        self.assertEqual(payload, {"ok": True})
        self.assertEqual(client.calls, 2)

    def test_generate_json_exposes_raw_text_on_terminal_parse_failure(self) -> None:
        provider = ProviderConfig(
            base_url="https://relay.example.com",
            wire_api="responses",
            api_key="secret",
            model="gpt-test",
            review_model="gpt-test",
        )

        class RecordingClient(OpenAICompatibleClient):
            def __init__(self) -> None:
                super().__init__(provider, timeout_seconds=5, retries=0)

            def _execute_request(self, *args, **kwargs):  # type: ignore[override]
                return ResponseResult(text="not-json")

        client = RecordingClient()

        with self.assertRaises(JsonParseModelClientError) as ctx:
            client.generate_json("system", "user")

        self.assertEqual(ctx.exception.raw_text, "not-json")

    def test_client_reports_request_time_budget(self) -> None:
        provider = ProviderConfig(
            base_url="https://relay.example.com",
            wire_api="responses",
            api_key="secret",
            model="gpt-test",
            review_model="gpt-test",
        )
        client = OpenAICompatibleClient(provider, timeout_seconds=180, retries=2)

        self.assertEqual(client.request_time_budget_seconds(), 543)

    def test_responses_client_falls_back_to_v1_endpoint(self) -> None:
        _FallbackHandler.requests = []
        with _serve(_FallbackHandler) as server:
            provider = ProviderConfig(
                base_url=f"http://127.0.0.1:{server.server_port}",
                wire_api="responses",
                api_key="secret",
                model="gpt-test",
                review_model="gpt-test",
            )
            client = OpenAICompatibleClient(provider, timeout_seconds=5)
            payload = client.generate_json("system", "user")

            self.assertEqual(payload["ok"], True)
            self.assertGreaterEqual(len(_FallbackHandler.requests), 2)
            self.assertEqual(_FallbackHandler.requests[0], "/responses")
            self.assertEqual(_FallbackHandler.requests[-1], "/v1/responses")

    def test_streaming_responses_accumulates_deltas(self) -> None:
        _StreamHandler.bodies = []
        with _serve(_StreamHandler) as server:
            provider = ProviderConfig(
                base_url=f"http://127.0.0.1:{server.server_port}",
                wire_api="responses",
                api_key="secret",
                model="gpt-test",
                review_model="gpt-test",
            )
            client = OpenAICompatibleClient(provider, timeout_seconds=5)
            deltas: list[str] = []
            text = client.generate_text(
                "system",
                "user",
                stream=True,
                stream_observer=deltas.append,
                session_id="writer",
            )

            self.assertEqual(text, "Hello world")
            self.assertEqual(deltas, ["Hello ", "world"])
            self.assertTrue(_StreamHandler.bodies[0]["stream"])

    def test_streaming_responses_can_recover_text_from_output_item_done(self) -> None:
        _StreamOutputItemDoneHandler.bodies = []
        with _serve(_StreamOutputItemDoneHandler) as server:
            provider = ProviderConfig(
                base_url=f"http://127.0.0.1:{server.server_port}",
                wire_api="responses",
                api_key="secret",
                model="gpt-test",
                review_model="gpt-test",
            )
            client = OpenAICompatibleClient(provider, timeout_seconds=5)

            text = client.generate_text("system", "user", stream=True, session_id="writer")

            self.assertEqual(text, "Recovered from item")
            self.assertTrue(_StreamOutputItemDoneHandler.bodies[0]["stream"])

    def test_responses_client_extracts_text_from_wrapped_response_payload(self) -> None:
        with _serve(_WrappedResponsesHandler) as server:
            provider = ProviderConfig(
                base_url=f"http://127.0.0.1:{server.server_port}",
                wire_api="responses",
                api_key="secret",
                model="gpt-test",
                review_model="gpt-test",
            )
            client = OpenAICompatibleClient(provider, timeout_seconds=5)

            text = client.generate_text("system", "user")

            self.assertEqual(text, "Wrapped OK")

    def test_session_history_replays_prior_assistant_output(self) -> None:
        _SessionHandler.bodies = []
        with _serve(_SessionHandler) as server:
            provider = ProviderConfig(
                base_url=f"http://127.0.0.1:{server.server_port}",
                wire_api="responses",
                api_key="secret",
                model="gpt-test",
                review_model="gpt-test",
            )
            client = OpenAICompatibleClient(provider, timeout_seconds=5)

            client.generate_text("system prompt", "first user turn", session_id="writer")
            client.generate_text("system prompt", "second user turn", session_id="writer")

            self.assertEqual(len(_SessionHandler.bodies), 2)
            second_input = _SessionHandler.bodies[1]["input"]
            self.assertEqual(second_input[0]["role"], "system")
            self.assertEqual(second_input[1]["role"], "user")
            self.assertEqual(second_input[1]["content"][0]["text"], "first user turn")
            self.assertEqual(second_input[2]["role"], "assistant")
            self.assertEqual(second_input[2]["content"][0]["type"], "output_text")
            self.assertEqual(second_input[2]["content"][0]["text"], "First answer")
            self.assertEqual(second_input[3]["role"], "user")
            self.assertEqual(second_input[3]["content"][0]["text"], "second user turn")

    def test_previous_response_id_continuation_uses_provider_chain(self) -> None:
        _ContinuationHandler.bodies = []
        with _serve(_ContinuationHandler) as server:
            provider = ProviderConfig(
                base_url=f"http://127.0.0.1:{server.server_port}",
                wire_api="responses",
                api_key="secret",
                model="gpt-test",
                review_model="gpt-test",
                continuation_mode="previous_response_id",
            )
            client = OpenAICompatibleClient(provider, timeout_seconds=5)

            client.generate_text("system prompt", "first user turn", session_id="writer")
            client.generate_text("system prompt", "second user turn", session_id="writer")

            self.assertEqual(len(_ContinuationHandler.bodies), 2)
            first_input = _ContinuationHandler.bodies[0]["input"]
            self.assertEqual(first_input[0]["role"], "system")
            self.assertEqual(first_input[-1]["content"][0]["text"], "first user turn")
            second_body = _ContinuationHandler.bodies[1]
            self.assertEqual(second_body["previous_response_id"], "resp-1")
            self.assertEqual(len(second_body["input"]), 1)
            self.assertEqual(second_body["input"][0]["role"], "user")
            self.assertEqual(second_body["input"][0]["content"][0]["text"], "second user turn")

    def test_hybrid_continuation_sends_previous_response_id_and_replay_history(self) -> None:
        _ContinuationHandler.bodies = []
        with _serve(_ContinuationHandler) as server:
            provider = ProviderConfig(
                base_url=f"http://127.0.0.1:{server.server_port}",
                wire_api="responses",
                api_key="secret",
                model="gpt-test",
                review_model="gpt-test",
                continuation_mode="hybrid",
            )
            client = OpenAICompatibleClient(provider, timeout_seconds=5)

            client.generate_text("system prompt", "first user turn", session_id="writer")
            client.generate_text("system prompt", "second user turn", session_id="writer")

            self.assertEqual(len(_ContinuationHandler.bodies), 2)
            second_body = _ContinuationHandler.bodies[1]
            self.assertEqual(second_body["previous_response_id"], "resp-1")
            second_input = second_body["input"]
            self.assertEqual(second_input[0]["role"], "system")
            self.assertEqual(second_input[1]["role"], "user")
            self.assertEqual(second_input[1]["content"][0]["text"], "first user turn")
            self.assertEqual(second_input[2]["role"], "assistant")
            self.assertEqual(second_input[2]["content"][0]["type"], "output_text")
            self.assertEqual(second_input[2]["content"][0]["text"], "First answer")
            self.assertEqual(second_input[3]["role"], "user")
            self.assertEqual(second_input[3]["content"][0]["text"], "second user turn")

    def test_client_sends_stable_sticky_session_header_per_namespace(self) -> None:
        _StickySessionHandler.bodies = []
        _StickySessionHandler.session_headers = []
        with _serve(_StickySessionHandler) as server:
            provider = ProviderConfig(
                base_url=f"http://127.0.0.1:{server.server_port}",
                wire_api="responses",
                api_key="secret",
                model="gpt-test",
                review_model="gpt-test",
            )
            client = OpenAICompatibleClient(provider, timeout_seconds=5, routing_namespace="runs/demo-book-123")

            client.generate_text("system prompt", "first user turn", session_id="writer-v1")
            client.generate_text("system prompt", "second user turn", session_id="writer-v1")
            client.generate_text("system prompt", "review pass", session_id="reviewer")

            self.assertEqual(len(_StickySessionHandler.session_headers), 3)
            first_header = _StickySessionHandler.session_headers[0]
            second_header = _StickySessionHandler.session_headers[1]
            third_header = _StickySessionHandler.session_headers[2]
            self.assertIsNotNone(first_header)
            self.assertEqual(first_header, second_header)
            self.assertNotEqual(first_header, third_header)
            self.assertIn("writer-v1", first_header or "")
            self.assertNotIn("_sagaquill_session_id", _StickySessionHandler.bodies[0])

    def test_client_retries_transient_524_for_text_generation(self) -> None:
        _RetryHandler.attempts = 0
        with _serve(_RetryHandler) as server:
            provider = ProviderConfig(
                base_url=f"http://127.0.0.1:{server.server_port}",
                wire_api="responses",
                api_key="secret",
                model="gpt-test",
                review_model="gpt-test",
            )
            client = OpenAICompatibleClient(provider, timeout_seconds=5, retries=2)
            text = client.generate_text("system", "user")

            self.assertEqual(text, "Recovered draft")
            self.assertEqual(_RetryHandler.attempts, 3)

    def test_client_retries_remote_disconnect_for_text_generation(self) -> None:
        _DisconnectOnceHandler.attempts = 0
        with _serve(_DisconnectOnceHandler) as server:
            provider = ProviderConfig(
                base_url=f"http://127.0.0.1:{server.server_port}",
                wire_api="responses",
                api_key="secret",
                model="gpt-test",
                review_model="gpt-test",
            )
            client = OpenAICompatibleClient(provider, timeout_seconds=5, retries=1)
            text = client.generate_text("system", "user", stream=True, stream_observer=lambda _delta: None)

            self.assertEqual(text, "Recovered after disconnect")
            self.assertGreaterEqual(_DisconnectOnceHandler.attempts, 2)

    def test_client_retries_stream_error_event_for_text_generation(self) -> None:
        _StreamErrorOnceHandler.attempts = 0
        with _serve(_StreamErrorOnceHandler) as server:
            provider = ProviderConfig(
                base_url=f"http://127.0.0.1:{server.server_port}",
                wire_api="responses",
                api_key="secret",
                model="gpt-test",
                review_model="gpt-test",
            )
            client = OpenAICompatibleClient(provider, timeout_seconds=5, retries=1)
            text = client.generate_text("system", "user", stream=True, stream_observer=lambda _delta: None)

            self.assertEqual(text, "Recovered stream")
            self.assertEqual(_StreamErrorOnceHandler.attempts, 2)

    def test_anthropic_messages_client_extracts_text(self) -> None:
        _AnthropicHandler.bodies = []
        _AnthropicHandler.session_headers = []
        with _serve(_AnthropicHandler) as server:
            provider = ProviderConfig(
                base_url=f"http://127.0.0.1:{server.server_port}",
                wire_api="anthropic-messages",
                api_key="secret",
                model="claude-test",
                review_model="claude-test",
            )
            client = OpenAICompatibleClient(provider, timeout_seconds=5)
            text = client.generate_text("system prompt", "user turn", session_id="writer")

            self.assertEqual(text, "Anthropic OK")
            body = _AnthropicHandler.bodies[0]
            self.assertEqual(body["model"], "claude-test")
            self.assertEqual(body["system"], "system prompt")
            self.assertEqual(body["messages"][-1]["content"], "user turn")
            self.assertEqual(body["max_tokens"], 4096)
            self.assertIsNotNone(_AnthropicHandler.session_headers[0])

    def test_anthropic_messages_streaming_accumulates_deltas(self) -> None:
        _AnthropicStreamHandler.bodies = []
        with _serve(_AnthropicStreamHandler) as server:
            provider = ProviderConfig(
                base_url=f"http://127.0.0.1:{server.server_port}",
                wire_api="anthropic-messages",
                api_key="secret",
                model="claude-test",
                review_model="claude-test",
            )
            client = OpenAICompatibleClient(provider, timeout_seconds=5)
            deltas: list[str] = []
            text = client.generate_text("system", "user", stream=True, stream_observer=deltas.append)

            self.assertEqual(text, "Anthropic stream")
            self.assertEqual(deltas, ["Anthropic ", "stream"])
            self.assertTrue(_AnthropicStreamHandler.bodies[0]["stream"])

    def test_anthropic_messages_non_json_body_surfaces_as_parse_recoverable_text(self) -> None:
        _AnthropicNonJsonBodyHandler.bodies = []
        with _serve(_AnthropicNonJsonBodyHandler) as server:
            provider = ProviderConfig(
                base_url=f"http://127.0.0.1:{server.server_port}",
                wire_api="anthropic-messages",
                api_key="secret",
                model="claude-test",
                review_model="claude-test",
            )
            client = OpenAICompatibleClient(provider, timeout_seconds=5, retries=0)

            with self.assertRaises(JsonParseModelClientError) as ctx:
                client.generate_json("system", "user", stream=True)

            self.assertEqual(ctx.exception.raw_text, "temporary upstream body")
            self.assertTrue(_AnthropicNonJsonBodyHandler.bodies[0]["stream"])

    def test_anthropic_messages_non_stream_non_json_body_surfaces_as_parse_recoverable_text(self) -> None:
        _AnthropicNonJsonBodyHandler.bodies = []
        with _serve(_AnthropicNonJsonBodyHandler) as server:
            provider = ProviderConfig(
                base_url=f"http://127.0.0.1:{server.server_port}",
                wire_api="anthropic-messages",
                api_key="secret",
                model="claude-test",
                review_model="claude-test",
            )
            client = OpenAICompatibleClient(provider, timeout_seconds=5, retries=0)

            with self.assertRaises(JsonParseModelClientError) as ctx:
                client.generate_json("system", "user", stream=False)

            self.assertEqual(ctx.exception.raw_text, "temporary upstream body")
            self.assertNotIn("stream", _AnthropicNonJsonBodyHandler.bodies[0])

    def test_anthropic_messages_client_prefers_v1_messages_endpoint(self) -> None:
        provider = ProviderConfig(
            base_url="https://relay.example.com",
            wire_api="anthropic-messages",
            api_key="secret",
            model="claude-test",
            review_model="claude-test",
        )
        client = OpenAICompatibleClient(provider)

        self.assertEqual(
            client._candidate_urls(),
            [
                "https://relay.example.com/v1/messages",
                "https://relay.example.com/messages",
            ],
        )


class _serve:
    def __init__(self, handler: type[BaseHTTPRequestHandler]) -> None:
        self.server = HTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> HTTPServer:
        self.thread.start()
        return self.server

    def __exit__(self, exc_type, exc, tb) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
