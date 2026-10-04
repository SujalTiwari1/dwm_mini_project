# MedStock ETL

Frozen raw CSVs (`data/raw/`, read-only) → PostgreSQL star schema (`warehouse`). Design: [docs/warehouse_design.md](../docs/warehouse_design.md).

```
etl/
  config.py                  env-driven configuration (DATABASE_URL), paths, load order
  extract/csv_loader.py      read CSVs (money as exact text), structure + key checks, raw-file MD5s
  transform/dimensions.py    dim_date, dim_category, dim_medicine, dim_branch, dim_supplier, dim_batch (+ key maps)
  transform/sales.py         fact_sales   (line grain, not aggregated)
  transform/purchases.py     fact_purchase
  transform/inventory.py     fact_inventory reconstruction (purchases - sales - expiry write-off)
  load/postgres.py           engine, schema creation, truncate, COPY, index/FK drop-and-restore
  load/dimensions.py, load/facts.py
  validation/warehouse_checks.py   runs sql/validation.sql + raw-vs-warehouse checks
  pipeline.py                one-command entry point
```

## Run

```bash
docker compose up -d                # PostgreSQL in Docker: localhost:5433, database medstock (see README)
export DATABASE_URL="postgresql+psycopg://user:password@localhost:5433/medstock"   # or put it in .env
python -m etl.pipeline            # full rebuild + validation (about 40 seconds on Docker)
python -m etl.validation.warehouse_checks   # validation only
```

The pipeline exits non-zero if any validation check fails, and writes `data/metadata/warehouse_validation.json`.
It never writes to `data/raw/` (it verifies the raw MD5s are identical before and after).
