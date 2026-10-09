# MedStock – Algorithms Used and Things We Can Do

A plain-language guide. MedStock is a pharmacy data project: it makes fake-but-realistic pharmacy data, loads it into a warehouse, analyses it, mines patterns, forecasts demand, and tells you what to do about stock.

---

## Part 1 – Algorithms used in this project

### Pipeline at a glance

```
Data generator OR user upload -> validation -> ETL -> Warehouse (PostgreSQL) -> Analytics (SQL)
                                    |-> Data mining (Apriori, K-Means, anomaly detection)
                                    |-> Demand forecasting (gradient boosting)
                                    '-> Decision support (rules) -> API -> Dashboard
```

### 1. Data generation (`data_generator/`)

| Algorithm | What it does (simple) |
|---|---|
| **Demand model (multiplicative)** | Works out how many sales to expect each day for each medicine and branch. It starts from a base level (high/medium/low demand) and multiplies by: branch size, day of week, season (a cosine wave over the year), long-term trend, and random noise. Some random "spikes" are added on purpose as anomalies. |
| **Reorder-point replenishment** | Every day each branch checks its stock. If stock plus already-ordered stock drops below a limit, it orders enough to reach a target level. Deliveries arrive after the supplier's lead time (2–5 days, sometimes delayed). |
| **FEFO (first-expiry-first-out)** | When a sale happens, the batch that expires soonest is used first. Expired stock is never sold. |
| **Basket generation** | Builds customer baskets (several medicines in one bill), including planted "bought together" pairs so association mining has something to find. |
| **Inventory ledger** | Stock is never stored directly. It is purchases minus sales minus expired stock. |

### 2. ETL (`etl/`)

| Algorithm / technique | What it does (simple) |
|---|---|
| **Extract – Transform – Load** | Reads the CSV files, cleans and reshapes them, and loads them into PostgreSQL. |
| **Star schema** | Facts (sales, purchases, inventory) sit in the middle. Dimensions (date, medicine, branch, supplier, category) are around them. This makes analysis fast and simple. |
| **Surrogate keys** | Each row gets a simple number ID in the warehouse instead of relying on the original IDs. |
| **Warehouse checks** | Counts rows, checks totals and keys match the source. |

### 3. Analytics / OLAP (`analytics/sql/`)

| Technique | What it does (simple) |
|---|---|
| **Aggregation (GROUP BY)** | Totals of revenue, units, and transactions by branch, month, category, etc. |
| **ROLLUP** | Subtotals and grand totals, for example branch -> category -> total in one query. |
| **Window functions** (`RANK`, `ROW_NUMBER`, `SUM() OVER`) | Ranks branches or medicines, finds top N per category, and works out each item's share of a total. |
| **Coefficient of variation (CV)** | Standard deviation divided by average. Shows how stable or unpredictable a medicine's weekly demand is. |
| **Seasonal index** | Compares a month's daily demand with the category's average. Above 1 means a busy month. |
| **Days of cover / days of inventory** | Stock divided by daily sales. How many days the stock will last. |
| **Expiry-risk projection** | Estimates how much of a batch will sell before it expires. Whatever does not sell is "at risk". |
| **OLAP cube operations** (new, `/api/analytics/olap`) | **Slice** (filter on one value), **dice** (filter on several values), **roll-up** (go to a coarser level, such as month -> quarter -> year), **drill-down** (go to a finer level), and **pivot** (one dimension down the rows, another across the columns). Hierarchies: time (year > quarter > month > day), location (city > branch), product (category > medicine). Measures: revenue, units, transactions. The dimension names come from a fixed whitelist and user values are passed as bind parameters, so it is safe from SQL injection. |
| **Views** | Saved queries (low stock, overstock, expiry risk) that other layers reuse. |

### 4. Data mining (`data_mining/`)

| Algorithm | What it does (simple) | Key settings |
|---|---|---|
| **Apriori (association rules)** | Finds medicines that are often bought together, such as "people who buy A also buy B". It reports **support** (how often the pair appears), **confidence** (how often B comes with A), and **lift** (how much more likely than chance). | min support 0.05%, min confidence 10%, lift > 1, up to 3 items |
| **K-Means clustering** | Groups medicines that behave alike (volume, variability, price, expiry, and so on) into clusters. | K tested 2–8; picks the smallest K whose silhouette score is close to the best |
| **StandardScaler + log1p** | Prepares the data so one big-number feature does not dominate. `log1p` shrinks very skewed features. | |
| **PCA (2 components)** | Squashes many features into 2 so the clusters can be drawn on a chart. | |
| **Cluster quality scores** | Silhouette, Calinski-Harabasz, Davies-Bouldin, and inertia. They tell us whether the clusters are tight and well separated. | |
| **Robust z-score (median + MAD)** | Flags a week or day with unusually high or low sales. It uses the median and MAD instead of the mean and standard deviation, so past spikes do not distort the baseline. | cut-off 5 (week) and 6 (day) |
| **Rolling windows (causal)** | All baselines use only past data, so there is no peeking into the future. | 7-day, 28-day, 56-day |
| **Stockout-run rule** | Flags a medicine that has stayed at zero stock for 7 or more days in a row. | |
| **Isolation Forest** | A machine-learning method that finds odd rows. Odd points are easy to "isolate" with random splits. Used on sales series and on purchase lots. | flags the top 0.3% of sales rows and 1% of purchases |
| **Purchase checks** | Flags unusual order size, gap between orders, or unit cost compared with the medicine's own history. | |
| **Post-hoc evaluation** | After detection finishes, results are compared with the hidden "planted anomaly" list to compute precision and recall. This is done last so there is no cheating. | |

### 5. Demand forecasting (`ml_forecasting/`)

| Algorithm | What it does (simple) |
|---|---|
| **Feature engineering** | Builds clues for the model from the past: lags (yesterday, last week), rolling means and medians (7/14/28 days), calendar info, stockout flags. |
| **HistGradientBoostingRegressor** | The main ML model. It builds many small decision trees, each one correcting the previous one's mistakes. One model per horizon: 7, 14 and 30 days. |
| **Loss and target options** | Tries squared error vs. Poisson loss, and raw units vs. `log1p` units. Picks the best on validation data. |
| **Small grid search** | Tries a few parameter sets and keeps the one that scores best on validation. |
| **Baselines** | Simple benchmarks the ML model must beat: **naive** (repeat last period), **moving average 7 / 28**, **seasonal naive** (same weekday last week, or same time last year). |
| **Chronological split** | Train on the past (2025-01 to 2026-06), validate on 2026-Q3, test once on 2026-Q4. Never shuffled. |
| **Censored-demand handling** | If stock hit zero, true demand is unknown. Two strategies are compared: keep those windows, or drop them. |
| **Error metrics** | MAE, RMSE, WAPE (percentage error), MASE (vs. naive), and bias (consistently too high or too low). |
| **Residual-quantile prediction intervals** | Uses the 10th and 90th percentile of past errors to give an approximate 80% range around each forecast. |
| **Permutation importance** | Shuffles one feature at a time and measures how much the error gets worse. Shows which clues matter most. |

### 6. Decision support (`decision_support/`)

These are explainable rules, not black-box ML.

| Algorithm | What it does (simple) |
|---|---|
| **Stockout-risk levels** | Days of cover = stock / expected daily demand. Under 3 days = CRITICAL, under 7 = HIGH, under 14 = MEDIUM, otherwise LOW. It can escalate one step if recent stockouts were frequent or the upper forecast shows trouble. |
| **Safety stock** | `z × daily demand std × sqrt(lead time)`, with z = 1.645 (95% service level). A cushion for uncertain demand. |
| **Reorder point** | Demand during lead time + safety stock. |
| **Order-up-to level and order quantity** | Reorder point + 14 days of demand, minus current stock, rounded up. |
| **Reorder status** | ORDER_NOW, REORDER_SOON, NO_REORDER, NO_DEMAND_DATA. |
| **Overstock rule** | Stock > 0 and (no sales in 30 days, or more than 90 days of cover). Excess value is estimated using the larger of recent demand and forecast demand. |
| **Expiry rule** | Expected sales before expiry = daily demand × days left. Earlier-expiring batches sell first. Unsold units → CRITICAL (expiry within 30 days) or HIGH (within 90 days). |
| **Priority scoring / action queue** | Combines all issues into one list. The worst issue sets the priority (CRITICAL/HIGH/MEDIUM/LOW). A numeric score only orders items inside the same priority. |

### 7. Upload your own data (new, `datasets/`)

Users can now upload their own sales file (and optionally a purchases file) instead of using the demo data. Each upload gets its own dataset and its own PostgreSQL database.

| Algorithm / technique | What it does (simple) |
|---|---|
| **Column mapping suggestion** | Looks at the uploaded file's headers and guesses which column is the date, medicine, quantity, and price. The user can correct it. |
| **Validation and cleaning** | Checks required columns, dates, numbers, and duplicates. Rows that cannot be used are dropped and counted in a report. Nothing is silently invented. |
| **FEFO allocation (replay)** | A sales file does not say which batch was sold. So sales are replayed in date order per branch and medicine, and each sale is filled from the received, non-expired lots with the earliest expiry first (a heap is used to pick the lot). |
| **Implied opening stock** | If sales exceed everything received, a special never-expiring "OPENING" lot is added. It is the smallest amount that keeps stock from going negative. It is an estimate and is shown to the user. |
| **Cost estimation** | For opening stock with no known cost, it uses the medicine's own average purchase cost, or its selling price times the typical cost/price ratio of other medicines. |
| **Capability detection** | Works out what the file allows. Sales only unlocks the dashboard, sales analysis, association rules (needs a bill id) and forecasts (needs 180+ days). Adding purchases unlocks inventory, expiry, clustering, anomalies, and decisions. |
| **Background job queue** | Runs one dataset at a time. Each stage (etl, analytics, association, clustering, anomaly, forecast, decisions) runs in its own process. States go pending -> running -> ok / failed / skipped. |
| **Upload forecasting** (`ml_forecasting/upload_run.py`) | Same gradient boosting model, but with no stockout features. Splits are sized from history length (last ~15% test, 15% before that validation). It uses the demo settings with no new tuning, and it forecasts only the highest-volume branch-medicine pairs. |
| **Upload decisions** (`decision_support/upload_run.py`) | Same decision rules, run on the latest date with that date's forecasts. |
| **Housekeeping and limits** | Datasets are deleted after 14 days by default. Limits: max 10 datasets, max 3 queued jobs, 6 uploads per hour per client (a sliding-window rate limiter). |

### 8. API and dashboard (`api/`, `frontend/`)

| Piece | What it does (simple) |
|---|---|
| **FastAPI routers** | Serve analytics, OLAP, mining results, decisions, dataset upload/status, and dashboard numbers as JSON. |
| **React dashboard** | Pages for Dashboard, Sales (now with an **OLAP Explorer**), Inventory, Risk, Insights, **Forecast**, **Decisions**, and **Upload Data**. |
| **Action queue on the dashboard** | Shows the critical actions with a "Show reason" toggle and a **Complete** button. Completed items are remembered in the browser. |

---|---|
| **FastAPI routers** | Serve analytics, mining results, decisions, and dashboard numbers as JSON. |
| **React dashboard** | Pages for Dashboard, Sales, Inventory, Risk, and Insights, with KPI cards and charts. |

---

## Part 2 – Things we can do (in simple language)

### What the project already does
1. **Generate realistic pharmacy data** – 500 medicines, 5 branches, 2 years of sales, purchases and batches.
2. **Build a warehouse** and load the data into it safely.
3. **Answer business questions** – best-selling medicines, top branches, busy seasons, steady vs. unpredictable demand.
4. **Find medicines bought together** – useful for shelf placement and bundles.
5. **Group medicines by behaviour** – fast movers, slow movers, expensive and risky items.
6. **Spot unusual events** – sudden sales spikes or drops, long stockouts, odd purchase orders.
7. **Forecast demand** for the next 7, 14 and 30 days, with a likely range.
8. **Tell you what to do** – what to reorder and how much, what is overstocked, and which batches to sell first before they expire.
9. **Show it all on a dashboard** through an API.
10. **Explore sales like an OLAP cube** – slice, dice, roll up, drill down, and pivot in the browser.
11. **Upload your own sales and purchases CSVs** and run the whole pipeline on them, with each upload kept separate and cleaned up automatically.
12. **Work through the action queue** – read why an action is recommended and mark it complete.

### Ideas to add next

**Quick wins**
- Add a **CSV/PDF export** of the daily action queue for the store manager.
- Add **filters** (branch, category, date) to every dashboard page.
- Add **email or WhatsApp alerts** for CRITICAL stockouts and batches about to expire.
- Add a **"why" panel** on each recommendation that shows the numbers behind it.

**Analytics**
- **ABC / XYZ classification**: A = top-revenue items, X = steady demand. This tells you where to focus.
- **Supplier scorecard**: delivery delays, price changes, and share of expired stock per supplier.
- **Profit margin analysis**: selling price vs. purchase price by medicine and branch.
- **Discount impact**: do discounts really increase units sold?

**Data mining**
- **Cross-selling recommender**: "customers who bought A should be offered B" using the Apriori rules.
- **FP-Growth** instead of Apriori for faster rule mining.
- **Try other clustering**: DBSCAN, hierarchical clustering, or Gaussian mixtures, and compare with K-Means.
- **Time-series clustering** of demand curves.
- **Branch clustering** – which branches behave alike?

**Forecasting**
- Add **LightGBM / XGBoost**, **Prophet**, or **ARIMA/ETS** and compare them with the current model.
- Add **holiday, weather and disease-season** features (flu, monsoon fevers).
- **Quantile regression** to give proper intervals instead of residual-based ones.
- Handle **new medicines** with little history by borrowing from similar medicines (via clusters).
- **Automatic retraining** on a schedule, plus accuracy monitoring over time.

**Decision support**
- **What-if simulator**: "If lead time becomes 10 days, what happens to stockouts?"
- **Optimal order quantity (EOQ)** and **minimum order quantity** rules.
- **Transfer suggestions** between branches (move surplus from branch A to branch B instead of buying more).
- **Discount suggestions** for items near expiry, to clear them before they are wasted.
- **Return-to-supplier** suggestions for near-expiry stock.
- Optimise a **budget-limited purchase list** – best order mix within a fixed spend.

**Engineering**
- **Scheduler** (cron/Airflow) to run ETL → mining → forecasting → decisions every night.
- **Login and roles** (manager vs. branch staff), which also protects each user's uploaded datasets.
- **More tests and CI** (GitHub Actions) to run the validation checks on every commit.
- **Docker for the whole stack** (API + frontend + database) so it starts with one command.
- **Real data adapter** – partly done: the upload feature already accepts real CSVs. Next steps are support for more file formats (Excel) and a direct connection to a pharmacy billing system.
- **Saving completed actions on the server** – today they are only remembered in the user's browser.
- **Save OLAP views** – let users keep and share favourite cube queries.

### Important limits to remember
- For **uploaded data**, stock is reconstructed (FEFO replay plus an implied opening stock), so inventory numbers are estimates. Forecasts use settings tuned on the demo data, and only the highest-volume pairs are forecast.
- The built-in demo data is **synthetic**, so results show how the methods behave, not real pharmacy facts.
- Association rules show **things bought together, not cause and effect**.
- An anomaly flag means **"unusual"**, not **"proven wrong"**.
- Forecasts are **estimates**; the lead time (7 days), service level (95%) and order cover (14 days) are **assumptions**, not learned from data.
- Recommendations are for **inventory management only**, with no medical advice.
