"""Where a dataset lives. The built-in ``demo`` dataset resolves to the project's original locations, so nothing
changes for it; every uploaded dataset gets its own folder and its own PostgreSQL database (schema ``warehouse``).

    data/datasets/<id>/raw/           uploaded + cleaned source files
    data/datasets/<id>/reports/<area> analytics | mining | forecast | decision
    data/datasets/<id>/meta.json      status, capabilities, per-stage results
    database  medstock_<id>           same schema/table names as the demo warehouse

The active dataset for a pipeline process is taken from the MEDSTOCK_DATASET environment variable (default: demo).
"""
import json
import os
import re
import uuid
from pathlib import Path

from sqlalchemy.engine import make_url

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEMO = "demo"
DATASETS_DIR = PROJECT_ROOT / "data" / "datasets"
ID_RE = re.compile(r"^[a-z0-9_]{1,40}$")

_DEMO_REPORTS = {"analytics": "analytics/reports", "mining": "data_mining/reports",
                 "forecast": "ml_forecasting/reports", "decision": "decision_support/reports"}
AREAS = tuple(_DEMO_REPORTS)


def _load_env() -> None:
    env = PROJECT_ROOT / ".env"
    if os.environ.get("DATABASE_URL") or not env.is_file():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def current_id() -> str:
    return valid_id(os.environ.get("MEDSTOCK_DATASET", DEMO))


def valid_id(dataset_id: str) -> str:
    if dataset_id != DEMO and not ID_RE.match(dataset_id or ""):
        raise ValueError(f"invalid dataset id {dataset_id!r}")
    return dataset_id


def new_id() -> str:
    return "ds_" + uuid.uuid4().hex[:10]


def dataset_dir(dataset_id: str | None = None) -> Path:
    return DATASETS_DIR / valid_id(dataset_id or current_id())


def raw_dir(dataset_id: str | None = None) -> Path:
    dataset_id = dataset_id or current_id()
    return PROJECT_ROOT / "data" / "raw" if dataset_id == DEMO else dataset_dir(dataset_id) / "raw"


def report_dir(area: str, dataset_id: str | None = None) -> Path:
    dataset_id = dataset_id or current_id()
    if area not in _DEMO_REPORTS:
        raise KeyError(area)
    return PROJECT_ROOT / _DEMO_REPORTS[area] if dataset_id == DEMO else dataset_dir(dataset_id) / "reports" / area


def base_database_url() -> str:
    _load_env()
    url = os.environ.get("DATABASE_URL", "").strip()
    for plain in ("postgresql://", "postgres://"):
        if url.startswith(plain):
            url = "postgresql+psycopg://" + url[len(plain):]
    return url


def db_name(dataset_id: str) -> str:
    return make_url(base_database_url()).database if dataset_id == DEMO else f"medstock_{valid_id(dataset_id)}"


def db_url(dataset_id: str | None = None) -> str:
    """SQLAlchemy URL of the dataset's database (the demo uses DATABASE_URL unchanged)."""
    dataset_id = dataset_id or current_id()
    base = base_database_url()
    if not base or dataset_id == DEMO:
        return base
    return make_url(base).set(database=db_name(dataset_id)).render_as_string(hide_password=False)


def admin_db_url() -> str:
    """URL of the maintenance database used to CREATE/DROP per-dataset databases."""
    return make_url(base_database_url()).set(database="postgres").render_as_string(hide_password=False)


# ── registry (one meta.json per dataset) ─────────────────────────────────────
def meta_path(dataset_id: str) -> Path:
    return dataset_dir(dataset_id) / "meta.json"


def load_meta(dataset_id: str) -> dict | None:
    try:
        return json.loads(meta_path(dataset_id).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return None


def save_meta(dataset_id: str, meta: dict) -> None:
    p = meta_path(dataset_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")
    tmp.replace(p)


def list_datasets() -> list[dict]:
    out = []
    if DATASETS_DIR.is_dir():
        for d in sorted(DATASETS_DIR.iterdir()):
            m = load_meta(d.name) if d.is_dir() and ID_RE.match(d.name) else None
            if m:
                out.append(m)
    return sorted(out, key=lambda m: m.get("created_at", ""), reverse=True)
