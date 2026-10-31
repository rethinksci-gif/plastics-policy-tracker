from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from pipeline import compose, review
from pipeline.models import Candidate, DraftUpdate, EditorialReview, ReviewRecord, TriageResult


def candidate(dossier, name='one', status='passed'):
    return Candidate(id=name,created=date(2026,10,20),snapshot_id='snapshot',source_id='official',
                     source_url='https://environment.ec.europa.eu/report',source_trust='official',
                     triage=TriageResult(relevance=1,dossier_id=dossier.id,category='policy',reason='test'),
                     draft=DraftUpdate(dossier_id=dossier.id,date='2026-10-20',summary='The Commission adopted an implementing act on recycled content.',
                                       source_url='https://environment.ec.europa.eu/report',source_quote='The Commission adopted an implementing act on recycled content.'),
                     status=status)


@pytest.fixture
def setup(monkeypatch,tmp_path,dossier):
    issues=tmp_path/'issues';issues.mkdir()
    reviews=tmp_path/'reviews';reviews.mkdir()
    monkeypatch.setattr(compose,'ISSUES',issues)
    monkeypatch.setattr(compose,'REVIEWS',reviews)
    monkeypatch.setattr(compose,'load_dossiers',lambda:{dossier.id:dossier})
    monkeypatch.setattr(compose,'write_issue_report',lambda report:None)
    monkeypatch.setattr(compose,'save_dossier',lambda dossier:None)
    monkeypatch.setattr(compose,'save_candidate',lambda candidate:None)
    monkeypatch.setattr(review,'save_record',lambda *args:None)
    def reviewed(llm,c,d,**kw):
        return ReviewRecord(review_id=c.id,candidate_id=c.id,dossier_id=d.id,created=datetime.now(timezone.utc),
                            impact=d.impact,outcome='passed',checks=[],reasons=[])
    monkeypatch.setattr(review,'review_candidate',reviewed)
    monkeypatch.setattr(compose,'editorial_review',lambda *args:EditorialReview(passed=True))
    return issues,dossier,SimpleNamespace(calls=0,usage={})


def test_valid_item_publishes_with_high_impact_quarantine(setup,monkeypatch):
    issues,dossier,llm=setup
    passed=candidate(dossier)
    held=candidate(dossier,'held','quarantined')
    monkeypatch.setattr(compose,'load_candidates',lambda:[passed,held])
    result=compose.run(llm,issue_date=date(2026,10,26),status_fn=lambda u:200)
    assert result['decision']=='publish'
    assert len(result['published_items'])==1
    assert result['quarantined_items'][0]['id']=='held'
    assert len(list(issues.glob('*.md')))==1
    again=compose.run(llm,issue_date=date(2026,10,27),status_fn=lambda u:200)
    assert again['decision']=='skip'
    assert len(list(issues.glob('*.md')))==1


def test_empty_collection_does_not_publish(setup,monkeypatch):
    issues,dossier,llm=setup
    monkeypatch.setattr(compose,'load_candidates',lambda:[])
    result=compose.run(llm,issue_date=date(2026,10,26))
    assert result['decision']=='hold'
    assert not list(issues.glob('*.md'))


def test_global_conflict_holds_edition(setup,monkeypatch):
    issues,dossier,llm=setup
    monkeypatch.setattr(compose,'load_candidates',lambda:[candidate(dossier)])
    monkeypatch.setattr(compose,'editorial_review',lambda *args:EditorialReview(passed=False,contradictions=['effective dates conflict']))
    assert compose.run(llm,issue_date=date(2026,10,26))['decision']=='hold'
    assert not list(issues.glob('*.md'))


def test_no_force_override(setup):
    with pytest.raises(ValueError,match='cannot be overridden'):
        compose.run(setup[2],override_gate=True)
