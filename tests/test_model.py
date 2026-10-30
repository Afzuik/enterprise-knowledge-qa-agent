import io
import json
import os
import socket
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import MagicMock, patch
from http.server import BaseHTTPRequestHandler, HTTPServer

from knowledge_agent.model import LiveModel, ModelError, _NoRedirect
from knowledge_agent.prompts import SYSTEM_PROMPT


class LiveModelTests(unittest.TestCase):
    def setUp(self):
        self.model = LiveModel("secret-test-key", "test-model")
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT},
                         {"role": "user", "content": "报销期限？"}]

    def respond(self, content):
        raw = json.dumps({"choices": [{"message": {"content": content}}]}).encode()
        self.model._opener = MagicMock()
        self.model._opener.open.return_value.__enter__.return_value.read.return_value = raw

    def test_request_and_response_contract(self):
        action = {"action": "search_docs", "arguments": {"query": "报销", "top_k": 5},
                  "decision_summary": "先查制度。"}
        self.respond(json.dumps(action))
        self.assertEqual(self.model.decide(self.messages), action)
        call = self.model._opener.open.call_args
        request = call.args[0]
        self.assertEqual(request.full_url, "https://api.openai.com/v1/chat/completions")
        self.assertEqual(request.method, "POST")
        payload = json.loads(request.data)
        self.assertEqual(payload["messages"], self.messages)
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertFalse(payload["store"])
        self.assertNotIn("temperature", payload)
        self.assertEqual(call.kwargs["timeout"], 30)

    def test_env_defaults_and_fallback(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "fallback", "OPENAI_MODEL": "fallback-model"}, clear=True):
            model = LiveModel.from_env()
            self.assertEqual(model.name, "fallback-model")
            self.assertEqual(model.mode, "live")
        with patch.dict(os.environ, {"OPENAI_API_KEY": "fallback", "OPENAI_MODEL": "fallback-model",
                                    "LLM_API_KEY": "primary", "LLM_MODEL": "primary-model",
                                    "LLM_BASE_URL": "https://example.org/v1/"}, clear=True):
            model = LiveModel.from_env(timeout=7)
            self.assertEqual(model.name, "primary-model")
            self.assertEqual(model.timeout, 7)
            self.assertEqual(model._endpoint, "https://example.org/v1/chat/completions")

    def test_missing_configuration_does_not_fallback_to_mock(self):
        for env in ({}, {"LLM_API_KEY": "present"}, {"LLM_MODEL": "present"}):
            with self.subTest(env=env), patch.dict(os.environ, env, clear=True):
                with self.assertRaises(ModelError) as raised:
                    LiveModel.from_env()
                self.assertEqual(raised.exception.code, "config_missing")

    def test_rejects_unsafe_or_malformed_urls(self):
        urls = ["http://example.org/v1", "https://user:secret@example.org/v1",
                "https://example.org/v1?key=secret", "https://example.org/#secret",
                "file:///tmp/api", "https://example.org:bad", "https://example.org/\npath", ""]
        for url in urls:
            with self.subTest(url=url), self.assertRaises(ModelError) as raised:
                LiveModel("key", "model", url)
            self.assertEqual(raised.exception.code, "config_invalid")
            self.assertNotIn("secret", str(raised.exception))

    def test_allows_local_http(self):
        for url in ("http://127.0.0.1:9999/v1", "http://localhost/v1", "http://[::1]:9999/v1"):
            self.assertEqual(LiveModel("key", "model", url).mode, "live")

    def test_rejects_invalid_timeouts(self):
        for timeout in (0, -1, True, float("inf"), float("nan"), "30"):
            with self.subTest(timeout=timeout), self.assertRaises(ModelError):
                LiveModel("key", "model", timeout=timeout)

    def test_rejects_redirects(self):
        request = urllib.request.Request("https://example.org", headers={"Authorization": "Bearer private"})
        self.assertIsNone(_NoRedirect().redirect_request(request, None, 302, "Found", {}, "https://other.org"))

    def test_http_error_is_sanitized_and_not_retried(self):
        self.model._opener = MagicMock()
        self.model._opener.open.side_effect = urllib.error.HTTPError(
            "https://example.org/?secret-test-key", 401, "secret-test-key", {}, io.BytesIO(b"secret-test-key"))
        with self.assertRaises(ModelError) as raised:
            self.model.decide(self.messages)
        self.assertEqual(raised.exception.code, "http_error")
        self.assertIn("401", str(raised.exception))
        self.assertNotIn("secret-test-key", str(raised.exception))
        self.assertEqual(self.model._opener.open.call_count, 1)

    def test_network_errors_are_sanitized(self):
        self.model._opener = MagicMock()
        self.model._opener.open.side_effect = urllib.error.URLError("secret-test-key")
        with self.assertRaises(ModelError) as raised:
            self.model.decide(self.messages)
        self.assertEqual(raised.exception.code, "network_error")
        self.assertNotIn("secret-test-key", str(raised.exception))

    def test_timeouts_are_distinct(self):
        for error in (socket.timeout("private"), urllib.error.URLError(socket.timeout("private"))):
            self.model._opener = MagicMock()
            self.model._opener.open.side_effect = error
            with self.assertRaises(ModelError) as raised:
                self.model.decide(self.messages)
            self.assertEqual(raised.exception.code, "model_timeout")

    def test_invalid_content_does_not_leak_raw_text(self):
        contents = [None, "secret-test-key", "```json\n{}\n```", "[]", "{}",
                    '{"action":"finish","arguments":{},"decision_summary":123}']
        for content in contents:
            self.respond(content)
            with self.subTest(content=content), self.assertRaises(ModelError) as raised:
                self.model.decide(self.messages)
            self.assertEqual(raised.exception.code, "invalid_model_output")
            self.assertNotIn("secret-test-key", str(raised.exception))

    def test_response_size_is_bounded(self):
        self.model.max_response_bytes = 8
        self.respond("a" * 20)
        with self.assertRaises(ModelError) as raised:
            self.model.decide(self.messages)
        self.assertEqual(raised.exception.code, "invalid_model_output")
        self.assertEqual(raised.exception.hint, "response_too_large")
        response = self.model._opener.open.return_value.__enter__.return_value
        response.read.assert_called_once_with(9)

    def test_parse_hints_are_safe_and_specific(self):
        for content, hint in ((None, "non_text_content"), ("private-marker", "invalid_json"),
                              ("{}", "missing_action_fields"), ("[]", "missing_action_fields")):
            self.respond(content)
            with self.subTest(hint=hint), self.assertRaises(ModelError) as raised:
                self.model.decide(self.messages)
            self.assertEqual(raised.exception.hint, hint)
            self.assertNotIn("private-marker", str(raised.exception))
        self.respond("{}")
        self.model._opener.open.return_value.__enter__.return_value.read.return_value = b'{"error":"private-marker"}'
        with self.assertRaises(ModelError) as raised:
            self.model.decide(self.messages)
        self.assertEqual(raised.exception.hint, "invalid_envelope")
        self.assertIsNone(ModelError("x", "safe", "private-marker").hint)

    def test_invalid_input_is_distinct(self):
        for messages in ([], None, [{"content": object()}]):
            with self.subTest(messages=messages), self.assertRaises(ModelError) as raised:
                self.model.decide(messages)
            self.assertEqual(raised.exception.code, "invalid_request")


class LocalTransportTests(unittest.TestCase):
    """Real localhost HTTP only; this is not evidence of live model quality."""

    def test_http_roundtrip_and_redirect_block(self):
        requests = []
        action = {"action": "search_docs", "arguments": {"query": "报销", "top_k": 5},
                  "decision_summary": "读取相关资料。"}

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                requests.append((self.path, self.headers.get("Authorization"), json.loads(body)))
                if self.path.startswith("/redirect/"):
                    self.send_response(302)
                    self.send_header("Location", "/capture")
                    self.end_headers()
                    return
                payload = json.dumps({"choices": [{"message": {"content": json.dumps(action)}}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_GET(self):
                requests.append((self.path, self.headers.get("Authorization"), None))
                self.send_response(200)
                self.end_headers()

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = "http://127.0.0.1:{}".format(server.server_port)
        try:
            model = LiveModel("local-test-only", "local-fixture", base + "/v1")
            messages = [{"role": "user", "content": "JSON 动作：报销期限？"}]
            self.assertEqual(model.decide(messages), action)
            self.assertEqual(requests[0][0], "/v1/chat/completions")
            self.assertEqual(requests[0][1], "Bearer local-test-only")
            self.assertEqual(requests[0][2]["messages"], messages)
            redirected = LiveModel("local-test-only", "local-fixture", base + "/redirect")
            with self.assertRaises(ModelError) as raised:
                redirected.decide(messages)
            self.assertEqual(raised.exception.code, "http_error")
            self.assertEqual([request[0] for request in requests],
                             ["/v1/chat/completions", "/redirect/chat/completions"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
