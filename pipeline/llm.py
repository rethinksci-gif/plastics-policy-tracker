"""DeepSeek client: JSON mode, pydantic validation, retries and a per-run call budget."""

from __future__ import annotations

import json
import logging
import os
import time
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from .config import PROMPTS, config, max_llm_calls

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


class BudgetExceeded(RuntimeError):
    """Raised when MAX_LLM_CALLS_PER_RUN is reached; the run stops and reports."""


class LLMError(RuntimeError):
    pass


def load_prompt(name: str) -> str:
    return (PROMPTS / f"{name}.md").read_text()


def render(template: str, **values: str) -> str:
    out = template
    for k, v in values.items():
        out = out.replace("{{" + k + "}}", v)
    return out


class LLM:
    def __init__(self, max_calls: int | None = None, client=None):
        self.max_calls = max_calls if max_calls is not None else max_llm_calls()
        self.calls = 0
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0}
        self._client = client

    @property
    def client(self):
        if self._client is None:
            from openai import OpenAI

            key = os.environ.get("DEEPSEEK_API_KEY")
            if not key:
                raise LLMError("DEEPSEEK_API_KEY is not set")
            cfg = config()["llm"]
            self._client = OpenAI(api_key=key, base_url=cfg["base_url"], timeout=cfg["timeout_seconds"])
        return self._client

    def json_call(self, model: str, system: str, user: str, schema: type[T], max_tokens: int = 4000) -> T:
        """One logical call. Each HTTP attempt counts against the budget."""
        retries = config()["llm"]["max_retries"]
        last_err: Exception | None = None
        for attempt in range(retries + 1):
            if self.calls >= self.max_calls:
                raise BudgetExceeded(f"LLM call budget of {self.max_calls} reached")
            self.calls += 1
            try:
                resp = self.client.chat.completions.create(
                    model=model,
                    messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                    response_format={"type": "json_object"},
                    temperature=config()["llm"]["temperature"],
                    max_tokens=max_tokens,
                )
                if resp.usage:
                    self.usage["prompt_tokens"] += resp.usage.prompt_tokens or 0
                    self.usage["completion_tokens"] += resp.usage.completion_tokens or 0
                content = (resp.choices[0].message.content or "").strip()
                if not content:
                    raise LLMError("empty response")
                return schema.model_validate(json.loads(content))
            except (ValidationError, json.JSONDecodeError, LLMError) as e:
                last_err = e
            except Exception as e:  # network / API errors
                last_err = e
            if attempt < retries:
                delay = 2 ** attempt * 2
                log.warning("LLM call failed (%s); retry %d/%d in %ss", last_err, attempt + 1, retries, delay)
                time.sleep(delay)
        raise LLMError(f"LLM call failed after {retries + 1} attempts: {last_err}")


def prompt_parts(name: str, **values: str) -> tuple[str, str]:
    """Split prompts/<name>.md into its '# System' and '# User' sections and fill placeholders."""
    text = load_prompt(name)
    _, _, rest = text.partition("# System")
    system, _, user = rest.partition("# User")
    return render(system.strip(), **values), render(user.strip(), **values)
