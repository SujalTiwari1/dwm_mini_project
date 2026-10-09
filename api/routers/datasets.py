"""Datasets: upload a sales file, follow the background pipeline, list / delete datasets.

The demo dataset is always available; uploaded datasets are private folders + databases created from a validated upload.
"""
import json
import logging
import shutil
import tempfile
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import PlainTextResponse

from datasets import jobs, maintenance, paths, purchase_validation as pv, sales_validation as sv

from ..database import dispose_engine

log = logging.getLogger("medstock.api")
router = APIRouter(prefix="/api/datasets", tags=["Datasets"])

MAX_UPLOAD_BYTES = 250 * 1024 * 1024
ALLOWED_SUFFIXES = (".csv", ".txt")
limiter = maintenance.RateLimiter()
PURCHASE_TEMPLATE = (
    "purchase_date,branch_id,medicine_id,batch_id,expiry_date,supplier,quantity,unit_purchase_price\n"
    "2025-01-01,BR001,MED001,BAT0001,2026-12-31,Acme Pharma,500,12.40\n"
    "2025-01-01,BR002,MED001,BAT0001,2026-12-31,Acme Pharma,300,12.40\n"
    "2025-01-03,BR001,MED002,BAT0002,2027-03-31,Zen Labs,200,21.00\n")
TEMPLATE = ("transaction_id,transaction_date,branch_id,medicine_id,medicine_name,category,quantity,unit_selling_price,discount\n"
            "TXN000001,2025-01-01,BR001,MED001,Paracetamol 500mg,Analgesics,2,18.50,0.00\n"
            "TXN000001,2025-01-01,BR001,MED002,Cetirizine 10mg,Antihistamines,1,32.00,0.00\n"
            "TXN000002,2025-01-01,BR002,MED001,Paracetamol 500mg,Analgesics,3,18.50,2.00\n")

DEMO_ENTRY = {"id": paths.DEMO, "name": "Demo dataset (synthetic pharmacy)", "status": "ready", "built_in": True,
              "capabilities": {"sales_analytics": True, "association_rules": True, "multi_branch": True, "forecasting": True,
                               "inventory_expiry_decisions": True, "decision_support": True, "expiry_risk": True}}


async def _save_upload(file: UploadFile, dest: Path) -> int:
    if not (file.filename or "").lower().endswith(ALLOWED_SUFFIXES):
        raise HTTPException(415, "Only .csv files are accepted.")
    size = 0
    with open(dest, "wb") as out:
        while chunk := await file.read(1024 * 1024):
            if size == 0 and b"\x00" in chunk[:8192]:                   # binary content (Excel, zip, image...) is not a CSV
                out.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(415, "This is not a plain-text CSV file. Export your data as CSV (comma-separated) and try again.")
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                out.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(413, f"The file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB. Upload a smaller extract.")
            out.write(chunk)
    return size


def _public(meta: dict) -> dict:
    return {k: v for k, v in meta.items() if k not in ("source_file",)}


@router.get("", summary="List datasets (the demo dataset first)")
def list_datasets():
    return {"data": [DEMO_ENTRY] + [_public(m) for m in paths.list_datasets()]}


@router.get("/template/sales", response_class=PlainTextResponse, summary="Download a sample sales CSV with the expected columns")
def sales_template():
    return PlainTextResponse(TEMPLATE, media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="sales_template.csv"'})


@router.get("/template/purchases", response_class=PlainTextResponse, summary="Download a sample purchases CSV with the expected columns")
def purchases_template():
    return PlainTextResponse(PURCHASE_TEMPLATE, media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="purchases_template.csv"'})


@router.post("/preview", summary="Read the header of a sales or purchases file and suggest a column mapping")
async def preview(file: UploadFile = File(...), kind: str = "sales"):
    if kind not in ("sales", "purchases"):
        raise HTTPException(422, {"messages": ["kind must be 'sales' or 'purchases'."]})
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / "upload.csv"
        await _save_upload(file, dest)
        try:
            return (pv if kind == "purchases" else sv).read_preview(dest)
        except sv.ValidationError as exc:
            raise HTTPException(422, {"messages": exc.messages})


def _parse_mapping(text_value: str, what: str):
    try:
        obj = json.loads(text_value) if text_value.strip() else None
        if obj is not None and not isinstance(obj, dict):
            raise ValueError
        return obj
    except ValueError:
        raise HTTPException(422, {"messages": [f"The {what} column mapping must be a JSON object {{field: column}}."]})


def _prepare(raw: Path, sales_path: Path, mapping, purchases_path: Path | None, purchases_mapping) -> dict:
    """Validate + clean the uploaded files and write the cleaned inputs of the pipeline. Raises sv.ValidationError."""
    sales, meds, report = sv.clean_sales(sales_path, mapping)
    if purchases_path is not None:
        purchases, batches, suppliers, p_report = pv.clean_purchases(purchases_path, purchases_mapping, sales, report["medicines"], report["branches"])
        extra = sorted(set(purchases["medicine_id"]) - set(meds["medicine_id"]))
        if extra:
            meds = pd.concat([meds, pd.DataFrame({"medicine_id": extra, "medicine_name": extra, "category": sv.UNKNOWN_CATEGORY})], ignore_index=True)
        purchases.to_csv(raw / "purchases_clean.csv", index=False)
        batches.to_csv(raw / "batches_clean.csv", index=False)
        suppliers.to_csv(raw / "suppliers_clean.csv", index=False)
        report["purchases"] = p_report
        report["warnings"] = report["warnings"] + p_report["warnings"]
        report["capabilities"]["inventory_expiry_decisions"] = True
        report["capabilities"]["expiry_risk"] = bool(p_report["has_expiry"])
        report["capabilities"]["decision_support"] = bool(report["capabilities"]["forecasting"])
        report["medicines"] = int(len(meds))
    sales.to_csv(raw / "sales_clean.csv", index=False)
    meds.to_csv(raw / "medicine_master.csv", index=False)
    return report


@router.post("", status_code=202, summary="Upload a sales file (and optionally purchases) and start the analytics pipeline")
async def create_dataset(request: Request, file: UploadFile = File(...), purchases: UploadFile | None = File(None), name: str = Form(""),
                         mapping: str = Form(""), purchases_mapping: str = Form("")):
    if not limiter.allow(request.client.host if request.client else "unknown", maintenance.uploads_per_hour()):
        raise HTTPException(429, f"Upload limit reached ({maintenance.uploads_per_hour()} per hour). Please try again later.")
    if len(paths.list_datasets()) >= maintenance.max_datasets():
        raise HTTPException(409, f"The limit of {maintenance.max_datasets()} stored datasets is reached. Delete one on the Upload page first.")
    if jobs.pending_count() >= maintenance.max_queue():
        raise HTTPException(429, "Several datasets are still being processed. Please wait for one to finish.")
    mapping_obj = _parse_mapping(mapping, "sales")
    purchases_obj = _parse_mapping(purchases_mapping, "purchases")
    dataset_id = paths.new_id()
    raw = paths.raw_dir(dataset_id)
    raw.mkdir(parents=True, exist_ok=True)
    try:
        upload = raw / "sales_upload.csv"
        await _save_upload(file, upload)
        purchases_path = None
        if purchases is not None and purchases.filename:
            purchases_path = raw / "purchases_upload.csv"
            await _save_upload(purchases, purchases_path)
        try:
            report = await run_in_threadpool(_prepare, raw, upload, mapping_obj, purchases_path, purchases_obj)
        except sv.ValidationError as exc:
            raise HTTPException(422, {"messages": exc.messages})
        label = (name or Path(file.filename or "").stem or "Uploaded dataset").strip()[:80]
        meta = jobs.new_meta(dataset_id, label, report, Path(file.filename or "sales.csv").name[:120])
        paths.save_meta(dataset_id, meta)
    except Exception:
        shutil.rmtree(paths.dataset_dir(dataset_id), ignore_errors=True)
        raise
    jobs.submit(dataset_id)
    return _public(meta)


@router.get("/{dataset_id}", summary="Get one dataset: validation report, capabilities and pipeline progress")
def get_dataset(dataset_id: str):
    if dataset_id == paths.DEMO:
        return DEMO_ENTRY
    meta = paths.load_meta(dataset_id) if paths.ID_RE.match(dataset_id) else None
    if meta is None:
        raise HTTPException(404, "Unknown dataset")
    return _public(meta)


@router.delete("/{dataset_id}", summary="Delete an uploaded dataset (files and database)")
def delete_dataset(dataset_id: str):
    if dataset_id == paths.DEMO:
        raise HTTPException(400, "The demo dataset cannot be deleted")
    meta = paths.load_meta(dataset_id) if paths.ID_RE.match(dataset_id) else None
    if meta is None:
        raise HTTPException(404, "Unknown dataset")
    if meta.get("status") in ("queued", "running"):
        raise HTTPException(409, "The dataset is still being processed")
    dispose_engine(dataset_id)
    try:
        maintenance.drop_dataset(dataset_id)
    except Exception:
        log.exception("could not remove dataset %s", dataset_id)
        raise HTTPException(503, "The dataset could not be removed")
    return {"deleted": dataset_id}
