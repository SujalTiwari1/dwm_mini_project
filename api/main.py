"""MedStock read-only API.  Run:  uvicorn api.main:app --reload   (docs at /docs)"""
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from datasets import jobs, maintenance, paths as ds_paths
from sqlalchemy import text

from .database import current_dataset, dispose_engine, get_engine, log
from .routers import analytics, dashboard, datasets, decisions, mining
from .schemas import Health, Ready

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

@asynccontextmanager
async def lifespan(_app):
    """Pipeline worker (fails jobs interrupted by a restart) and periodic removal of expired uploads."""
    jobs.start_worker()
    maintenance.start_cleanup_thread(on_drop=dispose_engine)
    yield


app = FastAPI(
    lifespan=lifespan,
    title="MedStock API",
    version="1.0",
    description="Read-only API over the MedStock warehouse, analytics views and the stored Data Mining, ML forecasting and "
                "Decision Support reports. It never recalculates analytics, trains models or applies decision rules. Synthetic data; "
                "inventory-management recommendations only.",
)

origins = [o.strip() for o in os.environ.get("FRONTEND_ORIGINS", "http://localhost:5173").split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST", "DELETE"], allow_headers=["*"])


@app.middleware("http")
async def select_dataset(request: Request, call_next):
    """Every data request works on one dataset, chosen by the X-Dataset-Id header (default: the demo dataset)."""
    dataset_id = request.headers.get("x-dataset-id", ds_paths.DEMO).strip() or ds_paths.DEMO
    if dataset_id != ds_paths.DEMO:
        if not ds_paths.ID_RE.match(dataset_id) or ds_paths.load_meta(dataset_id) is None:
            return JSONResponse({"detail": "Unknown dataset"}, status_code=404)
    token = current_dataset.set(dataset_id)
    try:
        return await call_next(request)
    finally:
        current_dataset.reset(token)


@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception):
    log.exception("unhandled error on %s", request.url.path)          # details stay in the server log
    return JSONResponse({"detail": "Internal server error"}, status_code=500)


@app.get("/health", response_model=Health, tags=["System"], summary="Liveness check")
def health():
    return {"status": "ok"}


@app.get("/ready", response_model=Ready, tags=["System"], summary="Readiness check (PostgreSQL reachable)")
def ready():
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        log.error("readiness check failed: %s", exc.__class__.__name__)
        return JSONResponse({"status": "not ready", "database": "unreachable"}, status_code=503)
    return {"status": "ready", "database": "connected"}


for r in (dashboard.router, analytics.router, mining.mining, mining.forecasts, decisions.router, datasets.router):
    app.include_router(r)
