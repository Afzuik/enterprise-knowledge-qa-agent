"""A small, non-retrying Chat Completions adapter.

The model emits JSON actions, not native function-call messages. All HTTP
requests are explicit; importing this module never contacts a service.
"""

import json
import math
import os
import socket
import urllib.error
import urllib.parse
import urllib.request


class ModelError(Exception):
    """Sanitized operational error suitable for a public execution trace."""

    def __init__(self, code, message, hint=None):
        super().__init__(message)
        self.code = code
        allowed_hints = {"invalid_json", "missing_action_fields", "invalid_envelope",
                         "non_text_content", "response_too_large"}
        self.hint = hint if hint in allowed_hints else None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward Authorization (or the prompt) to a redirect target.
        return None


class LiveModel:
    mode = "live"

    def __init__(self, api_key, model, base_url="https://api.openai.com/v1",
                 timeout=30, max_response_bytes=1024 * 1024):
        if not isinstance(api_key, str) or not api_key.strip():
            raise ModelError("config_missing", "缺少 LLM_API_KEY（或 OPENAI_API_KEY）。")
        if not isinstance(model, str) or not model.strip():
            raise ModelError("config_missing", "缺少 LLM_MODEL（或 OPENAI_MODEL）。")
        if "\n" in api_key or "\r" in api_key:
            raise ModelError("config_invalid", "API Key 配置格式无效。")
        try:
            if not isinstance(base_url, str) or not base_url.strip():
                raise ValueError()
            parsed = urllib.parse.urlsplit(base_url.strip())
            local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
            if (not parsed.hostname or parsed.username is not None
                    or parsed.password is not None or parsed.query or parsed.fragment
                    or parsed.scheme not in {"https", "http"}
                    or (parsed.scheme == "http" and not local)):
                raise ValueError()
            # Force validation of malformed port specifications here.
            _ = parsed.port
            if any(ord(char) <= 32 for char in base_url):
                raise ValueError()
        except (TypeError, ValueError):
            raise ModelError("config_invalid", "模型接口必须是无凭据、查询参数或片段的 HTTPS 基础 URL；本机测试允许 HTTP。") from None
        if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
                or not math.isfinite(timeout) or timeout <= 0):
            raise ModelError("config_invalid", "模型请求超时必须是正数。")
        if (type(max_response_bytes) is not int or max_response_bytes <= 0):
            raise ModelError("config_invalid", "模型响应大小限制必须是正整数。")
        self._api_key = api_key.strip()
        self.name = model.strip()
        self._endpoint = base_url.strip().rstrip("/") + "/chat/completions"
        self.timeout = timeout
        self.max_response_bytes = max_response_bytes
        self._opener = urllib.request.build_opener(_NoRedirect())

    @classmethod
    def from_env(cls, timeout=30):
        def setting(primary, fallback, default=None):
            return os.environ.get(primary) or os.environ.get(fallback) or default

        return cls(
            api_key=setting("LLM_API_KEY", "OPENAI_API_KEY"),
            model=setting("LLM_MODEL", "OPENAI_MODEL"),
            base_url=setting("LLM_BASE_URL", "OPENAI_BASE_URL", "https://api.openai.com/v1"),
            timeout=timeout,
        )

    def decide(self, messages):
        if not isinstance(messages, list) or not messages:
            raise ModelError("invalid_request", "模型消息必须是非空列表。")
        try:
            body = json.dumps({
                "model": self.name,
                "messages": messages,
                "response_format": {"type": "json_object"},
                "store": False,
            }, ensure_ascii=False, allow_nan=False).encode("utf-8")
        except (TypeError, ValueError):
            raise ModelError("invalid_request", "模型消息无法序列化为 JSON。") from None
        request = urllib.request.Request(
            self._endpoint, data=body, method="POST", headers={
                "Authorization": "Bearer " + self._api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                raw = response.read(self.max_response_bytes + 1)
        except urllib.error.HTTPError as error:
            status = error.code
            error.close()
            raise ModelError("http_error", "模型接口返回 HTTP {}；未自动重试。".format(status)) from None
        except (socket.timeout, TimeoutError):
            raise ModelError("model_timeout", "模型请求超时；未自动重试。") from None
        except urllib.error.URLError as error:
            if isinstance(error.reason, (socket.timeout, TimeoutError)):
                raise ModelError("model_timeout", "模型请求超时；未自动重试。") from None
            raise ModelError("network_error", "模型网络请求失败；未自动重试。") from None
        except (OSError, ValueError):
            raise ModelError("network_error", "模型请求无法完成；未自动重试。") from None
        if len(raw) > self.max_response_bytes:
            raise ModelError("invalid_model_output", "模型响应超过大小限制。", "response_too_large")
        try:
            envelope = json.loads(raw.decode("utf-8"))
            content = envelope["choices"][0]["message"]["content"]
        except (UnicodeDecodeError, ValueError, TypeError, KeyError, IndexError):
            raise ModelError("invalid_model_output", "模型响应外层格式无效。", "invalid_envelope") from None
        if not isinstance(content, str):
            raise ModelError("invalid_model_output", "模型响应内容不是文本。", "non_text_content")
        try:
            action = json.loads(content)
        except ValueError:
            raise ModelError("invalid_model_output", "模型内容不是有效 JSON。", "invalid_json") from None
        if (not isinstance(action, dict)
                or not isinstance(action.get("action"), str)
                or not isinstance(action.get("arguments"), dict)
                or not isinstance(action.get("decision_summary"), str)):
            raise ModelError("invalid_model_output", "模型动作缺少必需字段或字段类型不符。", "missing_action_fields")
        return action
