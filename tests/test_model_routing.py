"""Model allocation per stage, the high-impact second review, and layer-4 style notes never blocking."""

import pytest

import pipeline.review as review
from pipeline.compose import editorial_blocking, editorial_unattached_blocking
from pipeline.config import model_for
from pipeline.models import EditorialReview, LLMReview


@pytest.fixture(autouse=True)
def _models(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_MODEL_FAST", "fast-model")
    monkeypatch.setenv("DEEPSEEK_MODEL_PRO", "pro-model")


def test_stage_tiers():
    assert model_for("triage") == "fast-model"
    assert model_for("draft") == "fast-model"
    assert model_for("review") == "fast-model"
    assert model_for("highlights") == "fast-model"
    assert model_for("review_high_confirm") == "pro-model"
    assert model_for("editor") == "pro-model"


class FakeLLM:
    """Returns a scripted verdict per model and records which models were called."""

    def __init__(self, verdicts):
        self.verdicts, self.called = verdicts, []

    def json_call(self, model, system, user, schema, max_tokens=0):
        self.called.append(model)
        verdict, conf = self.verdicts[model]
        return LLMReview(verdict=verdict, confidence=conf, checks={}, issues=[] if verdict == "supported" else ["x"])


def run(llm, impact):
    return review.layer3(llm, claim="{}", url="https://example.europa.eu", source_text="The act applies.",
                         quote="The act applies.", impact=impact)


def test_medium_impact_uses_fast_only():
    llm = FakeLLM({"fast-model": ("supported", 0.9)})
    out = run(llm, "medium")
    assert llm.called == ["fast-model"] and not out["reasons"] and out["confirm"] is None


def test_high_impact_needs_both_reviewers():
    llm = FakeLLM({"fast-model": ("supported", 0.9), "pro-model": ("partially_supported", 0.9)})
    out = run(llm, "high")
    assert llm.called == ["fast-model", "pro-model"]
    assert out["confirm_model"] == "pro-model"
    assert any("high-impact confirmation" in r for r in out["reasons"])


def test_high_impact_rejected_by_fast_never_reaches_pro():
    llm = FakeLLM({"fast-model": ("unsupported", 0.95), "pro-model": ("supported", 0.99)})
    out = run(llm, "high")
    assert llm.called == ["fast-model"] and out["reasons"]


def test_high_impact_passes_when_both_agree():
    llm = FakeLLM({"fast-model": ("supported", 0.85), "pro-model": ("supported", 0.9)})
    assert not run(llm, "high")["reasons"]


def test_style_notes_never_block():
    ed = EditorialReview(passed=False, terminology_issues=["'European Commission' vs 'the Commission'"],
                         style_notes={"2026-10-14-004": ["write 'the Commission'"]})
    assert editorial_blocking(ed) == {}
    assert editorial_unattached_blocking(ed) == []  # passed=False alone does not hold the issue


def test_factual_flags_block():
    ed = EditorialReview(passed=False, history_conflicts=["stage conflicts with history"],
                         item_flags={"2026-10-14-006": ["stage conflicts with history"]})
    assert editorial_blocking(ed) == {"2026-10-14-006": ["stage conflicts with history"]}
    unattached = EditorialReview(passed=False, contradictions=["items 1 and 2 disagree on the date"])
    assert editorial_unattached_blocking(unattached) == ["items 1 and 2 disagree on the date"]
