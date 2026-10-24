"""A thin client for the Google Gemini REST API.

Differences from the original code:
  * the API key goes in a request header, not the URL, so it never shows up in logs
  * every request has a timeout and retries on 429 / 5xx with backoff
  * errors are logged on the server but only a short message goes back to the user
  * one reusable method replaces three copies of the same request code
"""
import json
import logging

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)

BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiError(Exception):
    """Raised with a message that is safe to show to the user."""


def _build_session() -> requests.Session:
    retry = Retry(
        total=2,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"POST"}),
        respect_retry_after_header=True,
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


class GeminiClient:
    def __init__(self, api_key, model, embed_model, timeout=30, session=None):
        self.api_key = api_key
        self.model = model
        self.embed_model = embed_model
        self.timeout = timeout
        self.session = session or _build_session()

    def _post(self, url: str, payload: dict) -> dict:
        try:
            response = self.session.post(
                url,
                json=payload,
                headers={"x-goog-api-key": self.api_key},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            log.warning("Gemini request failed: %s", type(exc).__name__)
            raise GeminiError("Could not reach the Gemini API. Try again in a moment.") from exc

        if response.status_code >= 400:
            log.warning("Gemini HTTP %s: %s", response.status_code, response.text[:300])
            if response.status_code in (401, 403):
                raise GeminiError("The Gemini API key was rejected. Check GOOGLE_API_KEY.")
            if response.status_code == 429:
                raise GeminiError("The Gemini quota was reached. Try again later.")
            raise GeminiError(f"The Gemini API returned an error ({response.status_code}).")

        try:
            return response.json()
        except ValueError as exc:
            raise GeminiError("The Gemini API returned an unreadable response.") from exc

    def generate_json(self, prompt: str, schema: dict, system: str = "") -> dict:
        """Ask the model for JSON that matches schema and return it parsed."""
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": schema,
                "temperature": 0.3,
            },
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}

        data = self._post(f"{BASE_URL}/{self.model}:generateContent", payload)

        block_reason = (data.get("promptFeedback") or {}).get("blockReason")
        if block_reason:
            raise GeminiError("Gemini declined to process this text.")

        try:
            raw = data["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(raw)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            log.warning("Unexpected Gemini response shape")
            raise GeminiError("Gemini returned an unexpected response. Try again.") from exc

    def embed(self, text: str) -> list:
        """Return the embedding vector for text."""
        payload = {
            "model": f"models/{self.embed_model}",
            "content": {"parts": [{"text": text[:8000]}]},
        }
        data = self._post(f"{BASE_URL}/{self.embed_model}:embedContent", payload)
        try:
            return data["embedding"]["values"]
        except (KeyError, TypeError) as exc:
            raise GeminiError("Gemini returned an unexpected embedding response.") from exc
