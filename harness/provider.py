"""OpenAI-compatible /v1/chat/completions client.

Works against llama.cpp's server, vLLM, Ollama, LM Studio, or any hosted
endpoint. No streaming: the harness logs completed turns, not tokens.

What it smooths over, because servers differ:
  - URL given with or without a trailing /v1
  - tool calls without ids (llama.cpp with some templates): ids are assigned
    so tool results can be matched back
  - `arguments` returned as an object instead of a JSON string
  - `content: null` alongside tool calls: sent back as "" (some chat
    templates break on null)
  - reasoning text (`reasoning_content` / `reasoning`): returned separately so
    it can be logged, and not sent back into the conversation

What it deliberately does NOT do: parse tool calls out of plain text. A model
that writes a tool call as prose has not made a tool call, and hiding that
would hide exactly the wiring failure preflight exists to catch.

Retries: connection errors, timeouts, 429 and 5xx are retried with backoff.
Each retry is reported through `on_retry` so the episode log records it.
"""
import json
import os
import time

import requests

DEFAULT_URL = os.getenv("MODEL_SERVER_URL", "http://127.0.0.1:8080").rstrip("/")
RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}
BACKOFF = (2, 5, 15, 30)


class Provider:
    def __init__(
        self,
        url=None,
        model=None,
        api_key=None,
        timeout=600,
        temperature=None,
        seed=None,
        max_tokens=None,
        retries=len(BACKOFF),
        extra=None,
    ):
        self.url = (url or DEFAULT_URL).rstrip("/")
        if self.url.endswith("/v1"):
            self.url = self.url[:-3]
        self.model = model or "local"
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self.timeout = timeout
        self.temperature = temperature
        self.seed = seed
        self.max_tokens = max_tokens
        self.retries = retries
        self.extra = dict(extra or {})
        self._ids = 0

    def describe(self):
        return {
            "model": self.model,
            "url": self.url,
            "temperature": self.temperature,
            "seed": self.seed,
            "max_tokens": self.max_tokens,
        }

    def _post(self, payload, on_retry=None):
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        last = None
        for attempt in range(self.retries + 1):
            try:
                r = requests.post(
                    f"{self.url}/v1/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=self.timeout,
                )
                if r.ok:
                    return r.json()
                last = f"{r.status_code}: {r.text[:500]}"
                if r.status_code not in RETRY_STATUS:
                    raise RuntimeError(last)
            except (requests.ConnectionError, requests.Timeout) as e:
                last = f"{type(e).__name__}: {str(e)[:300]}"
            if attempt < self.retries:
                wait = BACKOFF[min(attempt, len(BACKOFF) - 1)]
                if on_retry:
                    on_retry(attempt + 1, wait, last)
                time.sleep(wait)
        raise RuntimeError(f"gave up after {self.retries + 1} attempts: {last}")

    def complete(self, messages, tools=None, on_retry=None):
        payload = {"model": self.model, "messages": messages}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        if self.seed is not None:
            payload["seed"] = self.seed
        if self.max_tokens is not None:
            payload["max_tokens"] = self.max_tokens
        payload.update(self.extra)

        data = self._post(payload, on_retry=on_retry)
        choice = (data.get("choices") or [{}])[0]
        raw = choice.get("message") or {}

        reasoning = raw.get("reasoning_content") or raw.get("reasoning") or None
        calls = []
        for c in raw.get("tool_calls") or []:
            fn = dict(c.get("function") or {})
            args = fn.get("arguments")
            if isinstance(args, (dict, list)):
                fn["arguments"] = json.dumps(args)
            elif args is None:
                fn["arguments"] = "{}"
            cid = c.get("id")
            if not cid:
                self._ids += 1
                cid = f"call_{self._ids}"
            calls.append({"id": cid, "type": "function", "function": fn})

        msg = {"role": "assistant", "content": raw.get("content") or ""}
        if calls:
            msg["tool_calls"] = calls

        return {
            "message": msg,
            "reasoning": reasoning,
            "finish_reason": choice.get("finish_reason"),
            "usage": data.get("usage") or {},
            "served_model": data.get("model"),
        }
