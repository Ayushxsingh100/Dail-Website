"""The Gemini provider for DAIL's provider seam (PLAN §3.5; B work package §3.3; D-15).

``GeminiProvider`` implements ``llm.adapter.provider.LLMProvider``: ``name = "gemini"`` and
``generate(call: ProviderCall) -> ProviderReply``, modelled on DAIL's ``OllamaProvider``. It only
moves text: DAIL's ``Generator`` builds the prompt and the records, DAIL's parser and patch
validator judge the reply. Standard library only (``urllib.request``).

Documented API used (Google's official Gemini API documentation, read on 26 Nov 2026; URLs in
``docs/DECISIONS.md``, D-15):

* ``POST {endpoint}/v1beta/models/{model}:generateContent`` with ``systemInstruction``,
  ``contents`` (one ``user`` turn) and ``generationConfig`` (``temperature``, ``topP``, ``seed``,
  ``maxOutputTokens``, ``responseMimeType: "application/json"`` and ``responseJsonSchema``: DAIL's
  response schema as a generation hint; DAIL's parser stays the judge). The reply text is
  ``candidates[0].content.parts[].text``; ``usageMetadata`` gives the token counts and
  ``modelVersion`` the model that answered.
* ``GET {endpoint}/v1beta/models/{model}`` (models.get) confirms the configured model exists and
  supports ``generateContent`` before any generation (``check_model``).

**The key** is read only from ``GEMINI_API_KEY`` (``from_environment``) and sent only in the
``x-goog-api-key`` header, never in a URL. It never appears in an error message: every failure is
a fixed one-line reason with at most an HTTP status. Redirects are refused, so the header is never
sent to another host. The endpoint must be ``https``; plain ``http`` is accepted only at a loopback
address (the tests' local fake server).

**Failure classes** (DAIL §24): missing key, HTTP 400/401/403/404 -> UNSUPPORTED (the request
cannot be served; retrying would not help); HTTP 429 (the free-tier limit) -> RATE_LIMIT; a
time-out -> TIMEOUT; no network, 5xx -> TRANSIENT_ERROR; a reply that is not JSON, or has no
candidate text -> INVALID_OUTPUT.
"""

from __future__ import annotations

import ipaddress
import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from typing import Any, Final

from llm.adapter.provider import ProviderCall, ProviderError, ProviderReply
from llm.schemas.records import FailureClass

F = FailureClass
KEY_VARIABLE: Final = "GEMINI_API_KEY"
KEY_HEADER: Final = "x-goog-api-key"
NO_KEY: Final = f"{KEY_VARIABLE} is not set: AI mode unavailable; typed-patch mode still works"
_LOOPBACK_NAMES: Final = frozenset({"localhost"})


def _checked_endpoint(endpoint: str) -> str:
    parts = urllib.parse.urlsplit(endpoint)
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("Gemini endpoint: no user, query or fragment is allowed")
    if parts.path not in ("", "/"):
        raise ValueError("Gemini endpoint: no path is allowed")
    host = parts.hostname or ""
    if parts.scheme == "https" and host:
        return f"https://{parts.netloc}"
    if parts.scheme == "http":
        loopback = host in _LOOPBACK_NAMES
        if not loopback:
            try:
                loopback = ipaddress.ip_address(host).is_loopback
            except ValueError:
                loopback = False
        if loopback:
            return f"http://{parts.netloc}"
    raise ValueError("Gemini endpoint: https only (plain http only at a loopback address)")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        raise urllib.error.HTTPError(req.full_url, code, "redirect refused", headers, fp)


def _status_failure(status: int) -> tuple[FailureClass, str]:
    if status == 429:
        return F.RATE_LIMIT, "Gemini free-tier rate limit reached (HTTP 429); wait and try again"
    if status in (401, 403):
        return F.UNSUPPORTED, f"Gemini refused the API key (HTTP {status})"
    if status == 404:
        return F.UNSUPPORTED, "Gemini does not know the configured model (HTTP 404)"
    if 300 <= status < 400:
        return F.UNSUPPORTED, f"Gemini answered with a redirect (HTTP {status}); refused"
    if status >= 500:
        return F.TRANSIENT_ERROR, f"Gemini is unavailable (HTTP {status})"
    return F.UNSUPPORTED, f"Gemini refused the request (HTTP {status})"


class GeminiProvider:
    name = "gemini"

    def __init__(self, *, api_key: str, model: str, endpoint: str, api_version: str = "v1beta") -> None:
        self._key = api_key.strip()
        self.model = model
        self.endpoint = _checked_endpoint(endpoint)
        self.api_version = api_version
        self.model_facts: dict[str, Any] | None = None
        self.model_versions: list[str] = []  # ``modelVersion`` of every reply, for the trace
        self._opener = urllib.request.build_opener(_NoRedirect())

    @classmethod
    def from_environment(
        cls, environ: Mapping[str, str], *, model: str, endpoint: str, api_version: str = "v1beta"
    ) -> GeminiProvider:
        return cls(
            api_key=environ.get(KEY_VARIABLE, ""), model=model, endpoint=endpoint, api_version=api_version
        )

    @property
    def has_key(self) -> bool:
        return bool(self._key)

    def __repr__(self) -> str:  # never shows the key
        return f"GeminiProvider(model={self.model!r}, endpoint={self.endpoint!r})"

    # --- HTTP -----------------------------------------------------------------------------------

    def _url(self, path: str) -> str:
        return f"{self.endpoint}/{self.api_version}/{path}"

    def _http(self, method: str, path: str, body: Any, timeout: float) -> Any:
        if not self._key:
            raise ProviderError(F.UNSUPPORTED, NO_KEY)
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            self._url(path),
            data=data,
            method=method,
            headers={"Content-Type": "application/json", KEY_HEADER: self._key},
        )
        try:
            with self._opener.open(request, timeout=timeout) as answer:
                raw = answer.read()
        except urllib.error.HTTPError as error:
            failure, detail = _status_failure(error.code)
            error.close()
            raise ProviderError(failure, detail) from None
        except (TimeoutError, socket.timeout):
            raise ProviderError(F.TIMEOUT, f"no answer from Gemini within {timeout:g} s") from None
        except urllib.error.URLError as error:
            if isinstance(error.reason, TimeoutError | socket.timeout):
                raise ProviderError(F.TIMEOUT, f"no answer from Gemini within {timeout:g} s") from None
            raise ProviderError(
                F.TRANSIENT_ERROR, f"no network: cannot reach {urllib.parse.urlsplit(self.endpoint).hostname}"
            ) from None
        except (ConnectionError, OSError):
            raise ProviderError(
                F.TRANSIENT_ERROR, f"no network: the connection to {urllib.parse.urlsplit(self.endpoint).hostname} failed"
            ) from None
        try:
            return json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            raise ProviderError(F.INVALID_OUTPUT, "Gemini's reply is not JSON") from None

    # --- model check ----------------------------------------------------------------------------

    def check_model(self, timeout: float = 30.0) -> dict[str, Any]:
        """models.get: the configured model must exist and support ``generateContent``."""
        value = self._http("GET", f"models/{urllib.parse.quote(self.model, safe='-._')}", None, timeout)
        if not isinstance(value, dict) or not isinstance(value.get("name"), str):
            raise ProviderError(F.INVALID_OUTPUT, "Gemini's model description has no name")
        methods = value.get("supportedGenerationMethods") or []
        if "generateContent" not in methods:
            raise ProviderError(F.UNSUPPORTED, f"model {self.model} does not support generateContent")
        facts = {
            "name": value["name"],
            "version": value.get("version"),
            "display_name": value.get("displayName"),
            "input_token_limit": value.get("inputTokenLimit"),
            "output_token_limit": value.get("outputTokenLimit"),
        }
        self.model_facts = facts
        return facts

    # --- generation -----------------------------------------------------------------------------

    def generate(self, call: ProviderCall) -> ProviderReply:
        config = call.config
        generation: dict[str, Any] = {
            "temperature": config.temperature,
            "topP": config.top_p,
            "maxOutputTokens": config.max_output_tokens,
            "responseMimeType": "application/json",
            "responseJsonSchema": dict(call.response_schema),
        }
        if config.seed is not None:
            generation["seed"] = config.seed
        body = {
            "systemInstruction": {"parts": [{"text": call.system}]},
            "contents": [{"role": "user", "parts": [{"text": call.task}]}],
            "generationConfig": generation,
        }
        started = time.perf_counter()
        value = self._http(
            "POST",
            f"models/{urllib.parse.quote(config.model_name, safe='-._')}:generateContent",
            body,
            config.timeout_seconds,
        )
        latency = (time.perf_counter() - started) * 1000.0
        if not isinstance(value, dict):
            raise ProviderError(F.INVALID_OUTPUT, "Gemini's reply is not a JSON object")
        if isinstance(value.get("modelVersion"), str):
            self.model_versions.append(value["modelVersion"])
        candidates = value.get("candidates")
        first = candidates[0] if isinstance(candidates, list) and candidates else None
        content = first.get("content") if isinstance(first, dict) else None
        parts = content.get("parts") if isinstance(content, dict) else None
        texts = [
            p["text"]
            for p in (parts if isinstance(parts, list) else [])
            if isinstance(p, dict) and isinstance(p.get("text"), str) and not p.get("thought")
        ]
        if not texts:
            feedback = value.get("promptFeedback")
            blocked = feedback.get("blockReason") if isinstance(feedback, dict) else None
            finish = first.get("finishReason") if isinstance(first, dict) else None
            why = f"blockReason {blocked}" if blocked else f"finishReason {finish}"
            raise ProviderError(F.INVALID_OUTPUT, f"Gemini's reply has no candidate text ({why})")
        usage_raw = value.get("usageMetadata")
        usage = {
            name: usage_raw[key]
            for name, key in (("input", "promptTokenCount"), ("output", "candidatesTokenCount"))
            if isinstance(usage_raw, dict) and isinstance(usage_raw.get(key), int)
        }
        return ProviderReply(text="".join(texts), latency_ms=latency, token_usage=usage)
