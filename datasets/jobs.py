"""Background pipeline runner: one job at a time, each stage in its own subprocess, progress kept in meta.json.

Stage states: pending -> running -> ok | failed | skipped (with the reason shown to the user).
Dataset status: queued -> running -> ready | ready_with_warnings | failed.
"""
import json
import logging
import os
import queue
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone

from . import maintenance, paths

log = logging.getLogger("medstock.jobs")
STAGE_TIMEOUT_SECONDS = 45 * 60

NEEDS_PURCHASES = "Needs purchase data: upload a purchases file together with your sales."
NEEDS_HISTORY = "The upload has too little history to forecast (at least 180 days of sales are needed)."


def build_plan(caps: dict):
    """(stage, title, command or None, reason shown when the stage is not run) for the dataset's capabilities."""
    inv = bool(caps.get("inventory_expiry_decisions"))
    return [
        ("etl", "Build data warehouse" + (" (sales, purchases, stock)" if inv else ""), "etl", None),
        ("analytics", "Sales & inventory analytics (OLAP)" if inv else "Sales analytics & OLAP", "analytics", None),
        ("association", "Association rules (items bought together)", "association" if caps.get("association_rules") else None,
         "The upload has no transaction id, so there are no baskets to mine."),
        ("clustering", "Medicine clustering", "clustering" if inv else None, NEEDS_PURCHASES),
        ("anomaly", "Anomaly detection", "anomaly" if inv else None, NEEDS_PURCHASES),
        ("forecast", "Demand forecasting", "forecast" if caps.get("forecasting") else None, NEEDS_HISTORY),
        ("decisions", "Decision support (reorder, overstock, expiry)", "decisions" if inv else None, NEEDS_PURCHASES),
    ]


_queue: "queue.Queue[str]" = queue.Queue()
_worker_started = False
_lock = threading.Lock()


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_meta(dataset_id: str, name: str, report: dict, filename: str) -> dict:
    return {
        "id": dataset_id, "name": name, "created_at": now(), "status": "queued", "source_file": filename,
        "validation": report, "capabilities": report["capabilities"], "error": None, "expires_at": maintenance.expiry_timestamp(),
        "stages": {s: {"title": title, "status": "pending", "message": None, "seconds": None, "result": None}
                   for s, title, _, _ in build_plan(report["capabilities"])},
    }


def _update(dataset_id: str, fn) -> dict:
    with _lock:
        meta = paths.load_meta(dataset_id)
        fn(meta)
        paths.save_meta(dataset_id, meta)
        return meta


def _run_stage(dataset_id: str, command: str) -> tuple[bool, dict | None, str]:
    env = {**os.environ, "MEDSTOCK_DATASET": dataset_id, "DATABASE_URL": paths.db_url(dataset_id), "PYTHONIOENCODING": "utf-8"}
    try:
        proc = subprocess.run([sys.executable, "-m", "datasets.stages", command], cwd=str(paths.PROJECT_ROOT), env=env,
                              capture_output=True, text=True, timeout=STAGE_TIMEOUT_SECONDS, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return False, None, "The step took too long and was stopped."
    result = None
    for line in proc.stdout.splitlines():
        if line.startswith("RESULT "):
            result = json.loads(line[7:])
    if proc.returncode == 0 and result is not None:
        return True, result, ""
    tail = (proc.stderr or proc.stdout).strip().splitlines()[-1:] or ["unknown error"]
    log.error("stage %s failed for %s:\n%s", command, dataset_id, (proc.stderr or proc.stdout)[-2000:])
    return False, None, tail[0][:300]


def _process(dataset_id: str) -> None:
    meta = paths.load_meta(dataset_id)
    if meta is None:
        return
    _update(dataset_id, lambda m: m.update(status="running"))
    caps = meta["capabilities"]
    etl_ok, any_failed = True, False
    for stage, _title, command, skip_reason in build_plan(caps):
        if command is None:
            _update(dataset_id, lambda m, s=stage, r=skip_reason: m["stages"][s].update(status="skipped", message=r))
            continue
        if not etl_ok:
            _update(dataset_id, lambda m, s=stage: m["stages"][s].update(status="skipped", message="The warehouse could not be built."))
            continue
        _update(dataset_id, lambda m, s=stage: m["stages"][s].update(status="running"))
        t0 = time.time()
        ok, result, message = _run_stage(dataset_id, command)
        secs = round(time.time() - t0, 1)
        skipped = ok and isinstance(result, dict) and result.get("skipped")

        def record(m, s=stage, o=ok, r=result, msg=message, sc=secs, sk=skipped):
            m["stages"][s].update(status="skipped" if sk else "ok" if o else "failed", result=None if sk else r, message=sk or msg or None, seconds=sc)
            extra = (r or {}).get("warnings") if o and isinstance(r, dict) else None
            if extra:
                m["validation"]["warnings"] = list(m["validation"].get("warnings", [])) + extra
        _update(dataset_id, record)
        if not ok:
            any_failed = True
            if stage == "etl":
                etl_ok = False

    def finish(m):
        m["finished_at"] = now()
        if not etl_ok:
            m["status"], m["error"] = "failed", m["stages"]["etl"]["message"] or "The warehouse could not be built."
        else:
            m["status"] = "ready_with_warnings" if any_failed else "ready"

    _update(dataset_id, finish)


def _worker() -> None:
    while True:
        dataset_id = _queue.get()
        try:
            _process(dataset_id)
        except Exception as exc:                                    # never let one bad job kill the worker
            log.exception("job crashed for %s", dataset_id)
            _update(dataset_id, lambda m, e=exc: m.update(status="failed", error=f"Unexpected error: {e.__class__.__name__}"))
        finally:
            _queue.task_done()


def start_worker() -> None:
    """Start the single worker thread and fail jobs that were interrupted by a server restart."""
    global _worker_started
    if _worker_started:
        return
    _worker_started = True
    for meta in paths.list_datasets():
        if meta.get("status") in ("queued", "running"):
            _update(meta["id"], lambda m: m.update(status="failed", error="Interrupted by a server restart. Upload the file again."))
    threading.Thread(target=_worker, name="medstock-pipeline", daemon=True).start()


def pending_count() -> int:
    """Datasets waiting for or running in the pipeline."""
    return sum(1 for m in paths.list_datasets() if m.get("status") in ("queued", "running"))


def submit(dataset_id: str) -> None:
    start_worker()
    _queue.put(dataset_id)
