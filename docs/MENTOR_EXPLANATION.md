# MedStock — Project Explanation Guide (for mentor presentation)

**MedStock: Pharmacy Inventory Intelligence & Demand Analytics System** — a Data Warehousing & Data Mining (DWM) mini project.

---

## 1. The project in 30 seconds

> A pharmacy chain loses money in two opposite ways: **running out** of medicines (lost sales, unhappy patients) and **holding too much** (cash locked up, stock expiring). MedStock is an end-to-end system that takes raw sales/purchase data, builds a **data warehouse**, analyses it with **OLAP**, discovers patterns with **data mining**, predicts future demand with **machine learning**, and finally converts everything into a prioritised list of **"what should the pharmacy do today?"** actions, shown on a web dashboard.

One-line pipeline:

```
Synthetic data → ETL → Data Warehouse (star schema) → OLAP/Analytics → Data Mining → ML Forecasting → Decision Support → REST API → React Dashboard
```

---

## 2. Dataset — size and structure

| Item | Value |
|---|---|
| Branches | 5 (Mumbai) |
| Medicines | 500 (10 categories) |
| Suppliers | 30 |
| Period | 1 Jan 2025 – 31 Dec 2026 (24 months, 730 days) |
| Sales lines | **1,022,346** (~613,027 transactions / baskets) |
| Purchases | 80,363 |
| Batches (lots with expiry) | 35,477 |
| Daily inventory snapshots | **1,825,000** (730 days × 5 branches × 500 medicines) |
| Branch–medicine pairs analysed | 2,500 |

Raw files (`data/raw/`): categories, medicines, branches, suppliers, batches, purchases, sales. There is **no inventory file by design** — inventory is *derived* as purchases − sales − expired stock, exactly like a real system would reconstruct it.

---

## 3. Why synthetic data? (the question you will be asked)

**Short answer:** Real pharmacy transaction data is private/commercial and not publicly available at this scale. A DWM project needs *large, clean, relational, time-stamped* data with batches, expiry dates and multiple branches. So we generated it.

**Detailed reasons**

1. **Availability & privacy** – real pharmacy sales/patient data is confidential; public datasets don't have batch-level stock, expiry, suppliers and branches together.
2. **We know the ground truth** – because we planted the patterns, we can *scientifically evaluate* our mining and ML. For example, we planted 150 anomaly events and 8 co-purchase rules, then checked how many the algorithms recovered. With real data you can never be sure what "the right answer" is.
3. **Controllability** – we can calibrate size (1 M rows), seasonality, stockouts, expiry and supplier delays so every module of the course (warehouse, OLAP, association rules, clustering, anomaly detection, forecasting) has meaningful material to work on.
4. **Reproducibility** – a fixed random seed gives byte-identical CSVs, so results can be re-run and verified by anyone (mentor included).
5. **Realistic, not random** – the generator is a day-by-day simulation, not random numbers:
   - demand = base demand × branch factor × category affinity × day-of-week × annual seasonality × trend × noise
   - skewed volumes (top 20 % of medicines ≈ 52 % of units; ~165× gap between busiest and slowest medicine)
   - replenishment with reorder points, MOQs, supplier lead times (2–5 days + random delays)
   - FEFO selling (first-expiry-first-out), expiry write-offs
   - stockouts and expiry **emerge naturally** from the simulation; they are not inserted by hand
6. **Honest disclosure** – the data is clearly labelled synthetic everywhere in the code, reports and UI. We make **no claim** that results apply to real pharmacies. The *methodology and system* are the contribution; with real data, only the input CSVs change.

**If asked "Then are your results meaningless?"**
> No. The results show that the *pipeline works correctly end to end* and that the methods recover known structure. Model accuracy numbers are valid for this dataset only; deploying on a real pharmacy would need re-training on real data, and we state this limitation openly.

**Safeguard against cheating:** the hidden generator parameters (`ground_truth_private.json`) are never used as features. They are read only *after* detection to score the anomaly detectors, and an automatic static check enforces this.

---

## 4. Layer-by-layer explanation

### 4.1 Data Warehouse & ETL (PostgreSQL, star schema)
- **ETL**: Extract CSVs → Transform (clean, keys, derive inventory) → Load into PostgreSQL (Docker) → Validate.
- **Star schema**: 
  - Dimensions (6): `dim_date` (730 rows), `dim_category` (10), `dim_medicine` (500), `dim_branch` (5), `dim_supplier` (30), `dim_batch` (35,477).
  - Facts (3): `fact_sales` (1,022,346 rows), `fact_purchase` (80,363), `fact_inventory` (1,825,000 – periodic snapshot).
- Declared grains, composite keys and indexes; ETL validation checks reconcile row counts and totals.

### 4.2 Analytics + OLAP
- 7 SQL views, 8 query files, **37 reconciliation checks**.
- Covers: sales KPIs, year-over-year growth, category/branch/medicine performance, stock status, inventory turnover, days of inventory, fast/slow movers, expiry risk, stockouts, demand variability, seasonality.
- OLAP operations: **roll-up, drill-down, slice, dice, pivot**.

### 4.3 Data Mining (3 techniques) — 35 validation checks, 0 failures

| Technique | Algorithm | Result |
|---|---|---|
| **Association rules** | Apriori (mlxtend), min support 0.0005, min confidence 0.1, lift > 1 | 613,027 baskets → 440 frequent itemsets → **14 rules / 8 medicine pairs**. Strongest: Mupirocin → Clotrimazole (lift 168), Glimepiride → Metformin (confidence 55 %, lift 54), Atorvastatin → Amlodipine (lift 30) |
| **Clustering** | K-Means (K = 4, log-transform + standard scaling, 10 features); K chosen with silhouette, Calinski-Harabasz, Davies-Bouldin | 4 segments: high-volume (94 medicines = **67 % of all units**), high-price (200), low-price (171), expiry-risk (35). Silhouette ≈ 0.22 |
| **Anomaly detection** | Robust statistics (median/MAD modified z-score) + **Isolation Forest** (200 trees) | 8,159 flagged rows / 4,744 episodes. Combined detector precision 0.20, "either method" recall **0.72** against 150 planted events |

*Be honest about these:* clustering silhouette is low (medicines form a continuum, not tight groups); anomaly precision is low because many natural events (long stockouts, knock-on effects) are real but not "labelled", so they count as false positives. Recall is the stronger result.

### 4.4 Machine Learning — Demand Forecasting
- **Goal**: forecast units demanded for each of the 2,500 branch–medicine pairs for the next **7, 14 and 30 days**.
- **Model**: `HistGradientBoostingRegressor` (scikit-learn gradient boosting), one model per horizon; `log1p` target transform; learning rate 0.05, 300 iterations, 63 leaves; seed 42.
- **Features (36)**: lags (1–28 days), rolling mean/std/median (7, 14, 28 days), trend ratio, stockout context (current stock, days since last stockout…), calendar (day of week, month, sine/cosine), branch and category.
- **Validation – no data leakage**: strictly **chronological** split, no random K-fold.
  - Train: 1 Jan 2025 – 30 Jun 2026
  - Validation: Jul – Sep 2026 (hyper-parameter and strategy choice)
  - Test: Oct – Dec 2026 (used **once**, at the end)
  - 7-day horizon: 1,277,500 train / 215,000 validation / 215,000 test rows.
- **Stockout censoring**: when stock is zero, low sales ≠ low demand. We compared training on all data vs. excluding stockout windows (differed by < 1 %) and never invented "lost sales".
- **Metrics**: MAE, RMSE, **WAPE** (= Σ|error| / Σactual, the main one), MASE, bias. (MAPE not used because actual demand is often zero.)

**Test-set accuracy (Oct–Dec 2026)**

| Horizon | ML model WAPE | ML MAE (units) | Best baseline | Baseline WAPE | Improvement |
|---|---|---|---|---|---|
| 7-day | **0.3905** (~61 % accurate) | 2.40 | 28-day moving average | 0.4031 | ~3 % |
| 14-day | **0.2983** (~70 %) | 3.67 | 28-day moving average | 0.3148 | ~5 % |
| 30-day | **0.2310** (~77 %) | 6.09 | naive | 0.2493 | ~7 % |

- "Accuracy ≈ 1 − WAPE" is only an informal reading. WAPE is the formal metric — say *error*, not "accuracy %", to be safe.
- Baselines compared: naive, moving average (7/28), seasonal-naive (weekly/yearly). ML beats all of them **at every horizon**, but the margin is modest — and we say so.
- Accuracy depends strongly on volume: **fast movers WAPE 0.27**, medium 0.55, slow movers ≈ 0.99 (very low sales are mostly random noise – no model can fix that).
- **Prediction interval**: approximate 80 % band from validation residuals; measured test coverage **80.4 %** (so the band is well calibrated).
- Top drivers (permutation importance): 28-day rolling mean (with and without stockout days), current inventory, 7/14-day rolling means.
- **Known limitation (state it before the mentor finds it):** the model under-forecasts totals by ~11 % (7-day), ~9 % (14-day), ~7 % (30-day), because the log-transform favours a median-like value. This is documented, the selection rule was fixed in advance (not changed after seeing results), and it is why the decision layer uses recent demand together with the forecast.
- 24 validation checks, 0 failures. Fully reproducible.

### 4.5 Decision Support (rule-based, deliberately NOT ML)
Turns forecasts + inventory + expiry into actions. Rules are transparent and explainable, so management can trust them.

**Assumptions (documented, not in the data):** decision date 31 Dec 2026; supplier lead time 7 days; 95 % service level (z = 1.645); each order covers 14 days beyond lead time; no MOQ; no open orders.

**Reorder logic**
- Safety stock = z × daily demand std × √lead time
- Reorder point = lead-time demand + safety stock
- `ORDER_NOW` if stock ≤ lead-time demand; `REORDER_SOON` if below reorder point; else `NO_REORDER`
- Order quantity = ⌈reorder point + 14 days demand − stock⌉

**Other rules:** stockout severity from days of cover (cut-offs 3/7/14 days, escalated by recent stockout history); overstock = more than 90 days of cover; expiry risk = FEFO-aware projection of unsold units per batch (CRITICAL/HIGH → `PRIORITIZE_SALE`).

**Output on the dated run (31 Dec 2026), 2,500 branch–medicine pairs**

| Priority | Count |
|---|---|
| CRITICAL | 79 |
| HIGH | 352 |
| MEDIUM | 367 |
| LOW | 1,702 |

- **171** pairs "Order Now", **280** "Reorder Soon", 2,049 no reorder; **14,431** units recommended in total
- **593** overstocked pairs (≈ 2,867 excess units, est. ₹2.1 lakh)
- Potential stockout exposure ≈ ₹1.1 lakh; projected expiry exposure ≈ ₹25 thousand
- 5,500 batch lots assessed for expiry → 40 critical, 19 high
- **75 validation checks, 0 failures**; exposures are labelled *estimates, not realised losses*.

### 4.6 API & Dashboard
- **FastAPI** (read-only REST, Swagger docs): serves warehouse queries and the stored reports; never retrains models or re-applies rules.
- **React + Vite + Tailwind + Recharts** dashboard, 7 pages: Dashboard, Sales, Inventory, Forecast, Risk & Expiry, Data Mining Insights, **Decision Support** ("What should the pharmacy do now?").

---

## 4.7 Bonus: "Upload your own data"

The system is not tied to the synthetic dataset. A user uploads a sales CSV (and optionally a purchases CSV); each upload gets its **own database and report folder**, and the same pipeline runs in the background with a live progress screen.

- **Sales only** -> sales analytics/OLAP, association rules, demand forecasting (needs 180+ days).
- **Sales + purchases** -> also inventory, expiry risk, clustering, anomaly detection and the full decision-support queue.
- **Stock is rebuilt, not invented:** sales are replayed per branch and medicine and filled from received, non-expired lots earliest-expiry-first (FEFO). Anything sold without a matching purchase becomes an *estimated opening stock* that is shown to the user as a warning.
- **Safe by design:** column-mapping step, validation with plain-language errors, CSV-only/size/row limits, upload rate limit, automatic deletion after 14 days, the demo dataset can never be deleted.
- **Honest limits:** forecasting for uploads uses the demo's model settings without tuning and ignores stock; decisions are only as good as the purchases file.
- **Validated:** on a slice of the demo data (700,000 sales, 56,000 receipts) the rebuilt stock reproduced the demo's expired-unit count exactly (2,455).

**Extra mentor question - "How would this work on a real pharmacy?"** Export sales and purchase receipts as CSV, upload them, map the columns, and read the results; no code changes. The quality of the stock-based decisions depends on how complete the purchases file is.

---

## 5. Tech stack

Python 3.11 · pandas · NumPy · scikit-learn 1.4 · mlxtend (Apriori) · SQL (PostgreSQL 18 in Docker) · SQLAlchemy / psycopg · FastAPI + Uvicorn · pytest · React · Vite · Tailwind CSS · Recharts.

---

## 6. Why this is a *DWM* project (map to syllabus)

| DWM concept | Where |
|---|---|
| Data generation / preprocessing | `data_generator/`, ETL transform |
| ETL | `etl/` |
| Star schema, facts, dimensions, grain, indexing | `sql/schema.sql`, `docs/warehouse_design.md` |
| OLAP (roll-up, drill-down, slice, dice, pivot) | `analytics/`, `sql/olap_examples.sql` |
| Association rules (Apriori) | `data_mining/association/` |
| Clustering (K-Means) | `data_mining/clustering/` |
| Outlier / anomaly detection | `data_mining/anomaly/` |
| Prediction (supervised learning) | `ml_forecasting/` |
| Knowledge presentation / decision support | `decision_support/`, `api/`, `frontend/` |

---

## 7. Likely mentor questions and strong answers

**Q1. Why synthetic data?** See section 3 — privacy/availability, known ground truth for honest evaluation, controllable and reproducible; clearly disclosed.

**Q2. Isn't a model trained on synthetic data cheating?**
The generator simulates demand with seasonality and noise; the model sees only *observed sales and stock*, never the hidden parameters. Hidden ground truth is used only for post-hoc scoring. The model's accuracy is real for this dataset; transfer to real data would need retraining.

**Q3. Why gradient boosting and not LSTM/ARIMA/Prophet?**
We forecast 2,500 sparse, intermittent series together. One global tree model with lag/rolling/calendar/stockout features handles this well, trains in minutes on a laptop, is explainable (feature importance) and handles categorical branch/category naturally. Per-series ARIMA would need 2,500 models; deep learning is overkill for a 24-month, low-count dataset. We compared against five baselines to prove the added value.

**Q4. Your error is 39 % at 7 days — isn't that bad?**
It is dominated by slow-moving medicines that sell 0–2 units a week (random). On fast movers the error is 27 %, and at 30 days 23 %. Honest framing: improvement over baselines is modest because the synthetic demand has a large random component that no model can predict. The 80 % interval is correctly calibrated (80.4 %).

**Q5. Why is the model biased low?**
`log1p` target transform optimises a median-like value. We detected it at validation and documented it rather than silently changing the rule after seeing the test. Decision support uses recent demand + forecast to stay conservative.

**Q6. How do you prevent data leakage?**
Chronological split by target window, features use only data up to the forecast origin, test set used once, hyper-parameters selected on validation only, ground truth never an input, rolling anomaly features recomputed on truncated data in the validation checks.

**Q7. How do you handle stockouts hiding true demand (censoring)?**
Stockout flags and history are features; we compared training with and without censored windows; we never impute lost sales.

**Q8. Why rule-based decision support instead of ML?**
Inventory policy (reorder point, safety stock, service level) is a well-established, explainable method. Management must understand *why* an order is recommended. ML provides the demand input; the rules convert it to actions.

**Q9. What do exposure numbers mean?**
Potential impact (revenue not served or cost of stock that might expire) — estimates, never realised losses.

**Q10. Association rule lifts are 20–170 — suspicious?**
With 500 medicines, random co-occurrence is tiny, so any planted pair has very high lift. It is expected; we planted 8 rules and recovered all 8 pairs.

**Q11. Why only 4 clusters / low silhouette?**
Chosen by a pre-defined rule (smallest K ≥ 3 within 0.02 of best silhouette). K = 2 scores highest but is a trivial split. Medicines form a continuum, so boundaries are soft — and we state it.

**Q12. Anomaly precision is only 20 %.**
Flags on natural but unlabelled events (long stockouts, knock-on effects of association rules) are counted as false positives, so precision is a conservative lower bound. Recall of 72 % shows planted events are found. Thresholds were fixed before looking at ground truth.

**Q13. What would change on real data?**
Only the source CSVs: ETL → warehouse → analytics → mining → ML → decisions re-run unchanged. We would re-tune and re-validate models, replace assumed lead time/service level with real values, and add promotions/epidemic/price signals.

**Q14. Limitations?**
Synthetic data; only 24 months (one earlier year for yearly seasonality); no external drivers (weather, epidemics, prescriptions); lead time, service level and order cover are assumptions; no supplier constraints; slow-mover demand is inherently unpredictable; forecast bias on totals.

**Q15. Future work?**
Real data integration, bias correction / Poisson-loss variant, hierarchical forecasting, probabilistic forecasts, supplier-specific lead times, automatic purchase-order generation, user authentication, live data refresh.

---

## 8. How to run (for a live demo)

```bash
docker start medstock-postgres                 # PostgreSQL on port 5433
uvicorn api.main:app --reload                  # API  → http://127.0.0.1:8000/docs
cd frontend && npm run dev                     # UI   → http://localhost:5173
```

Pipelines (already executed; re-run only if asked):
`python -m etl.pipeline` → `python -m analytics.run` → `python -m data_mining.run` → `python -m ml_forecasting.run` → `python -m decision_support.run`

**Suggested demo order (5 minutes):** Dashboard (big picture) → Sales/Inventory (OLAP) → Insights (mining) → Risk → **Decisions** (the final answer: "what should we do now?").

---

## 9. Closing statement

> "MedStock demonstrates the complete knowledge-discovery chain taught in DWM — from raw data to a warehouse, from OLAP to mining and prediction, and finally to an actionable decision interface. Every layer is validated (24–75 automated checks each, 0 failures), reproducible, and honest about its limitations. The data is synthetic by necessity, but the system is designed so real pharmacy data can be dropped in."
