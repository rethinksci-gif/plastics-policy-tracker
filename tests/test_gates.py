"""Layers 1 and 2 must reject fabricated quotes and impossible dates."""

from datetime import date

import pytest

import pipeline.checks as checks
from pipeline.checks import (blocking, check_event_date, check_quote, check_stage_change, deterministic_checks,
                             flags, normalise, quote_in_text)
from pipeline.models import Dossier, DraftUpdate

from .conftest import SOURCE_TEXT, TRUSTED, URL

TODAY = date(2026, 10, 14)


@pytest.fixture(autouse=True)
def _raw(raw_dir, monkeypatch):
    monkeypatch.setattr(checks, "RAW", raw_dir)


def draft(**kw):
    base = dict(dossier_id="eu-supd", date="2026-10-02",
                summary="The Commission adopted an implementing act on recycled content in single-use plastic bottles.",
                source_url=URL,
                source_quote="The Commission today adopted an implementing act laying down the methodology for calculating recycled content",
                stage_change=None)
    base.update(kw)
    return DraftUpdate(**base)


def run(d, dossier):
    return deterministic_checks(d, dossier, snapshot_texts=None, status_fn=lambda u: 200, trusted=TRUSTED,
                                now=TODAY, check_urls=True)


# --- layer 2: provenance --------------------------------------------------------


def test_genuine_quote_passes(dossier):
    res = run(draft(), dossier)
    assert not blocking(res), [r.detail for r in blocking(res)]


def test_fabricated_quote_is_rejected(dossier):
    d = draft(source_quote="The Commission today banned all single-use plastic bottles with immediate effect.")
    bad = blocking(run(d, dossier))
    assert any(r.name == "quote-provenance" and r.layer == 2 for r in bad)


def test_subtly_altered_quote_is_rejected(dossier):
    # one number changed: 2027 -> 2028
    d = draft(source_quote="The act will apply from 1 January 2028.")
    assert any(r.name == "quote-provenance" for r in blocking(run(d, dossier)))


def test_quote_without_snapshot_is_rejected(dossier):
    d = draft(source_url="https://environment.ec.europa.eu/news/never-fetched_en")
    assert any(r.name == "quote-provenance" for r in blocking(run(d, dossier)))


def test_normalisation_tolerates_whitespace_quotes_case():
    q = "THE  ACT will apply from 1 January 2027."
    assert quote_in_text(q, SOURCE_TEXT)[0]
    assert normalise("“Recy- cled”") == '"recycled"'


def test_ellipsis_fragments_must_be_in_order():
    ok = "The Commission today adopted an implementing act … The act will apply from 1 January 2027."
    assert quote_in_text(ok, SOURCE_TEXT)[0]
    reversed_ = "The act will apply from 1 January 2027. … The Commission today adopted an implementing act"
    assert not quote_in_text(reversed_, SOURCE_TEXT)[0]


# --- layer 1: deterministic checks ------------------------------------------------


def test_future_event_date_is_rejected(dossier):
    d = draft(date="2026-12-01")
    assert any(r.name == "event-date" for r in blocking(run(d, dossier)))


def test_impossible_date_is_rejected_by_schema():
    with pytest.raises(ValueError):
        draft(date="2026-02-30")


def test_event_date_month_precision():
    assert check_event_date("2026-10", TODAY).passed
    assert not check_event_date("2026-11", TODAY).passed


def test_untrusted_domain_is_rejected(dossier):
    d = draft(source_url="https://www.euractiv.com/section/x/")
    names = {r.name for r in blocking(run(d, dossier))}
    assert "trusted-domain" in names


def test_dead_link_is_rejected(dossier):
    res = deterministic_checks(draft(), dossier, status_fn=lambda u: 404, trusted=TRUSTED, now=TODAY, check_urls=True)
    assert any(r.name == "url-200" for r in blocking(res))


def test_duplicate_is_rejected(dossier):
    d = draft(date="2026-07-01", source_url="https://environment.ec.europa.eu/news/older_en",
              source_quote="An earlier verbatim passage from the source.")
    assert any(r.name == "duplicate" for r in blocking(run(d, dossier)))


def test_past_next_step_marked_to_be_confirmed(dossier):
    d = draft(next_steps=[{"date": "2026-09", "text": "Council vote", "source_url": URL}])
    res = run(d, dossier)
    assert d.next_steps[0].status == "to-be-confirmed"
    assert any(r.name == "next-step-date" for r in flags(res))


@pytest.mark.parametrize("current,proposed,ok", [
    ("proposal", "parliament-council", True),
    ("proposal", "trilogue", True),          # skips one stage: allowed
    ("proposal", "adopted", False),          # skips two stages: human review
    ("in-force", "proposal", False),         # backwards
    ("trilogue", "withdrawn", False),        # terminal: human review
    ("proposal", None, True),
])
def test_stage_transitions(current, proposed, ok):
    r = check_stage_change(current, proposed)
    assert r.passed is ok
    if not ok:
        assert r.severity == "flag"


def test_non_english_source_requires_translation():
    from pipeline.models import Update
    with pytest.raises(ValueError):
        Update(date="2026-01-01", summary="A French decree set the bonus for recycled plastic.",
               source_url="https://www.legifrance.gouv.fr/x", source_quote="Le présent décret entre en vigueur",
               source_lang="fr", review_id="x")


def test_updates_must_be_reverse_chronological(dossier):
    data = dossier.model_dump(mode="json")
    data["updates"].append({**data["updates"][0], "date": "2026-08-01", "review_id": "seed-002"})
    with pytest.raises(ValueError):
        Dossier.model_validate(data)


def test_review_excerpt_contains_quote_in_long_document():
    from pipeline.checks import excerpt_for_review
    long_text = ("Filler sentence about nothing in particular. " * 4000) + SOURCE_TEXT + (" More filler." * 3000)
    ex = excerpt_for_review(long_text, "The act will apply from 1 January 2027.", 20000)
    assert len(ex) < 22000
    assert quote_in_text("The act will apply from 1 January 2027.", ex)[0]
