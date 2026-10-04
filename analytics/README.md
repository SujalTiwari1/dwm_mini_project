# MedStock Analytics + OLAP

SQL analytics on the PostgreSQL star schema (`warehouse` schema, Docker `localhost:5433`, database `medstock`). Methodology, formulas and thresholds:
[docs/analytics_design.md](../docs/analytics_design.md).

```
analytics/
  run.py                 thin runner: creates the views, runs every query, runs validation, writes results
  validation.sql         37 reconciliation checks (analytics vs warehouse facts)
  sql/
    views.sql            7 views (v_monthly_sales, v_medicine_performance, v_branch_performance, v_demand_stats,
                         v_stockout_summary, v_current_inventory, v_expiry_risk)
    sales.sql  branches.sql  inventory.sql  expiry.sql  purchases.sql  demand.sql  stockouts.sql  olap.sql
  reports/
    run_summary.json     query list with row counts and timings, validation results
    results/*.csv        output of every query
```

## Run

The warehouse must be loaded first (`python -m etl.pipeline`) and `DATABASE_URL` set (see the main README).

```bash
python -m analytics.run                  # views + all queries + validation (about 3.5 minutes), exits non-zero on any failure
python -m analytics.run --file expiry    # one query file only (views are always re-created first)
```

Or with psql (the files are plain SQL; `@name` lines are comments):

```bash
psql -h localhost -p 5433 -U medstock -d medstock -f analytics/sql/views.sql
psql -h localhost -p 5433 -U medstock -d medstock -f analytics/sql/sales.sql
psql -h localhost -p 5433 -U medstock -d medstock -f analytics/validation.sql
```

Convention in the query files: `-- @name: title` precedes each statement and statements end with a semicolon (keep semicolons out of comments).
Inventory is semi-additive: current stock is read on one date, trends use month-end stock, turnover uses an average of daily inventory value.
