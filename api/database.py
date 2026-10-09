"""Database and report access for the read-only API. DATABASE_URL comes from the environment (or the git-ignored .env)."""
import json
import logging
import os
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path

import pandas as pd
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from datasets import paths as ds_paths

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if load_dotenv:
    load_dotenv(PROJECT_ROOT / ".env")
if not os.environ.get("DATABASE_URL") and (PROJECT_ROOT / ".env").is_file():
    for line in (PROJECT_ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

log = logging.getLogger("medstock.api")
# Active dataset for the current request (set from the X-Dataset-Id header by the middleware in main.py; default: demo).
current_dataset: ContextVar[str] = ContextVar("current_dataset", default=ds_paths.DEMO)

_engines: dict = {}


def get_engine():
    dataset_id = current_dataset.get()
    if dataset_id not in _engines:
        url = ds_paths.db_url(dataset_id)
        if not url:
            log.error("DATABASE_URL is not set")
            raise HTTPException(503, "Database is not configured")
        _engines[dataset_id] = create_engine(url, pool_pre_ping=True)
    return _engines[dataset_id]


def dispose_engine(dataset_id: str) -> None:
    """Close the pooled connections of a dataset (before its database is dropped)."""
    engine = _engines.pop(dataset_id, None)
    if engine is not None:
        engine.dispose()


def query(sql: str, params: dict | None = None) -> list[dict]:
    """Run a parameterized SELECT and return rows as dicts (Decimal -> float)."""
    try:
        with get_engine().connect() as conn:
            rows = [dict(r._mapping) for r in conn.execute(text(sql), params or {})]
    except SQLAlchemyError as exc:
        log.error("database error: %s: %s", exc.__class__.__name__, str(exc.__cause__ or exc)[:300])
        raise HTTPException(503, "Database unavailable or query failed")
    return [{k: float(v) if hasattr(v, "as_tuple") else v for k, v in r.items()} for r in rows]


@lru_cache(maxsize=16)
def _read_csv(path: Path, _mtime: int) -> pd.DataFrame:
    return pd.read_csv(path)


def load_report(area: str, filename: str) -> pd.DataFrame | dict:
    """Read an existing CSV/JSON report. `area` and `filename` are chosen by the code, never by the client."""
    path = ds_paths.report_dir(area, current_dataset.get()) / filename
    try:
        if filename.endswith(".json"):
            return json.loads(path.read_text(encoding="utf-8"))
        return _read_csv(path, path.stat().st_mtime_ns)      # re-read automatically if the report is regenerated
    except FileNotFoundError:
        if current_dataset.get() != ds_paths.DEMO:           # e.g. decision support for an upload without inventory data
            raise HTTPException(404, "This analysis is not available for the selected dataset")
        log.error("report missing: %s", path)
        raise HTTPException(500, f"Report '{filename}' has not been generated yet")
    except Exception as exc:  # malformed CSV/JSON
        log.error("report unreadable: %s (%s)", path, exc)
        raise HTTPException(500, f"Report '{filename}' could not be read")


def to_records(df: pd.DataFrame) -> list[dict]:
    """DataFrame -> JSON-safe records (NaN -> None)."""
    return df.astype(object).where(df.notna(), None).to_dict("records")


def list_response(df: pd.DataFrame, limit: int, offset: int = 0) -> dict:
    """Standard list envelope: {"data": [...], "count": rows returned, "total": rows matching}."""
    page = df.iloc[offset:offset + limit]
    return {"data": to_records(page), "count": len(page), "total": len(df)}
