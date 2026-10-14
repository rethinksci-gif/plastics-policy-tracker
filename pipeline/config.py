"""Configuration and repository paths."""

from __future__ import annotations

import os
from datetime import date
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DOSSIERS = ROOT / "dossiers"
SOURCES = ROOT / "sources"
RAW = ROOT / "data" / "raw"
CANDIDATES = ROOT / "data" / "candidates"
REVIEWS = ROOT / "reviews"
ISSUES = ROOT / "issues"
PROMPTS = ROOT / "prompts"
LOGS = ROOT / "data" / "logs"


@lru_cache
def config() -> dict:
    return yaml.safe_load((ROOT / "config.yaml").read_text())


def today() -> date:
    """Pipeline 'today'. PPT_TODAY lets tests and backfills pin the date."""
    override = os.environ.get("PPT_TODAY")
    return date.fromisoformat(override) if override else date.today()


def model_fast() -> str:
    return os.environ.get("DEEPSEEK_MODEL_FAST") or config()["llm"]["default_model_fast"]


def model_pro() -> str:
    return os.environ.get("DEEPSEEK_MODEL_PRO") or config()["llm"]["default_model_pro"]


def model_for(stage: str) -> str:
    """Model for a pipeline stage, via config llm.stage_models (tier "fast" or "pro")."""
    tier = config()["llm"]["stage_models"][stage]
    if tier not in ("fast", "pro"):
        raise ValueError(f"stage_models.{stage} must be 'fast' or 'pro', not {tier!r}")
    return model_pro() if tier == "pro" else model_fast()


def max_llm_calls() -> int:
    return int(os.environ.get("MAX_LLM_CALLS_PER_RUN") or config()["llm"]["max_calls_per_run"])
