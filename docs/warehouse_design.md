# MedStock Data Warehouse: Star Schema Design

> Source data is synthetic (generated for the MedStock academic DWM project) and does not represent actual pharmacy transactions.

## 1. Architecture

```
Raw CSV (frozen, 7 files)          Python ETL (etl/)                PostgreSQL schema "warehouse"
data/raw/*.csv        ──►  extract → transform → load → validate ──►  6 dimensions + 3 facts (star schema)
 OLTP-like, one file per entity     bulk COPY, full rebuild            sql/schema.sql
                                                                             │
                                                                             ▼
                                                              OLAP queries (sql/olap_examples.sql)
```

* The raw CSVs are the source of truth and are **never modified** (the pipeline hashes them before and after a run).
* `data/metadata/ground_truth_private.json` and generator parameters (e.g. `demand_profile`) are **not** loaded: the warehouse contains
  only what a real analytics system would observe.
* Inventory has no source file; `FACT_INVENTORY` is **derived** from purchases, sales and batch expiry (section 4).

## 2. Dimensions

All dimension keys are integer surrogate keys (contiguous 1..n, assigned in natural-key order, so they are reproducible); the source identifier is kept as a
unique natural key. `dim_date` uses the smart key `YYYYMMDD`. All dimensions are Type 1 (the source has no attribute history).

| Dimension | Purpose | Grain | Primary key | Natural/source key | Columns |
|---|---|---|---|---|---|
| `dim_date` | calendar for time analysis | one day, 2025-01-01 to 2026-12-31 (730 rows) | `date_key` (YYYYMMDD) | `full_date` (unique) | date_key, full_date, day, day_of_week (ISO, 1=Mon), day_name, week (ISO), month, month_name, quarter, year, is_weekend |
| `dim_category` | medicine category | one category (10) | `category_key` | `category_id` | category_key, category_id, category_name |
| `dim_medicine` | product | one medicine (500) | `medicine_key` | `medicine_id` | medicine_key, medicine_id, medicine_name, category_key, manufacturer, dosage_form, strength, base_price |
| `dim_branch` | pharmacy branch | one branch (5) | `branch_key` | `branch_id` | branch_key, branch_id, branch_name, city, area |
| `dim_supplier` | supplier | one supplier (30) | `supplier_key` | `supplier_id` | supplier_key, supplier_id, supplier_name, city |
| `dim_batch` | manufacturing lot | one batch of one medicine from one supplier (35,477) | `batch_key` | `batch_id` | batch_key, batch_id, medicine_key, supplier_key, manufacture_date, expiry_date, initial_quantity, purchase_price |

Notes:
* `dim_medicine → dim_category` and `dim_batch → dim_medicine / dim_supplier` are deliberate light snowflaking, as specified; category and medicine
  attributes stay reachable in one or two joins.
* `dim_batch.expiry_date` is what links stock to expiry analysis. `initial_quantity` equals the sum of the batch's purchase lines (validated).
* `demand_profile` (present in `medicines.csv`) is generation metadata and is excluded to avoid leaking the generator's design into analytics or ML features.

## 3. Facts

| Fact | Grain | Rows |
|---|---|---|
| `fact_sales` | **One medicine/batch line sold at one branch as part of one transaction.** | 1,022,346 |
| `fact_purchase` | **One purchased/received medicine batch line for a branch from a supplier.** | 80,363 |
| `fact_inventory` | **End-of-day inventory state of one medicine at one branch for one calendar date.** | 1,825,000 |

### FACT_SALES
* Keys: `sales_key` (surrogate PK); FKs `date_key`, `medicine_key`, `branch_key`, `batch_key`.
* `transaction_id` is a **degenerate dimension**. It repeats once per line (a basket has several lines), so it is not the primary key. The grain is enforced by
  `UNIQUE (transaction_id, medicine_key, batch_key)`, whose leading column also serves basket lookups (needed for association-rule mining later).
* Measures: `quantity` (additive), `unit_selling_price` (non-additive: use revenue / quantity), `discount` (additive, rupees per line),
  `total_amount` (additive). Constraint: `total_amount = quantity × unit_selling_price − discount`.
* Additive across time, medicine, branch, batch and category (all dimensions). Lines are not aggregated in the ETL.

### FACT_PURCHASE
* Keys: `purchase_key` (PK); FKs `date_key` (receipt date), `medicine_key`, `branch_key`, `supplier_key`, `batch_key`; `purchase_id` is a unique degenerate key.
* Measures: `quantity` (additive), `unit_purchase_price` (non-additive; equals the batch's `purchase_price`), `total_cost` (additive).
  Constraint: `total_cost = quantity × unit_purchase_price`.
* A batch can be delivered to several branches (several rows, one date), which is why `branch_key` lives on the fact, not on `dim_batch`.

### FACT_INVENTORY (periodic snapshot, dense)
* Key: composite primary key `(date_key, branch_key, medicine_key)`; FKs to `dim_date`, `dim_branch`, `dim_medicine`.
* Measures: `opening_quantity`, `purchased_quantity`, `sold_quantity`, `expired_quantity`, `closing_quantity`, `closing_value_at_cost`.
* Constraint on every row: `opening + purchased − sold − expired = closing`, and all quantities ≥ 0.
* **Additivity:**
  * Flow measures (`purchased_quantity`, `sold_quantity`, `expired_quantity`) are fully **additive** across all dimensions, including time.
  * State measures (`opening_quantity`, `closing_quantity`, `closing_value_at_cost`) are **semi-additive**: they may be summed across **branches, medicines and
    categories** on a single date, but must **not** be summed across **time**. Over a period use the last day (period-end stock), the first day (opening stock) or an average.
    Example: `sql/olap_examples.sql` query 4c uses the last day of each month.
* Dense by design: every date × branch × medicine row exists (730 × 5 × 500 = 1,825,000). A row with `closing_quantity = 0` *is* a stockout day,
  so stockouts are directly queryable without anti-joins.
* `closing_value_at_cost` values each unit at the purchase price of the batch it came from (exact; computed in integer cents).

## 4. Inventory reconstruction (ETL step)

For each (date, branch, medicine): `opening(t) = closing(t−1)`, opening on day 1 = 0 (the source has no opening stock), and

```
closing = opening + purchased − sold − expired
```

* **purchased** = units received that day (purchases). **sold** = units sold that day from specific batches; the source's FEFO allocation is authoritative and is
  not re-allocated. Because sales carry `batch_id`, the reconstruction is exact per batch.
* **expired**: for each (branch, batch), remaining stock = received − sold. If the batch's `expiry_date` falls inside the calendar, the remaining units are written off **on the
  expiry date** and are unsellable from then on. Batches expiring after 2026-12-31 stay in closing stock.
* The ETL fails if any sale or purchase is dated on/after its batch expiry, if a batch is sold beyond what a branch received, or if any closing quantity would be negative.
* Result (frozen dataset): purchased 1,631,425 − sold 1,582,353 − expired 3,599 = **closing 45,473** units. The same figure was
  recomputed independently from natural IDs and matches the generator's own ledger.

## 5. Indexes (beyond primary/unique keys) and why

| Index | Reason |
|---|---|
| `fact_sales(date_key)`, `(medicine_key)`, `(branch_key)`, `(batch_key)` | the four join/filter/group-by paths of sales analysis: time series, product mix, branch comparison, batch/expiry joins |
| `uq_fact_sales_grain (transaction_id, medicine_key, batch_key)` | enforces the grain; leading `transaction_id` supports basket retrieval |
| `fact_purchase(date_key)`, `(medicine_key)`, `(branch_key)`, `(supplier_key)`, `(batch_key)` | supplier/medicine purchasing analysis, receipt timing, per-batch stock reconstruction |
| `fact_inventory` PK `(date_key, branch_key, medicine_key)` | "state on a date" and date-slice queries (current stock) |
| `fact_inventory(medicine_key, branch_key, date_key)` | one medicine's (or branch+medicine's) stock history over time |
| `dim_medicine(category_key)`, `dim_batch(medicine_key)`, `dim_batch(supplier_key)` | roll-ups from medicine to category and from batch to medicine/supplier |
| `dim_batch(expiry_date)` | range scans for near-expiry / expiry-risk queries |
| natural keys (`*_id`, `full_date`) | UNIQUE constraints, which also index them for ETL lookups |

Dimension attribute columns are not indexed: the dimensions are tiny except `dim_batch` (35k rows), and unneeded indexes only slow loading.

## 6. ETL strategy and performance

* **Idempotent full rebuild:** each run executes `schema.sql` (idempotent `CREATE ... IF NOT EXISTS`), `TRUNCATE`s all nine warehouse tables and reloads everything in
  **one transaction** (all-or-nothing). Re-running never duplicates rows. Chosen because the dataset is frozen and local, so incremental upserts add no value.
* **Bulk loading** with PostgreSQL `COPY ... FROM STDIN` in 200k-row chunks. Money columns are read as text and loaded into `NUMERIC` without a float round-trip.
* **Load-time optimisations:** the secondary indexes and the fact-table foreign keys are dropped before the load and re-created after it
  (definitions are read from the catalog, so `schema.sql` remains the single source of truth). Re-adding an FK validates every row with one set-based join,
  so referential integrity is fully enforced before commit. This cut the load from ~7 min to ~40 s on a local instance.
* Types: dates `DATE`, quantities `INTEGER`, money `NUMERIC(10..14,2)` (never floating point), flags `BOOLEAN`.

## 7. Validation

* `sql/validation.sql` (run by the pipeline and runnable alone in psql): reconciliation, opening/previous-closing continuity, negative stock, sales/purchases vs expiry,
  orphan keys for every FK, duplicate natural keys, date/branch/medicine/supplier coverage, batch consistency, inventory-vs-fact flows (per cell), snapshot density.
* `etl/validation/warehouse_checks.py`: recomputes counts and measures from the raw CSVs in exact integer cents and compares them to the warehouse, recomputes closing/expired
  inventory from natural IDs, cross-checks the generator's reported closing stock, expired units and stockout days, and asserts no generator-metadata columns exist in the schema.
* The CHECK constraints (`total_amount`, `total_cost`, the inventory equation) make an inconsistent row impossible to insert.

## 8. Known limitations

* No slowly changing dimensions and no late-arriving data handling (frozen, single-load source).
* No order/lead-time facts: the source records only the receipt date. Orders still in transit when the data ends do not appear.
* Stockout is defined at day level (end-of-day stock = 0). The source does not record unmet demand.
* Currency is INR throughout; there is no currency dimension.
