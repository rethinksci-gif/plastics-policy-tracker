"""Reading and writing the YAML/JSON files that make up the fact base."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from .config import CANDIDATES, DOSSIERS, RAW, SOURCES
from .models import Candidate, Dossier, Snapshot, Source


class _Dumper(yaml.SafeDumper):
    pass


def _str_presenter(dumper, data):
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_Dumper.add_representer(str, _str_presenter)


def dump_yaml(data) -> str:
    return yaml.dump(data, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=100)


# --- dossiers ---------------------------------------------------------------


def dossier_path(dossier_id: str) -> Path:
    return DOSSIERS / f"{dossier_id}.yaml"


def load_dossier(path: Path) -> Dossier:
    return Dossier.model_validate(yaml.safe_load(path.read_text()))


def load_dossiers() -> dict[str, Dossier]:
    out = {}
    for p in sorted(DOSSIERS.glob("*.yaml")):
        d = load_dossier(p)
        out[d.id] = d
    return out


def save_dossier(d: Dossier) -> None:
    data = d.model_dump(mode="json", exclude_none=True)
    for key in ("updates", "next_steps", "key_dates"):
        data.setdefault(key, [])
    dossier_path(d.id).write_text(dump_yaml(data))


# --- sources ----------------------------------------------------------------


def load_sources() -> list[Source]:
    raw = yaml.safe_load((SOURCES / "feeds.yaml").read_text())
    return [Source.model_validate(s) for s in raw["sources"]]


def load_trusted_domains() -> dict[str, list[str]]:
    return yaml.safe_load((SOURCES / "trusted_domains.yaml").read_text())


# --- snapshots --------------------------------------------------------------


def snapshot_path(snapshot_id: str) -> Path:
    return RAW / f"{snapshot_id}.json"


def save_snapshot(s: Snapshot) -> Path:
    p = snapshot_path(s.id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(s.model_dump_json(indent=1))
    return p


def load_snapshot(snapshot_id: str) -> Snapshot:
    return Snapshot.model_validate_json(snapshot_path(snapshot_id).read_text())


def iter_snapshots(raw_dir: Path = RAW):
    for p in sorted(raw_dir.glob("*/*.json")):
        yield Snapshot.model_validate_json(p.read_text())


def snapshot_index(raw_dir: Path = RAW) -> dict:
    p = raw_dir / "index.json"
    return json.loads(p.read_text()) if p.exists() else {"hashes": {}, "urls": {}}


def save_snapshot_index(index: dict, raw_dir: Path = RAW) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "index.json").write_text(json.dumps(index, indent=1, sort_keys=True))


# --- candidates -------------------------------------------------------------


def candidate_path(c: Candidate) -> Path:
    return CANDIDATES / f"{c.id}.json"


def save_candidate(c: Candidate) -> None:
    CANDIDATES.mkdir(parents=True, exist_ok=True)
    candidate_path(c).write_text(c.model_dump_json(indent=1))


def load_candidates(status: str | None = None) -> list[Candidate]:
    out = [Candidate.model_validate_json(p.read_text()) for p in sorted(CANDIDATES.glob("*.json"))]
    return [c for c in out if status is None or c.status == status]


def next_candidate_id(day) -> str:
    prefix = day.isoformat()
    n = len(list(CANDIDATES.glob(f"{prefix}-*.json"))) + 1
    return f"{prefix}-{n:03d}"
