"""MedStock read-only API.  Run:  uvicorn api.main:app --reload   (docs at /docs)"""
import logging
import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from .database import get_engine, log
from .routers import analytics, dashboard, decisions, mining
from .schemas import Health, Ready

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(
    title="MedStock API",
    version="1.0",
    description="Read-only API over the MedStock warehouse, analytics views and the stored Data Mining, ML forecasting and "
                "Decision Support reports. It never recalculates analytics, trains models or applies decision rules. Synthetic data; "
                "inventory-management recommendations only.",
)

origins = [o.strip() for o in os.environ.get("FRONTEND_ORIGINS", "http://localhost:5173").split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET"], allow_headers=["*"])


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


for r in (dashboard.router, analytics.router, mining.mining, mining.forecasts, decisions.router):
    app.include_router(r)
