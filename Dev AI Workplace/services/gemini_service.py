"""Thin wrapper around the Gemini API (google-genai SDK) with robust
failure handling.

Retries transient failures (503 UNAVAILABLE, 429 rate limit, 500 server
error, timeouts, network errors) up to 3 times with exponential backoff
(2s, 4s, 8s). If Gemini is still unavailable after retries, raises
GeminiUnavailableError — callers (agents/matcher_agent.py, services/chat.py)
catch this and fall back to the deterministic matching engine rather than
crashing or showing a raw API exception to the user.
"""
from __future__ import annotations

import time

from google import genai
from google.genai import errors as genai_errors

from services.config import Settings

RETRYABLE_HTTP_CODES = {429, 500, 503, 504}
BACKOFF_SECONDS = [2, 4, 8]

_client_cache: dict[str, genai.Client] = {}


class GeminiUnavailableError(Exception):
    """Raised when Gemini could not be reached after all retries. Callers
    should catch this specifically and fall back gracefully — never let it
    surface as a raw traceback to the user."""


def get_gemini_client(settings: Settings) -> genai.Client:
    if not settings.gemini_configured:
        raise RuntimeError(
            "Gemini is not configured. Enter your Gemini API key on the Settings page."
        )
    cached = _client_cache.get(settings.gemini_api_key)
    if cached:
        return cached
    client = genai.Client(api_key=settings.gemini_api_key)
    _client_cache[settings.gemini_api_key] = client
    return client


def _is_retryable(exc: Exception) -> bool:
    code = getattr(exc, "code", None)
    if isinstance(code, int) and code in RETRYABLE_HTTP_CODES:
        return True
    # Network-level failures (DNS, connection reset, timeout) don't carry a
    # Gemini status code but should still be retried.
    text = str(exc).lower()
    return any(
        keyword in text
        for keyword in ("timeout", "timed out", "connection", "network", "unavailable")
    )


def generate_text(client: genai.Client, model: str, prompt: str) -> str:
    """Calls Gemini with retry + exponential backoff. Raises
    GeminiUnavailableError (never a raw SDK exception) if every attempt
    fails."""
    last_error: Exception | None = None

    for attempt in range(len(BACKOFF_SECONDS) + 1):
        try:
            response = client.models.generate_content(model=model, contents=prompt)
            return (response.text or "").strip()
        except genai_errors.APIError as exc:
            last_error = exc
            if not _is_retryable(exc) or attempt == len(BACKOFF_SECONDS):
                break
            time.sleep(BACKOFF_SECONDS[attempt])
        except Exception as exc:  # noqa: BLE001 - network/timeout errors etc.
            last_error = exc
            if not _is_retryable(exc) or attempt == len(BACKOFF_SECONDS):
                break
            time.sleep(BACKOFF_SECONDS[attempt])

    raise GeminiUnavailableError(
        "Gemini is temporarily unavailable. Showing database-based recommendations."
    ) from last_error
