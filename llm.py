"""LLM calls: Anthropic, OpenAI, or Groq (OpenAI-compatible) via env."""
from __future__ import annotations

import json
import os
import re
from typing import Any

from dotenv import load_dotenv

load_dotenv()

GROQ_BASE_URL = "https://api.groq.com/openai/v1"


def get_provider() -> str:
    return os.environ.get("LLM_PROVIDER", "anthropic").lower()


def call_llm(system_prompt: str, user_prompt: str, max_tokens: int = 4096) -> str:
    provider = get_provider()
    if provider == "openai":
        return _call_openai(system_prompt, user_prompt, max_tokens)
    if provider == "groq":
        return _call_groq(system_prompt, user_prompt, max_tokens)
    return _call_anthropic(system_prompt, user_prompt, max_tokens)


def _call_anthropic(system_prompt: str, user_prompt: str, max_tokens: int) -> str:
    import anthropic

    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set (or set LLM_PROVIDER=openai with OPENAI_API_KEY)")
    client = anthropic.Anthropic(api_key=key)
    model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
    msg = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    block = msg.content[0]
    if block.type != "text":
        raise RuntimeError("Unexpected Anthropic response block type")
    return block.text


def _call_openai(system_prompt: str, user_prompt: str, max_tokens: int) -> str:
    from openai import OpenAI

    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    client = OpenAI(api_key=key)
    model = os.environ.get("OPENAI_MODEL", "gpt-4o")
    r = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    choice = r.choices[0].message.content
    if not choice:
        raise RuntimeError("Empty OpenAI response")
    return choice


def _call_groq(system_prompt: str, user_prompt: str, max_tokens: int) -> str:
    """Groq exposes an OpenAI-compatible Chat Completions API."""
    from openai import OpenAI

    key = os.environ.get("GROQ_API_KEY")
    if not key:
        raise RuntimeError(
            "GROQ_API_KEY is not set (get a key at https://console.groq.com/keys ; set LLM_PROVIDER=groq)"
        )
    client = OpenAI(api_key=key, base_url=GROQ_BASE_URL)
    model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
    r = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    choice = r.choices[0].message.content
    if not choice:
        raise RuntimeError("Empty Groq response")
    return choice


_JSON_FENCE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.MULTILINE)


def _repair_json_loose(s: str) -> str:
    """Best-effort fixes for common LLM JSON mistakes."""
    for a, b in (
        ("\u201c", '"'),
        ("\u201d", '"'),
        ("\u2018", "'"),
        ("\u2019", "'"),
    ):
        s = s.replace(a, b)
    # Trailing commas before } or ]
    s = re.sub(r",\s*([}\]])", r"\1", s)
    return s


def parse_json_from_llm(text: str) -> Any:
    """Extract JSON object/array from model output (handles markdown fences, light repair)."""
    original = text.strip()
    text = original
    m = _JSON_FENCE.search(text)
    if m:
        text = m.group(1).strip()

    candidates: list[str] = [text]
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        candidates.append(text[start : end + 1])

    last_err: json.JSONDecodeError | None = None
    for cand in candidates:
        for repaired in (cand, _repair_json_loose(cand)):
            try:
                return json.loads(repaired)
            except json.JSONDecodeError as e:
                last_err = e
                continue
    if last_err:
        raise last_err
    raise json.JSONDecodeError("No JSON object found", original, 0)
