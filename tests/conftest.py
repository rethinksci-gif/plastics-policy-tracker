import json
from datetime import datetime, timezone

import pytest

from pipeline.models import Dossier, Snapshot

TRUSTED = {"official": ["europa.eu", "gov.uk"], "trade-association": ["plasticseurope.org"], "media": ["euractiv.com"]}
URL = "https://environment.ec.europa.eu/news/example_en"
SOURCE_TEXT = (
    "Brussels, 2 October 2026.\n"
    "The Commission today adopted an implementing act laying down the methodology for calculating\n"
    "recycled content in single-use plastic bottles.  The act will apply from 1 January 2027.\n"
    "Member States must report data by 1 July 2027."
)


@pytest.fixture
def raw_dir(tmp_path):
    d = tmp_path / "raw" / "2026-10-02"
    d.mkdir(parents=True)
    snap = Snapshot(id="2026-10-02/test-abc", source_id="test", url=URL, title="t",
                    fetched_at=datetime(2026, 10, 2, tzinfo=timezone.utc), sha256="abc", trust="official",
                    jurisdiction="EU", text=SOURCE_TEXT)
    (d / "test-abc.json").write_text(snap.model_dump_json())
    (tmp_path / "raw" / "index.json").write_text(json.dumps({"hashes": {"abc": snap.id}, "urls": {URL: "abc"}}))
    return tmp_path / "raw"


@pytest.fixture
def dossier():
    return Dossier.model_validate({
        "id": "eu-supd", "title": "Single-Use Plastics Directive", "jurisdiction": "EU", "instrument": "directive",
        "topics": ["single-use"], "stage": "in-application", "affected": ["converters"], "impact": "high",
        "official_links": ["https://eur-lex.europa.eu/eli/dir/2019/904/oj"],
        "updates": [{
            "date": "2026-07-01", "summary": "An earlier recorded update about the directive.",
            "source_url": "https://environment.ec.europa.eu/news/older_en",
            "source_quote": "An earlier verbatim passage from the source.", "review_id": "seed-001",
        }],
    })
