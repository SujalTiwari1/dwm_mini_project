# MedStock Data Mining Results

> Synthetic data. Associations describe transaction-level co-occurrence, clusters describe observed business behaviour, and anomaly flags are statements about the specified detectors, not proof of anything.

## 1. Association Rules

### Method
Apriori (mlxtend) over transaction baskets. A basket is the set of distinct medicines in one `transaction_id` (the item is the medicine, not the batch). Because baskets with one medicine cannot contain a pair, Apriori runs on the multi-medicine baskets with an absolute-count threshold, and singleton supports come from all transactions, so every metric is exact.

### Parameters
- minimum support 0.0005 (307 of 613,027 transactions), minimum confidence 0.1, lift > 1.0, itemsets up to 3 medicines
- support choice (rules found at each threshold):

| min support | min transactions | frequent itemsets | pairs | useful rules |
|---|---|---|---|---|
| 0.002 | 1227 | 193 | 4 | 8 |
| 0.001 | 614 | 282 | 6 | 12 |
| 0.0005 | 307 | 440 | 24 | 14 |
| 0.0003 | 184 | 700 | 227 | 14 |
| 0.0002 | 123 | 958 | 462 | 14 |

The useful-rule count stops growing at 0.0005: lower thresholds add frequent pairs but no further rules with confidence >= 0.1 and lift > 1, while a higher threshold loses rules.

### Results
- 613,027 transactions, 500 medicines (259,755 transactions contain two or more medicines)
- 440 frequent itemsets {1: 416, 2: 24}, 14 rules generated, 14 useful rules covering 8 distinct medicine pairs (12 rules have the opposite direction as well)

### Top Patterns (one direction per pair, ranked by lift)

| antecedent | consequent | support count | confidence | lift |
|---|---|---|---|---|
| Mupirocin Ointment 2% [MED020] | Clotrimazole Cream 1% [MED019] | 875 | 0.8124 | 168.72 |
| Glimepiride 2mg [MED014] | Metformin 500mg [MED013] | 2555 | 0.5514 | 54.02 |
| Atorvastatin 10mg [MED012] | Amlodipine 5mg [MED011] | 5340 | 0.6596 | 30.15 |
| Domperidone 10mg [MED034] | Omeprazole 20mg [MED033] | 5650 | 0.7473 | 28.6 |
| Vitamin C Chewable 500mg [MED017] | Ambroxol + Levosalbutamol Syrup 100ml [MED015] | 961 | 0.2684 | 25.49 |
| Azithromycin 500mg [MED004] | Paracetamol 650mg [MED005] | 445 | 0.4406 | 24.0 |
| Ambroxol + Levosalbutamol Syrup 100ml [MED015] | Cetirizine 10mg [MED007] | 3037 | 0.4706 | 23.83 |
| Diclofenac 50mg [MED002] | Pantoprazole 40mg [MED009] | 456 | 0.3826 | 21.46 |

### Interpretation
Read `A -> B` as: *transactions containing A were more likely to also contain B*. Lift is the ratio of the observed co-occurrence to the co-occurrence expected if the two medicines were independent. Reverse rules of the same pair share support and lift but have different confidence. The patterns are transaction-level co-occurrence; they are not causal and say nothing about patients.

### Limitations
- With 500 medicines the baseline co-occurrence is very low, so lifts are large (tens to hundreds); the absolute support is small (about 0.07% to 0.9% of transactions).
- Only pairs reached the thresholds: no frequent itemset with three medicines exists at this support.
- Confidence depends on how common the antecedent is. Rely on support count, confidence and lift together.

## 2. Medicine Clustering

### Features
10 features describing behaviour over the 24 months: total_units_sold, avg_selling_price, demand_dispersion, stockout_rate, total_revenue, expired_value, expiry_risk_value, avg_inventory_value, avg_inventory_units, current_inventory_units. All come from SQL aggregation over the warehouse and the existing analytics views.

### Preprocessing
- candidates considered: 26; log1p applied to non-negative features with |skewness| > 1.0: total_units_sold, avg_selling_price, demand_dispersion, inventory_turnover, stockout_rate, days_of_inventory, total_revenue, avg_purchase_cost, expired_value, expiry_risk_value, avg_inventory_value, stockout_event_count, purchase_cost, avg_daily_revenue, avg_weekly_units, avg_daily_units, purchase_units, avg_inventory_units, current_inventory_value, expired_units, weekly_demand_std, current_inventory_units, stockout_days
- redundancy: a feature was dropped when |Spearman r| with an already kept feature exceeded 0.9. Dropped: weekly_demand_cv (~total_units_sold); inventory_turnover (~total_units_sold); days_of_inventory (~total_units_sold); avg_purchase_cost (~avg_selling_price); sales_days (~total_units_sold); stockout_event_count (~stockout_rate); purchase_cost (~total_revenue); avg_daily_revenue (~total_revenue); avg_weekly_units (~total_units_sold); avg_daily_units (~total_units_sold); purchase_units (~total_units_sold); current_inventory_value (~avg_inventory_value); expired_units (~expired_value); zero_sales_days (~total_units_sold); weekly_demand_std (~total_units_sold); stockout_days (~stockout_rate)
- missing values: none
- StandardScaler, then K-Means (`n_init` 20, `random_state` 42). The demand CV and turnover were redundant with volume, so a volume-independent dispersion measure (std / sqrt(mean) of weekly demand) represents variability.

### K Selection

| K | inertia | silhouette | Calinski-Harabasz | Davies-Bouldin | smallest cluster |
|---|---|---|---|---|---|
| 2 | 3493.502 | 0.3302 | 214.75 | 1.2749 | 120 |
| 3 | 2970.118 | 0.1914 | 169.83 | 1.6351 | 97 |
| 4 (selected) | 2527.575 | 0.2201 | 161.73 | 1.3579 | 35 |
| 5 | 2238.566 | 0.2137 | 152.65 | 1.4007 | 35 |
| 6 | 2036.968 | 0.2106 | 143.72 | 1.3182 | 35 |
| 7 | 1856.75 | 0.223 | 139.1 | 1.3186 | 34 |
| 8 | 1733.991 | 0.2317 | 132.38 | 1.2782 | 25 |

K = 2 has the highest silhouette but is a trivial split. The curve is flat for K >= 3, so the rule is the smallest K >= 3 within 0.02 of the best silhouette: K = 4 (silhouette 0.220).

### Cluster Profiles

| cluster | label (derived from centroid) | medicines | share of units | avg units | avg revenue | avg stockout rate | avg days of inventory |
|---|---|---|---|---|---|---|---|
| 0 | high-volume, high-revenue, frequent stockouts | 94 | 67.46% | 11356 | 1186312 | 0.0198 | 15 |
| 1 | high-price | 200 | 17.38% | 1375 | 189158 | 0.0076 | 56 |
| 2 | low-price, low-revenue | 171 | 14.14% | 1309 | 48975 | 0.0088 | 78 |
| 3 | expiry risk, low-volume, low-revenue, expiry write-offs | 35 | 1.01% | 458 | 42444 | 0.0039 | 158 |

### Interpretation
Labels are generated from each centroid's standardised distance on the selected features (|z| >= 0.5), not assigned beforehand. Cluster 0 is always the highest-volume segment.

### Limitations
- Silhouette is low (about 0.2): medicines form a continuum rather than well-separated groups, so boundaries are soft. PCA explains 65% of the variance in two components ([0.4533, 0.193]).
- The smallest cluster is defined mainly by a zero-inflated feature (projected expiry risk) and is best read as 'medicines currently holding stock expected to expire'.
- Observed demand is censored by stockouts and the data is synthetic.

## 3. Anomaly Detection

### Methods
1. **Robust statistics.** Median/MAD modified z-scores on sqrt(x + 3/8) of demand (a variance-stabilising transform for counts): the 7-day level versus the median/MAD of the prior 56 days of 7-day levels, plus single-day spikes versus the prior 28 days; a stockout of 7 or more consecutive days; and, for purchase lots, size per delivered branch, receipt gap and unit cost versus the medicine's prior lots.
2. **Isolation Forest** (200 trees, `random_state` 42) on causal features: robust z (7-day and daily), ratios to rolling median/mean, rolling 7/28-day units, inventory level and its ratio to the prior mean, stockout indicator and run length.

### Features
All rolling quantities for day D use observations up to D only (baselines end before D). The first 70 days are a burn-in and are never flagged. Validation recomputes the features from data truncated at D and requires identical values.

### Results

| detector set | flagged rows | episodes | distinct medicines |
|---|---|---|---|
| statistical | 2,698 | 1,808 | 344 |
| isolation_forest | 6,255 | 3,659 | 450 |
| combined_both_methods | 794 | 578 | 211 |
| either_method | 8,159 | 4,744 | 459 |

### Anomaly Types
A type is assigned only when the observable features support it (half the detection threshold on the relevant feature); otherwise the row is `unclassified`. Types: demand_spike, demand_drop, stockout_pattern, inventory_anomaly (unusually large purchase lot), supply_delay (unusually long gap between receipts), purchase_price_anomaly.

Rows by grain and type (either method): branch_medicine/demand_drop: 291; branch_medicine/demand_spike: 1033; branch_medicine/stockout_pattern: 1245; branch_medicine/unclassified: 3193; medicine/demand_drop: 401; medicine/demand_spike: 304; medicine/unclassified: 451; purchase_lot/inventory_anomaly: 971; purchase_lot/supply_delay: 165; purchase_lot/unclassified: 105

### Evaluation (post-hoc evaluation against synthetic ground truth, NOT model input)
The hidden generator ground truth (150 events: {'spike': 38, 'supply_disruption': 30, 'drop': 30, 'branch_surge': 30, 'bulk_purchase': 22}) was read only after `anomalies.csv` was written.

| detector set | episodes | TP episodes | FP episodes | events detected (strict) | events missed | precision (episode) | recall (strict) | recall (any flag) | F1 |
|---|---|---|---|---|---|---|---|---|---|
| statistical | 1808 | 158 | 1650 | 77 | 73 | 0.0874 | 0.5133 | 0.5533 | 0.1494 |
| isolation_forest | 3659 | 292 | 3367 | 102 | 48 | 0.0798 | 0.68 | 0.7 | 0.1428 |
| combined_both_methods | 578 | 115 | 463 | 63 | 87 | 0.199 | 0.42 | 0.44 | 0.27 |
| either_method | 4744 | 321 | 4423 | 108 | 42 | 0.0677 | 0.72 | 0.74 | 0.1237 |

Per-type results are in `anomaly_evaluation_by_type.csv`.

### Limitations
- Thresholds were fixed before this step and not tuned on the ground truth.
- Precision is conservative: a flag on a medicine whose demand moved because another (planted) medicine moved (a rule-driven knock-on), or a long natural stockout, is real behaviour in the data but not a labelled event, so it counts as a false positive here.
- Detected 'unclassified' episodes are compatible with every event type; they cannot be credited to a specific type.
- Ground truth covers 5 event types; the detectors also report types (stockout_pattern, purchase_price_anomaly) that have no labelled counterpart except through supply disruption.
- A flag means the detector marks the observation as unusual under the specified method. It does not prove that the observation is abnormal.
- Observed demand is censored by stockouts, small-volume medicines are inherently noisy, and the ground truth is synthetic, so the scores describe these detectors on this dataset only.

## 4. Overall Findings

- Association: 14 directional rules over 8 medicine pairs; every pair is a strong, well-supported co-occurrence (lift >= 21.46).
- Clustering: K = 4 segments with a soft structure (silhouette 0.22); the high-volume segment (94 medicines) carries 67.46% of units.
- Anomalies: 8,159 flagged rows in 4,744 episodes; see the evaluation table for how they relate to the planted events.

## 5. Reproducibility

`random_state` = 42 for K-Means, PCA and Isolation Forest; all orderings are explicit. Running `python -m data_mining.run` twice gives identical reports (apart from `run_timestamp` and `runtime_seconds` in `run_summary.json`).

## 6. Data Leakage Controls

- The hidden ground truth is read only by `data_mining/evaluation/evaluate.py`, after detection output exists. Feature, association, clustering and anomaly code never reference it (a static check enforces this).
- Rolling features are causal (validated by recomputing on truncated data). Thresholds were fixed in advance and not tuned on the ground truth.
- Validation: 35 checks, 0 failures.
