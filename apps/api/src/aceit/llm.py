"""One small interface to the language model used by the explanation writer and the publish gate: Google Gemini, or any provider that
speaks the common OpenAI-style chat API (Groq, OpenRouter, Cerebras...). Anthropic is never used.

    GEMINI_API_KEY=...   the key (environment only: never written to a file, a log or the database)
    GEMINI_MODEL=...     optional; default below. Ask Google which models a key can use: GET /v1beta/models
    LLM_BASE_URL=... LLM_API_KEY=... LLM_MODEL=...   use an OpenAI-style provider instead, e.g. https://api.groq.com/openai/v1
Free tiers allow only a few requests a minute, so calls are spaced out and a rate-limit answer (429) is waited out and retried.
"""
import base64
import os
import time
from pathlib import Path

import httpx

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class Llm:
    def __init__(self, key: str, model: str, *, min_interval_s: float | None = None, client: httpx.Client | None = None, sleep=time.sleep):
        self.key, self.model = key, model
        self.MODEL = f"gemini:{model}"
        self.min_interval_s = float(os.environ.get("ACEIT_LLM_MIN_INTERVAL_S", "4")) if min_interval_s is None else min_interval_s
        self.client, self.sleep, self._last = client or httpx.Client(timeout=180), sleep, 0.0

    def __call__(self, prompt: str, images: list[Path] | None = None, max_tokens: int = 2000, temperature: float = 0.7) -> str:
        images = images or []
        for attempt in range(4):
            wait = self.min_interval_s - (time.monotonic() - self._last)
            if wait > 0:
                self.sleep(wait)
            self._last = time.monotonic()
            try:
                r = self.client.post(**self._request(prompt, images, max_tokens, temperature))
            except httpx.TransportError:                                         # connection dropped or timed out: wait and try again
                if attempt == 3:
                    raise
                self.sleep(10 * (attempt + 1)); continue
            if r.status_code in (429, 503) and attempt < 3:                    # rate limited or briefly overloaded: wait and try again
                self.sleep(float(r.headers.get("retry-after", 20 * (attempt + 1))))
                continue
            r.raise_for_status()
            return self._text(r.json())
        raise RuntimeError("unreachable")

    def _request(self, prompt, images, max_tokens, temperature) -> dict:
        parts = [{"inline_data": {"mime_type": "image/png", "data": base64.b64encode(i.read_bytes()).decode()}} for i in images] + [{"text": prompt}]
        return dict(url=GEMINI_URL.format(model=self.model), headers={"x-goog-api-key": self.key},       # key in a header, never in the URL
                    json={"contents": [{"parts": parts}], "generationConfig": {"maxOutputTokens": max_tokens, "temperature": temperature}})

    def _text(self, body: dict) -> str:
        return "".join(p.get("text", "") for c in body.get("candidates", [])[:1] for p in c.get("content", {}).get("parts", []))


class OpenAICompat(Llm):
    """Same retry and spacing as Llm, but the request and reply follow the OpenAI chat format (page images go in as data URLs)."""
    def __init__(self, key: str, model: str, base_url: str, **kw):
        if "anthropic" in base_url.lower():
            raise ValueError("Anthropic is not used by this project")
        super().__init__(key, model, **kw)
        self.base_url, self.MODEL = base_url.rstrip("/"), f"openai-compatible:{model}"

    def _request(self, prompt, images, max_tokens, temperature) -> dict:
        content = [{"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(i.read_bytes()).decode()}} for i in images] + [{"type": "text", "text": prompt}]
        return dict(url=self.base_url + "/chat/completions", headers={"Authorization": f"Bearer {self.key}"},
                    json={"model": self.model, "messages": [{"role": "user", "content": content}], "max_tokens": max_tokens, "temperature": temperature})

    def _text(self, body: dict) -> str:
        return (body.get("choices") or [{}])[0].get("message", {}).get("content") or ""


def from_env() -> Llm | None:
    """The configured model, or None when no key is set."""
    if os.environ.get("LLM_BASE_URL") and os.environ.get("LLM_API_KEY"):
        return OpenAICompat(os.environ["LLM_API_KEY"], os.environ.get("LLM_MODEL", "llama-3.3-70b-versatile"), os.environ["LLM_BASE_URL"])
    if os.environ.get("GEMINI_API_KEY"):
        return Llm(os.environ["GEMINI_API_KEY"], os.environ.get("GEMINI_MODEL", "gemini-3.8-flash"))
    return None
