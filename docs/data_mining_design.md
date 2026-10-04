# MedStock Data Mining Layer: Design

> Source data is synthetic (generated for the MedStock academic DWM project) and does not represent actual pharmacy transactions.

## 1. Objectives

Discover previously unknown patterns in the warehouse with three mining tasks, plus an evaluation step:

1. **Association rules:** which medicines tend to occur together in the same transaction.
2. **Medicine clustering:** segments of medicines with similar demand, inventory, stockout, expiry and cost behaviour.
3. **Anomaly detection:** unusual operational behaviour in demand, stock and purchasing.
4. **Evaluation:** a post-hoc comparison of the anomaly detectors with the synthetic generator's hidden ground truth.

Out of scope here: forecasting, any ML demand prediction, API, dashboard.

## 2. Architecture

```
PostgreSQL Warehouse
        │
        ├── Transaction Basket Data (transaction -> set of medicines)
        │            ↓
        │      Association Rules (Apriori)
        │
        ├── Medicine Feature Matrix (500 x features, built in SQL)
        │            ↓
        │      K-Means (+ PCA projection)
        │
        └── Time-Series / Operational Features (date x branch x medicine, purchase lots)
                     ↓
            Statistical Detection (median / MAD robust z)
                     +
              Isolation Forest
                     ↓
                  Anomalies  (anomalies.csv)
                     ↓
         Post-hoc Ground Truth  (read only here)
                     ↓
                 Evaluation
```

SQL does the extraction and aggregation (baskets, medicine features, daily series); Python does the algorithms (`mlxtend`, `scikit-learn`, `scipy`, `pandas`).

## 3. Input data

| Data set | Grain | SQL (`data_mining/sql/mining_data.sql`) | Used by |
|---|---|---|---|
| baskets | (transaction, medicine) | distinct pairs from `fact_sales` | association |
| medicine features | medicine | aggregates reusing `v_medicine_performance`, `v_current_inventory`, `v_stockout_summary`, `v_expiry_risk`, `fact_inventory`, `fact_purchase` | clustering |
| daily series | date x branch x medicine (1.825M rows) | `fact_inventory` (units sold, closing stock) joined to `fact_sales` revenue | anomaly |
| purchase lots | received batch | `fact_purchase` grouped by batch | anomaly |

Nothing is read from the raw CSVs or from generator metadata. `data/metadata/generation_metadata.json` (public descriptor) is used only to report the dataset version.

## 4. Association mining

* **Baskets.** A basket is the set of distinct medicines in one `transaction_id`. The item is the medicine, never the batch, branch or key, and a medicine split over two batches counts once.
  613,027 transactions, 500 medicines, 259,755 baskets with two or more medicines.
* **Algorithm.** `mlxtend` Apriori, rules by `association_rules`, with support, confidence, lift, leverage and conviction, plus `support_count`.
* **Scale handling.** mlxtend's Apriori densifies the candidate matrix (about 20 GB here). A one-medicine basket cannot contain a pair, so Apriori runs (low-memory mode) on the multi-medicine baskets with the support
  threshold converted to an absolute transaction count; singleton supports are taken from all transactions. Counts of itemsets of size two or more are identical to counts over all transactions, so all metrics are exact
  (and every rule's counts are re-counted in the warehouse with SQL during validation).
* **Thresholds.** The minimum support is chosen from a sensitivity table written to `association_summary.json` (supports 0.002 to 0.0002): the number of useful rules saturates at 0.0005 (307 transactions), so lower
  thresholds only add frequent pairs without further rules. Minimum confidence 0.10, lift > 1.
* **Filtering.** Self-rules are excluded (none can arise: sides are disjoint by construction); rules are sorted by lift, confidence, support. The opposite direction of a pair is kept as a separate rule (different confidence) and
  flagged `reverse_rule_present`; the summary lists one direction per pair.
* **Interpretation.** `A -> B`: transactions containing A were more likely to also contain B. Transaction-level co-occurrence; not causation; not patient behaviour.

## 5. Clustering

* **Features** (`medicine_features` SQL): volume (`total_units_sold`, `avg_daily_units`, `sales_days`, `zero_sales_days`), revenue, demand variability (weekly CV and a volume-independent dispersion `std / sqrt(mean)`),
  inventory (average and current units and value, turnover, days of inventory), stockouts (days, rate, events), expiry (expired units/value, risk value), purchasing (units, cost, average unit cost), average selling price.
* **Preprocessing.** (1) missing values (`days_of_inventory` is NULL when there is no recent demand: capped at 365); (2) `log1p` on non-negative features with |skewness| > 1;
  (3) redundancy removal: features are taken in a documented priority order and a feature is dropped if its |Spearman r| with an already kept feature exceeds 0.90 (the dropped features and their partners are listed in `cluster_preprocessing.json`);
  (4) `StandardScaler`.
* **K-Means.** `n_init` 20, `random_state` 42. K = 2..8 are evaluated with inertia, silhouette, Calinski-Harabasz and Davies-Bouldin (`cluster_evaluation.csv`).
* **Choosing K.** K = 2 is a trivial high/low split and the silhouette curve is flat for K >= 3, so the rule is the smallest K >= 3 whose silhouette is within 0.02 of the best. The aim is interpretable segments, not the arbitrary maximum.
* **Labels** are derived from each cluster's standardised centroid (features with |z| >= 0.5), never assigned beforehand. Cluster ids are ordered by mean units sold (0 = highest volume), which makes the output stable.
* **Projection.** PCA(2) on the standardised matrix (`cluster_projection.csv`) for later visualisation.
* **Finding to know:** demand CV and turnover are strongly correlated with volume (Spearman about 0.96 each; with Poisson-like demand the CV of a slow medicine is mostly sampling noise), so they are dropped as redundant and variability enters through the dispersion measure.

## 6. Anomaly detection

### 6.1 Grains and signals
* **date x branch x medicine** (2,500 series) and **date x medicine** across branches (500 series): daily units, revenue, closing stock, stockout indicator.
* **Purchase lots** (35,477 received batches): lot size per delivered branch, gap since the previous receipt of the medicine, unit cost.

### 6.2 Method 1: robust statistics
* Counts are transformed with `y = sqrt(x + 3/8)` (variance-stabilising), so one threshold suits slow and fast medicines. With the plain Poisson scale a single six-unit sale in a slow series looked extreme, which made
  the first version flag far too much; the transform fixes the cause.
* **Level z (7 days):** `y` of the units in the last 7 days versus the median and MAD of the 7-day levels of the previous 56 days (windows that end before the current window). `z = (y - median) / max(1.4826 MAD, 0.5)`.
  Flag when |z| >= 3.5 (modified z-score, Iglewicz and Hoaglin) and the change is at least 5 units.
* **Daily spike:** the same z on the day versus the prior 28 days, threshold 4.0.
* **Stockout pattern:** 7 or more consecutive days with zero stock (flagged on the seventh day).
* **Purchase lots:** lot size per delivered branch, receipt gap and unit cost versus the medicine's prior lots only (needs at least 8 prior lots): size z >= 3.5 and at least 2.5x the prior median; gap z >= 3.5 and at least 2x the prior median gap;
  unit cost z >= 3.5 and at least 25 percent away from the prior median.

### 6.3 Method 2: Isolation Forest
`IsolationForest` (200 trees, `max_samples` 4096, `random_state` 42) on causal features: 7-day and daily robust z, ratios of units to the rolling median/mean, rolling 7/28-day units, inventory level and its ratio to the prior mean,
stockout indicator and run length (for purchase lots: size, gap and cost z-scores and ratios, branches delivered). The isolation score is `-score_samples` (higher = more isolated); the flag is the top 0.3 percent of rows (1 percent of purchase lots).
These are operating budgets, not estimates of the true anomaly rate.

### 6.4 Combination
`is_statistical_anomaly`, `is_isolation_anomaly` and `combined_anomaly` (flagged by both) are all kept in `anomalies.csv`, which holds every row flagged by at least one method. Consecutive flags of one series are grouped into **episodes**
(gap <= 3 days) for counting and evaluation.

### 6.5 Anomaly types
A type is assigned only when the observable features support it (half the detection threshold on the relevant feature): `demand_spike`, `demand_drop`, `stockout_pattern`, `inventory_anomaly` (unusually large lot), `supply_delay`
(unusually long receipt gap), `purchase_price_anomaly`; otherwise `unclassified`. The detector outputs are kept alongside.

### 6.6 No future leakage
Every rolling baseline for day D ends before D, and the first 70 days (burn-in) are never flagged. `validation.py` recomputes the feature functions from data truncated at D and requires identical values at D.

## 7. Evaluation (post-hoc)
`evaluation/evaluate.py` reads `ground_truth_private.json` only after `anomalies.csv` exists. A ground-truth event is a window for one medicine (and one branch for a branch surge); flags count if they fall inside the window plus the detector's
6-day lag (supply disruptions get `extra_lead_days + 14` days because deliveries are delayed; a bulk purchase is matched to the receipt date of its purchase lines +/- 1 day).
* **Recall** is per event, strict (a flag of a compatible detected type) and any-flag (any flag for the medicine in the window).
* **Precision** is per detected episode: true positive if it overlaps a compatible event window of the same medicine ("unclassified" episodes are compatible with every type).
* TP, FP, FN and precision, recall, F1 are reported for statistical, Isolation Forest, both-methods and either-method sets, and per type (`anomaly_evaluation_by_type.csv`).

## 8. Leakage prevention
Allowed: `warehouse data -> feature engineering -> detectors -> predictions -> ground truth -> evaluation`. Forbidden: `ground truth -> feature -> detector`. Enforced by: a single reading module, call order in `run.py`,
a static source check in validation, fixed a-priori thresholds, causal features checked by truncation, and no ground-truth evaluation of the association and clustering results.

## 9. Reproducibility
`random_state` = 42 for K-Means, PCA and Isolation Forest, explicit sort orders, deterministic SQL ordering. Two consecutive runs produce identical reports (except `run_timestamp` and `runtime_seconds`).

## 10. Limitations
* Observed demand is censored on stockout days; small-volume medicines are inherently noisy; demand has trend and seasonality that a 56-day baseline only partly absorbs.
* Rules describe co-occurrence only; at 500 medicines lifts are large because baseline co-occurrence is tiny.
* Clusters overlap (low silhouette), so boundaries are soft; the expiry-risk segment is driven by a zero-inflated feature.
* Precision against the synthetic labels is conservative: movements caused by a labelled event (for example a rule-driven knock-on to another medicine) or long natural stockouts are real in the data but unlabelled.
* Purchase prices vary by supplier and lot; no purchase-price anomalies are planted, so any detected price deviation is a false positive by construction.
* The ground truth is synthetic: scores describe these detectors on this data, not real pharmacy operations.

## 11. How to read the results
* Rule: transactions containing A were more likely to contain B (support count, confidence, lift together).
* Cluster: a segment of medicines that behaved similarly over 24 months; the label is a description of its centroid.
* Anomaly: the detector flags this observation as unusual under the stated method; it is a candidate for review, not a verdict.
