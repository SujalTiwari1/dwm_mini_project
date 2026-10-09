"""Housekeeping for uploaded datasets: limits, safe removal and automatic expiry.

Settings (environment variables, all optional):
    MEDSTOCK_RETENTION_DAYS    delete uploaded datasets this many days after creation (default 14, 0 = keep forever)
    MEDSTOCK_MAX_DATASETS      uploaded datasets kept at the same time (default 10)
    MEDSTOCK_MAX_QUEUE         datasets waiting or running in the pipeline (default 3)
    MEDSTOCK_UPLOADS_PER_HOUR  uploads accepted per client address per hour (default 6)
"""
import logging
import os
import shutil
import threading
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine

from . import paths

log = logging.getLogger("medstock.maintenance")
CLEANUP_INTERVAL_SECONDS = 6 * 3600


def _int_env(name: str, default: int) -> int:
    try:
        return max(0, int(os.environ.get(name, default)))
    except ValueError:
        return default


def retention_days() -> int:
    return _int_env("MEDSTOCK_RETENTION_DAYS", 14)


def max_datasets() -> int:
    return _int_env("MEDSTOCK_MAX_DATASETS", 10)


def max_queue() -> int:
    return _int_env("MEDSTOCK_MAX_QUEUE", 3)


def uploads_per_hour() -> int:
    return _int_env("MEDSTOCK_UPLOADS_PER_HOUR", 6)


def expiry_timestamp(created_iso: str | None = None) -> str | None:
    days = retention_days()
    if not days:
        return None
    created = datetime.fromisoformat(created_iso) if created_iso else datetime.now(timezone.utc)
    return (created + timedelta(days=days)).isoformat(timespec="seconds")


def drop_dataset(dataset_id: str) -> None:
    """Remove a dataset's database and folder. Never the demo dataset."""
    if dataset_id == paths.DEMO:
        raise ValueError("the demo dataset cannot be removed")
    admin = create_engine(paths.admin_db_url(), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.exec_driver_sql(f'DROP DATABASE IF EXISTS "{paths.db_name(dataset_id)}" WITH (FORCE)')   # name derived from a validated id
    finally:
        admin.dispose()
    shutil.rmtree(paths.dataset_dir(dataset_id), ignore_errors=True)


def cleanup_expired(on_drop=None) -> list[str]:
    """Delete finished datasets older than the retention period. Datasets still queued or running are left alone."""
    if not retention_days():
        return []
    now = datetime.now(timezone.utc)
    removed = []
    for meta in paths.list_datasets():
        if meta.get("status") in ("queued", "running"):
            continue
        exp = meta.get("expires_at") or expiry_timestamp(meta.get("created_at"))
        try:
            if exp and datetime.fromisoformat(exp) <= now:
                if on_drop:
                    on_drop(meta["id"])
                drop_dataset(meta["id"])
                removed.append(meta["id"])
                log.info("removed expired dataset %s", meta["id"])
        except Exception:
            log.exception("could not remove expired dataset %s", meta.get("id"))
    return removed


def start_cleanup_thread(on_drop=None) -> None:
    def loop():
        while True:
            try:
                cleanup_expired(on_drop)
            except Exception:
                log.exception("cleanup failed")
            time.sleep(CLEANUP_INTERVAL_SECONDS)
    threading.Thread(target=loop, name="medstock-cleanup", daemon=True).start()


class RateLimiter:
    """In-memory sliding window: at most `limit` events per `window` seconds per key."""

    def __init__(self, window: int = 3600):
        self.window, self.hits, self.lock = window, {}, threading.Lock()

    def allow(self, key: str, limit: int) -> bool:
        if limit <= 0:
            return True
        now = time.time()
        with self.lock:
            recent = [t for t in self.hits.get(key, []) if now - t < self.window]
            if len(recent) >= limit:
                self.hits[key] = recent
                return False
            recent.append(now)
            self.hits[key] = recent
            return True
