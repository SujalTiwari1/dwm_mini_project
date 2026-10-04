# MedStock — Synthetic Pharmacy Dataset Generator (v1.0, frozen)

> **This dataset is synthetically generated for the MedStock academic/portfolio DWM project and does not represent actual pharmacy transactions.**

## 1. Purpose

MedStock is a Data Warehousing & Data Mining (DWM) project. This repository currently contains only the
**source-data generation layer**: a reproducible generator that produces realistic, internally consistent
pharmacy operational data (sales, purchases, batches, inventory movements) that a later warehouse / mining
pipeline (star schema, OLAP, association rules, anomaly detection, expiry-risk analysis) will consume.

The dataset is frozen (v1.0). The PostgreSQL warehouse and ETL built on top of it are described in section 13. Not included yet (comes later): API, frontend, mining, ML, dashboards.

## 2. Scope (final dataset, v1.0)

| Item | Value |
|---|---|
| Medicines | 500 (10 fixed categories) |
| Branches | 5 (Mumbai) |
| Suppliers | 30 |
| Period | 2025-01-01 → 2026-12-31 (24 months) |
| Sales lines | ~1.02 M (~613 k transactions), 80 k purchases, 35 k batches |
| `demand_scale` | 0.22 (calibrated; see section 12) |

All sizes come from `DATASET_CONFIG` in [data_generator/config.py](data_generator/config.py).

## 3. Files and fields (`data/raw/`)

| File | Fields |
|---|---|
| `categories.csv` | category_id, category_name |
| `medicines.csv` | medicine_id, medicine_name, category_id, manufacturer, dosage_form, strength, base_price, demand_profile (HIGH/MEDIUM/LOW) |
| `branches.csv` | branch_id, branch_name, city, area |
| `suppliers.csv` | supplier_id, supplier_name, city |
| `batches.csv` | batch_id, medicine_id, supplier_id, manufacture_date, expiry_date, initial_quantity, purchase_price |
| `purchases.csv` | purchase_id, purchase_date, branch_id, supplier_id, medicine_id, batch_id, quantity, unit_purchase_price, total_cost |
| `sales.csv` | transaction_id, transaction_date, branch_id, medicine_id, batch_id, quantity, unit_selling_price, discount, total_amount |

There is intentionally **no inventory table**: inventory is derived as `Σ purchases − Σ sales − expired stock`.
`discount` is an absolute rupee amount per line. All money is in INR.

**Grain of `sales.csv`:** one row = one medicine/batch line sold at one branch within one transaction.
A `transaction_id` repeats once per line (basket), so it can be used for association-rule mining. If a line
is filled from two batches (first-expiry-first-out), it becomes two rows with the same transaction and medicine.

## 4. Relationships

```
categories 1─* medicines 1─* batches *─1 suppliers
branches 1─* purchases *─1 batches          (purchases also carry supplier_id, medicine_id)
branches 1─* sales     *─1 batches          (sales also carry medicine_id)
```

* A batch (manufacturing lot) has exactly one medicine and one supplier.
* A batch is received on one date; it may be delivered to several branches (one `purchases` row per branch).
  `batches.initial_quantity` = sum of that batch's purchase quantities, and `batches.purchase_price` = `unit_purchase_price`.
* A supplier supplies only medicines of the categories it specialises in (1–3 approved suppliers per medicine,
  one of them primary). The mapping is stored in `generation_metadata.json`.
* Purchase date = date the stock is received. There is no separate order/lead-time.

## 5. Data-generation approach

A day-by-day simulation (`data_generator/main.py`):

1. Generate master data: categories (fixed), medicines (curated catalog in `catalog.py`: realistic medicine names, forms and strengths, **fictional manufacturers**; extra strength/manufacturer
   variants are generated if more than the curated list is needed), branches, suppliers.
2. Build the demand model (below).
3. For every day: (a) write off stock reaching its expiry date, (b) run the replenishment policy → purchases + batches,
   (c) generate that day's sales baskets against the branch's actual stock.

**Inventory** lives in a ledger keyed by branch + medicine + batch (`inventory.py`). It only changes through purchases (+),
sales (−) and expiry (−). A sale is filled first-expiry-first-out, never from expired stock, and never exceeds stock
(a line with no stock is dropped as a lost sale; a partly available line is shortened).

**Replenishment, stockouts and expiry (v0.2):** a branch's *inventory position* (on hand + already ordered) is checked daily; below the
reorder point (days of forecast demand, per profile) a lot is ordered up to the target cover, subject to a minimum order quantity (MOQ).
Orders arrive after the supplier's lead time (2–5 days ± 1, 5% chance of an extra 4–10-day delay, plus supply-disruption anomalies); the purchase is recorded
on the arrival date, and day 1 receives immediate opening stock. Reorder point and cover are jittered per medicine (×0.8–1.3). The planner's forecast includes
the extra demand created by the association rules. **Stockouts are not inserted**: they emerge when demand spikes, deliveries are late or a medicine is tightly managed;
lines that find no stock are lost sales. They are discoverable from the CSVs (reconstructed end-of-day stock = 0). **Expiry is not inserted either**: each lot has
manufacture date + shelf life (12–36 months by product; liquids and creams are shorter), a share of lots arrives near-dated (8%, or 45% from "discount" suppliers,
which are also ~5% cheaper), and slow movers have large MOQs. Stock is sold earliest-expiry-first and written off on its expiry date, so high-turnover
medicines almost never expire while slow movers occasionally do. Anomalous bulk purchases are always fresh stock.

**Prices:** selling price = base price ± 3% (fixed per medicine-month); purchase price = base × 0.68–0.85 × supplier factor (≈0.97–1.03);
~12% of lines carry a 5/10/15% discount.

**Reproducibility:** `random_seed` seeds independent per-component RNG streams (`numpy.random.SeedSequence`), so the same
config + seed gives byte-identical CSVs (checked by hashing two runs).

## 6. Demand generation

Each medicine gets internal parameters (stored only in `data/metadata/ground_truth_private.json`):
`base_demand` (by HIGH/MEDIUM/LOW profile, drawn with a skewed Beta inside the profile range for a long-tail volume distribution: ~165× between the busiest and quietest medicine, top 20% of medicines ≈ 52% of units), `demand_variability`, `seasonality` amplitude/peak, `trend`.
Expected sale lines per day for medicine *m* at branch *b*:

```
base_demand(m) × branch_multiplier(b) × branch_category_affinity(b, category(m))
  × day_of_week × (1 + amp(m)·cos(annual cycle)) × exp(trend(m)·t)
```

Realized demand multiplies that by lognormal daily noise (sigma = variability; HIGH is low-noise, LOW is high-noise, chronic
categories are damped) and by any anomaly multiplier. Per branch/day, the number of transactions is Poisson(total demand / average
basket size), and baskets are filled by sampling medicines proportionally to realized demand — so high-demand medicines
appear in many more transactions. Units per line = 1 + Poisson(λ by category; chronic medicines buy more).

**Branches:** BR001 ×1.20 with somewhat higher respiratory demand; BR002 ×0.90 with somewhat higher cardiovascular/antidiabetic
(chronic) demand. Extra branches get random multipliers (0.80–1.25) and 1–2 mildly boosted categories.

## 7. Seasonality

An annual cosine per medicine; amplitude = category amplitude × random 0.6–1.4, peak day = category peak ± 15 days.
Respiratory ≈ ±25% (winter peak), antihistamines ≈ ±18% (spring), antipyretics/antibiotics/GI/dermatological ≈ ±12–15% (monsoon peak,
so they rise gently through Q1), vitamins ±10%, chronic categories ≈ ±2–3%. Small day-of-week effect (weekend higher). Deliberately moderate.
Note: a 3-month window sees only a slice of the annual cycle; seasonality becomes clearly visible at 24 months.

## 8. Association patterns

`ASSOCIATION_RULES` in config lists eight latent co-purchase rules over 15 of the 500 medicines (e.g. Metformin → Glimepiride, Amlodipine → Atorvastatin,
Clotrimazole → Mupirocin). If the antecedent is in a basket and the consequent is not, the consequent is added with probability 0.25–0.45 (never 1.0), chosen
so that P(B | A) is several times P(B | not A). At 500 medicines baseline co-occurrence is very low, so the planted rules show large lifts (21–169) with confidence 0.15–0.44 (see the quality report). Nothing about the rules appears in the
CSVs; the planted rules and their observed statistics are in the private metadata. The quality report also lists the strongest *observed* pairs, including
the reverse direction of each planted rule (same support and lift, different confidence), which a mining algorithm will naturally report.

## 9. Anomalies

About `rate_per_medicine_year` (0.15; 150 events in the final dataset), allocated in proportion to configured weights across five types:
**spike** (×2.5–4, 4–10 days), **drop** (×0.15–0.45, 7–15 days), **branch surge** (one branch ×1.8–2.6, 10–21 days), **bulk purchase** (an order ×3–5 the normal quantity)
and **supply disruption** (deliveries for a medicine delayed by 8–15 extra days, which shows as a long purchase gap and sometimes a stockout).
Demand anomalies are multipliers on the medicine's *own* baseline (including its association-driven demand), so they scale with the medicine. A visibility guard lengthens
the window or raises the multiplier (capped) until the expected deviation is at least 25 sale lines, and targets are chosen in favour of medicines with more volume. Windows for the same
medicine never overlap. Sales and purchases carry **no anomaly flag**. The ground truth (type, medicine, branch, dates, multiplier, purchase ids) and how visible each event is
in the generated data (observed ratio vs the local baseline, z-score, purchase gap) are in `data/metadata/ground_truth_private.json`.

> `data/metadata/ground_truth_private.json` is generator ground truth for evaluating later mining results. It is **NOT** part of the analytical
> dataset and must not be loaded into the warehouse or used as an input feature for analytics/ML.

## 10. Validation (runs automatically, on the CSVs as written)

Primary-key uniqueness and no nulls; referential integrity for every `*_id`; all quantities and prices positive;
`total_cost = quantity × unit_purchase_price`; `total_amount = quantity × unit_selling_price − discount`; purchase/sale medicine and supplier match the
batch; batch quantity = sum of purchases; `manufacture_date < purchase_date < expiry_date`; shelf life 6–36 months; no sale on/after expiry;
purchase price < selling price; one date/branch per transaction; **inventory replay** (purchases before sales on each day, per branch + batch) never
goes negative and every sale draws from a batch received at that branch; purchases − sales = ledger on-hand + expired write-offs;
purchases come from approved suppliers. The CSV-reconstructed closing stock and expired quantity must also equal the generator's ledger. The process exits non-zero if any check fails.

**Dataset quality report** (printed and saved in `generation_metadata.json`; evaluation only, never feeds back into the data): counts, sales totals and top/bottom medicines, stockout events and low-stock share, expired batches/quantity, expiry-risk batches at the end, demand distribution (Gini, top-20% share, ABC counts), revenue by branch, category mix per branch, a month-by-category seasonality index, the strongest observed association pairs (support/confidence/lift) and a check of each planted rule. Soft plausibility **warnings** (not errors) fire e.g. when there are no stockouts/expiries, when they are not rare, when a planted rule is weak or an anomaly is barely visible.

## 11. How to run

```bash
pip install -r requirements.txt
python -m data_generator.main          # run from the repository root
```

Writes `data/raw/*.csv`, `data/metadata/generation_metadata.json` (config, summary, validation results, supplier map) and
`data/metadata/quality_report.json` (full dataset quality report) and `data/metadata/ground_truth_private.json`, and prints a summary and the validation result. A full run takes about 3.5 minutes. `generation_metadata.json` contains no wall-clock timestamp (`frozen_on` is a fixed config label), so reruns are byte-identical.

## 12. Scale, calibration and changing the dataset size

Edit `DATASET_CONFIG` in `data_generator/config.py`: `num_medicines`, `num_branches`, `num_suppliers`, `start_date`, `end_date`, `random_seed`
and **`demand_scale`**. Row volume is linear in `demand_scale` and in the number of medicines. Calibration for the final dataset (500 medicines, 5 branches, 24 months):
scale 0.12 over two months gave ~22.7 k lines/month (~545 k projected); scale 0.22 over the full 24 months gave 1,018,864 lines, and the frozen run gives 1,022,346.
The minimum order quantity shrinks with `demand_scale` (floor `min_moq_units`) and there is a minimum reorder point (`min_reorder_point_units`), so very small
per-medicine volumes do not create artificial stockouts. The profile mix for medicines beyond the curated catalog is HIGH 10% / MEDIUM 30% / LOW 60% (long tail).
Branch/supplier name pools hold 10 / 40 entries; the medicine catalog plus strength/manufacturer variants supports well over 500 medicines.

## 13. Data warehouse and ETL (PostgreSQL star schema)

The frozen raw CSVs are loaded into a star schema in the `warehouse` schema of a PostgreSQL database. Design, grains, additivity and indexing rationale:
[docs/warehouse_design.md](docs/warehouse_design.md). ETL code: [etl/](etl/). SQL: [sql/schema.sql](sql/schema.sql), [sql/validation.sql](sql/validation.sql),
[sql/olap_examples.sql](sql/olap_examples.sql).

**Raw data is immutable.** The ETL only reads `data/raw/` and verifies its checksums before and after. `ground_truth_private.json` and generator-only columns such as
`demand_profile` are never loaded.

### Prerequisites
* Python 3.11+ with `pip install -r requirements.txt` (pandas, numpy, SQLAlchemy 2, psycopg 3, python-dotenv)
* PostgreSQL 14+ (developed on 18) and a database you can create tables in

### Environment variable
`DATABASE_URL` (SQLAlchemy URL; plain `postgresql://...` also accepted). Never hard-code credentials.
Copy `.env.example` to `.env` (git-ignored) and edit it:

```text
DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/medstock
```

### Setup and run
```bash
createdb medstock                      # or: psql -c "CREATE DATABASE medstock"
pip install -r requirements.txt
cp .env.example .env                   # then set DATABASE_URL
python -m etl.pipeline                 # extract, transform, load, reconstruct inventory, validate (~2 min)
```
The ETL is idempotent: each run creates the schema if needed, truncates all warehouse tables and reloads them in one transaction. Nothing is created in the `public` schema.

### Warehouse tables (schema `warehouse`)
| Dimensions | Facts |
|---|---|
| `dim_date` (730 days), `dim_category` (10), `dim_medicine` (500), `dim_branch` (5), `dim_supplier` (30), `dim_batch` (35,477) | `fact_sales` (1,022,346), `fact_purchase` (80,363), `fact_inventory` (1,825,000, derived daily medicine-branch snapshot) |

`fact_inventory` has no source file: it is reconstructed as `opening + purchased - sold - expired = closing` per date, branch and medicine, with stock written off on its batch's expiry date.
It is semi-additive: sum across branches/medicines, never across time.

### Validation
The pipeline runs 75 checks and exits non-zero on any failure (results in `data/metadata/warehouse_validation.json`). To re-run them:
```bash
python -m etl.validation.warehouse_checks
psql -d medstock -f sql/validation.sql        # SQL-only checks (PASS / FAIL / INFO rows)
psql -d medstock -f sql/olap_examples.sql     # sample OLAP queries (roll-up, drill-down, semi-additive inventory, expiry risk)
```
