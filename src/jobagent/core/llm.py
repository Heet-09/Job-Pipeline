"""LLM wrapper (LLD 5.2): structured output, one JSON-fix retry, 429 backoff, and full call logging."""
import json
import re
import time
from dataclasses import dataclass
from typing import Callable

from pydantic import BaseModel, ValidationError

from jobagent.core.db import Database
from jobagent.core.logging import get_logger, redact

log = get_logger("jobagent.llm")


class LLMError(Exception):
    pass


class RateLimitError(LLMError):
    """Provider returned 429."""


class ExtractionFailed(LLMError):
    """Model output was still invalid after the retry."""


class SensitiveLeak(LLMError):
    """A sensitive value was about to be sent in a prompt."""


@dataclass
class LLMResponse:
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0


Backend = Callable[[str, str, str], LLMResponse]  # (model, system, user) -> response

# USD per 1M tokens (prompt, completion). Unknown models cost 0.
PRICES = {"llama-3.1-8b-instant": (0.05, 0.08), "llama-3.3-70b-versatile": (0.59, 0.79)}


def _json_text(text: str) -> str:
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        return m.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    return text[start:end + 1] if start != -1 and end > start else text


class LLMClient:
    def __init__(self, backend: Backend, db: Database | None = None, models: dict | None = None,
                 sleep=time.sleep, rate_limit_retries: int = 3, base_delay: float = 1.0,
                 forbidden: list[str] | None = None):
        self.backend = backend
        self.db = db
        self.models = models or {"small": "small", "large": "large"}
        self.sleep = sleep
        self.rate_limit_retries = rate_limit_retries
        self.base_delay = base_delay
        self.forbidden = [f for f in (forbidden or []) if len(str(f)) >= 4]

    def _log(self, flow, job_id, model, system, user, resp, ok, error, started):
        if not self.db:
            return
        p, c = (resp.prompt_tokens, resp.completion_tokens) if resp else (0, 0)
        pin, pout = PRICES.get(model, (0.0, 0.0))
        self.db.write(
            "INSERT INTO llm_calls(flow, job_id, model, prompt_tokens, completion_tokens, cost_usd, latency_ms, ok, error, prompt, at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (flow, job_id, model, p, c, (p * pin + c * pout) / 1_000_000, int((time.monotonic() - started) * 1000),
             int(ok), error, redact(f"{system}\n---\n{user}"), self.db.now_iso()))

    def _invoke(self, flow, job_id, model, system, user) -> LLMResponse:
        """One backend call with 429 backoff. Every attempt is logged."""
        for attempt in range(self.rate_limit_retries + 1):
            started = time.monotonic()
            try:
                resp = self.backend(model, system, user)
                self._log(flow, job_id, model, system, user, resp, True, None, started)
                return resp
            except RateLimitError as e:
                self._log(flow, job_id, model, system, user, None, False, f"429: {e}", started)
                if attempt == self.rate_limit_retries:
                    raise
                delay = self.base_delay * (2 ** attempt)
                log.warning("rate limited, retrying in %.1fs (attempt %d)", delay, attempt + 1)
                self.sleep(delay)
            except Exception as e:
                self._log(flow, job_id, model, system, user, None, False, str(e)[:300], started)
                raise
        raise AssertionError("unreachable")

    def call(self, tier: str, system: str, user: str, schema: type[BaseModel], *, flow: str,
             job_id: int | None = None, retries: int = 1) -> BaseModel:
        for secret in self.forbidden:
            if str(secret) in system or str(secret) in user:
                raise SensitiveLeak("a sensitive profile value was about to be sent to the LLM")
        model = self.models[tier]
        message = user
        last_err = ""
        for attempt in range(retries + 1):
            resp = self._invoke(flow, job_id, model, system, message)
            try:
                return schema.model_validate(json.loads(_json_text(resp.text)))
            except (ValidationError, json.JSONDecodeError, ValueError) as e:
                last_err = str(e)[:200]
                message = f"{user}\n\nYour previous reply was invalid ({last_err}). Reply with ONLY valid JSON matching the schema."
        raise ExtractionFailed(f"invalid LLM output after {retries + 1} attempts: {last_err}")


def langchain_backend(api_key: str | None = None) -> Backend:
    """Real backend (Groq via LangChain). Not exercised by the unit tests - needs GROQ_API_KEY."""
    def run(model: str, system: str, user: str) -> LLMResponse:
        from langchain_groq import ChatGroq

        try:
            msg = ChatGroq(model=model, temperature=0, api_key=api_key).invoke([("system", system), ("human", user)])
        except Exception as e:
            if "429" in str(e) or "rate" in str(e).lower():
                raise RateLimitError(str(e)) from e
            raise
        usage = getattr(msg, "usage_metadata", None) or {}
        return LLMResponse(msg.content, usage.get("input_tokens", 0), usage.get("output_tokens", 0))
    return run
