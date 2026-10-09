# MedStock — "Upload your data" Architecture Plan

**Goal:** a user opens MedStock, uploads their sales data (plus optional purchases/batches), and the system runs the same warehouse → analytics → mining → forecasting → decision pipeline on *their* data and shows the results in the existing pages.

**Decisions taken**
- Input: **sales required**, purchases + batches optional (more files unlock more features).
- Isolation: **one dataset per upload, no login**.
- Processing: **background job with progress**.
- Existing synthetic dataset stays as the default **demo dataset**.

---

## 1. Why this is a real architecture change

Today everything assumes exactly one dataset:

| Part | Current assumption |
|---|---|
| ETL | reads `data/raw/*.csv`, truncates and rebuilds the single `warehouse` schema |
| SQL (~650 references) | hardcodes `warehouse.<table>` |
| Mining / ML / Decisions | write static files to `<module>/reports/` |
| API | reads those fixed report paths and one database |
| Frontend | no concept of "which dataset" |
| Inventory | derived from purchases + batches (a sales file alone cannot give stock or expiry) |

## 2. Core design (minimal-change)

**One PostgreSQL database per dataset, each keeping the schema name `warehouse`.**
This avoids touching ~650 SQL references: the pipeline only needs a different connection string. Demo data stays in the current database as dataset `demo`.

```
data/datasets/<dataset_id>/
    raw/            uploaded CSVs (validated copies)
    reports/
        analytics/  mining/  forecast/  decision/
    meta.json       status, capabilities, row counts, timings, errors
database: medstock_<dataset_id>   (schema "warehouse")
```

A small **dataset registry** (the `meta.json` files, or one SQLite file) lists datasets and their state.
Every pipeline stage reads two things from its environment/arguments instead of constants: **dataset id** (→ database URL, raw dir, report dirs).

## 3. What each upload unlocks

| Files uploaded | Available |
|---|---|
| `sales.csv` only | Dashboard (sales KPIs), Sales analytics/OLAP, association rules, clustering, anomaly detection, demand forecasting (without stock features), top-seller/slow-mover analysis |
| + `purchases.csv` | supplier/purchase analytics, estimated inventory (opening stock must be assumed → flagged as estimate) |
| + `batches.csv` | expiry risk, FEFO, full Decision Support (reorder, overstock, expiry, stockout) |

The UI shows a **capability banner** and greys-out/explains pages that need missing files ("Upload purchases and batches to enable Inventory and Decisions").

## 4. Minimum required columns (sales)

`transaction_id, transaction_date, branch_id, medicine_id, quantity, unit_selling_price` (+ optional `medicine_name, category, discount, total_amount, batch_id`).
Missing master data (medicines, branches, categories) is **derived from the sales file** when not uploaded. A **column-mapping step** lets users map their own headers to ours (e.g. `Date` → `transaction_date`).

**Validation before anything runs** (fail fast, readable messages): required columns, types, parseable dates, non-negative quantity/price, duplicate keys, file size/row cap, date span (forecasting needs enough history — at least roughly 6 months, otherwise forecasting is skipped with an explanation), enough distinct medicines/transactions for mining.

## 5. Processing flow

```
POST /api/datasets            upload files + mapping → validate → create dataset (status: queued)
        │
background worker (one job at a time)
        ├─ 1 ETL         create DB + schema → load dims/facts (inventory only if purchases+batches)
        ├─ 2 Analytics   create views, run queries
        ├─ 3 Mining      association, clustering, anomaly
        ├─ 4 Forecast    train + forecast (skipped if history too short)
        └─ 5 Decisions   only if inventory exists
GET  /api/datasets/{id}/status   → stage, % complete, per-stage result, errors
```

Each stage records `ok / skipped (reason) / failed (message)` in `meta.json`, so a failure in one stage does not hide the others.

## 6. API changes

- New: `POST /api/datasets`, `GET /api/datasets`, `GET /api/datasets/{id}`, `GET /api/datasets/{id}/status`, `DELETE /api/datasets/{id}`, `GET /api/datasets/template/{file}` (sample CSV headers).
- Existing endpoints get a dataset selector — preferably an `X-Dataset-Id` header (default `demo`), so no frontend call signature has to change except `api/client.js`.
- `database.py`: resolve DB engine and report directory **per dataset** (cache engines).

## 7. Frontend changes

1. **Upload page** (`/upload`): drag-and-drop for the three files, template downloads, column-mapping table, client-side preview + validation summary.
2. **Processing screen:** stage list with progress and errors; polls the status endpoint.
3. **Dataset selector** in the header (demo + user datasets); stored in `api/client.js` and sent with every request.
4. **Capability gating** on each page plus clear "not available for this dataset" states.
5. Existing pages remain unchanged otherwise.

## 8. Code changes needed in existing pipeline

| Area | Change |
|---|---|
| Config modules (`etl`, `analytics`, `data_mining`, `ml_forecasting`, `decision_support`) | replace constants with dataset-aware paths (`DATASET_ID` env/argument) |
| ETL | allow missing purchases/batches; derive dimensions from sales; skip inventory/expiry facts when absent |
| Analytics SQL | views that depend on inventory/batches must be created conditionally |
| Mining | features that need stock/expiry become optional |
| Forecasting | stock/stockout features optional; history-length guard |
| Decisions | run only when inventory + batches exist |
| Validation checks | reconcile against uploaded data instead of fixed expected counts (some checks assume 500 medicines, 5 branches, 730 days) |
| Generator ground-truth evaluation | stays demo-only (uploads have no ground truth) |

## 9. Risks and mitigations

- **Run time:** current full pipeline takes several minutes for ~1 M rows → row/size cap, progress UI, one job at a time, optional lighter mode.
- **Hardcoded assumptions** (500 medicines, 5 branches, 24 months) in validators and some SQL → audit and relax.
- **Sales-only inventory:** without purchases/batches, stock and expiry cannot be known → do not fake it; show as unavailable (or clearly labelled estimate).
- **Security (public upload):** file-size limits, CSV-only, safe filenames, dataset ids generated server-side (no user-supplied paths/SQL identifiers), parameterised queries, rate limiting; `CREATE DATABASE` privilege confined to the app role.
- **Disk growth:** dataset expiry/cleanup (e.g. auto-delete after N days) and a delete button.
- **Concurrency:** single worker queue first; scale later.
- **Messy real data:** duplicates, mixed date formats, returns/negative quantities → validation + cleaning report shown to the user.

## 10. Suggested build order

| Phase | Deliverable | Result |
|---|---|---|
| **A. Parametrise** | dataset-aware config + per-dataset DB/report dirs; demo still works | no visible change, foundation |
| **B. Sales-only ingestion** | validation, column mapping, ETL without inventory, background job + status API | upload sales → sales analytics + mining |
| **C. Upload UI** | upload page, progress, dataset selector, capability gating | end-to-end user flow |
| **D. Forecast on upload** | forecasting without stock features, history guard | forecast page works for uploads |
| **E. Full mode** | purchases + batches → inventory, expiry, decisions | all pages work for uploads |
| **F. Hardening** | limits, cleanup, error messages, tests, docs | demo-ready |

Phases A–C already give a convincing demo ("upload a sales CSV and get analytics"); D–E complete the vision.

## 11. Open points to confirm later

- Maximum upload size / row cap.
- Retention period for uploaded datasets.
- Whether to host (deployment needs PostgreSQL permissions to create databases) or run locally for the demo.


---

## 12. Implementation status

| Phase | Status |
|---|---|
| A. Dataset-aware config, per-dataset DB/reports, `X-Dataset-Id` header | done |
| B. Sales upload: validation, column mapping, ETL, background job + status API | done |
| C. Upload page, progress, dataset selector, capability gating | done |
| D. Demand forecasting on uploads (`ml_forecasting/upload_run.py`, stock-free) | done |
| E. Optional purchases file: FEFO stock reconstruction, expiry, clustering, anomalies, decision support | done |
| F. Hardening: upload limits, rate limit, CSV content checks, auto-delete after 14 days, 40-char ids, docs, tests | done |

**Phase E design notes**
- One optional *purchases* file (receipts: date, medicine, quantity, unit cost; batch and expiry optional) replaces the separate batches file.
- A sales file does not say which batch each sale used, so sales are replayed per branch x medicine and filled FEFO from lots that have been received and not expired (`datasets/allocation.py`).
- Sales that exceed everything received so far are covered by an **implied opening stock** (lot `OPENING-<medicine>`, never expires, received on day 1). Its size and share of units sold are reported as a warning; above 20% the UI says decisions are indicative only.
- Receipts before the first sale count as opening stock on day 1; receipts after the last sale are ignored; receipts already expired on arrival are dropped.
- Inventory is a dense date x branch x medicine snapshot, so uploads with purchases are limited to 20 million such rows.
- Decision support runs the same engine as the demo (`decision_support/upload_run.py`) on the latest date; the demo-only historical simulation is not run.
- Decision support and Risk pages need purchases **and** at least 180 days of history (capability `decision_support`).
