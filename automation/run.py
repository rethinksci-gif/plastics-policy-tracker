"""Daily collection and item-level verification; immutable fourteen-day editions."""
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from automation.evidence_gate import digest, now, write
from pipeline import compose, draft, fetch, review, triage
from pipeline.llm import LLM
from pipeline.store import load_candidates


def run():
    status_path = Path('automation/status.json')
    previous = json.loads(status_path.read_text()) if status_path.exists() else {}
    status = {'checked_at': now(), 'status': 'running', 'last_publication': previous.get('last_publication'),
              'last_successful_check': previous.get('last_successful_check'), 'reasons': []}
    try:
        result = fetch.run()
        status['collection'] = result
        if not os.getenv('DEEPSEEK_API_KEY'):
            status.update(status='skipped', reasons=['missing API key; collected sources retained, no publication'])
            return status
        llm = LLM(max_calls=40)
        pending = previous.get('pending_snapshots', [])
        batch = list(dict.fromkeys(pending + result['new']))
        triaged = triage.run(llm, batch[:10])
        status['pending_snapshots'] = triaged['pending'] + batch[10:]
        draft.run(llm)
        review.run(llm, dry_run=True)
        # Anchor cadence in UTC rather than weekday parity; a failed Monday can recover Tuesday.
        anchor = date(2026, 10, 12)
        today = date.today()
        end = anchor + timedelta(days=((today-anchor).days//14)*14)
        result = compose.run(llm, issue_date=end)
        status.update(status=result['decision'], reasons=result.get('hold_reasons', []))
        if result['decision'] == 'publish':
            status['last_publication'] = result['issue']
            target = Path(result['issue_file'])
            publication_id = 'PPT-' + str(end)
            content = target.read_text() + '\nPublication identifier: ' + publication_id + '\n'
            target.write_text(content)
            selected = {i['id'] for i in result['published_items']}
            items = [{'id':c.id,'status':'VERIFIED','reasons':[], 'source_url':c.draft.source_url,
                      'review':'reviews/items/' + (c.review_id or c.id) + '.json'}
                     for c in load_candidates() if c.id in selected]
            write('automation/publications/' + publication_id + '.json',
                  {'id':publication_id,'file':str(target),'sha256':digest(content),'items':items})
        status['last_successful_check'] = now()
    except Exception as exc:
        status.update(status='failed', reasons=[type(exc).__name__ + ': pipeline incomplete; do not commit content'])
        raise
    finally:
        records = []
        for c in load_candidates():
            disposition = {'passed':'VERIFIED', 'published':'VERIFIED', 'discarded':'REJECTED'}.get(c.status,'QUARANTINED')
            path = Path('reviews/items') / f'{c.review_id or c.id}.json'
            evidence = json.loads(path.read_text()) if path.exists() else {}
            records.append({'id':c.id, 'status':disposition, 'source_url':c.source_url,
                            'reasons':(evidence.get('reasons') or (['verification incomplete or edition-level check failed'] if disposition=='QUARANTINED' else [])),
                            'review':str(path) if path.exists() else None})
        write('automation/verification.json', records)
        write(status_path, status)
    return status


if __name__ == '__main__':
    print(json.dumps(run(), indent=2, default=str))
