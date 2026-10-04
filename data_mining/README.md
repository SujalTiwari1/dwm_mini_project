# MedStock Data Mining

Association rules, medicine clustering and anomaly detection on the PostgreSQL warehouse (`warehouse` schema). Design and methodology:
[docs/data_mining_design.md](../docs/data_mining_design.md). Generated results: [reports/mining_summary.md](reports/mining_summary.md).

```
PostgreSQL warehouse ──(SQL aggregation: sql/mining_data.sql)──> pandas ──> algorithms ──> reports/
```

```
data_mining/
  run.py                       python -m data_mining.run   (whole pipeline)
  config.py                    seeds and every threshold (all a priori)
  sql/mining_data.sql          basket, feature and daily-series extraction (reuses the analytics views)
  features/build_features.py   loads the SQL result sets
  association/rules.py         Apriori (mlxtend) on transaction baskets
  clustering/medicine_clusters.py   K-Means + PCA on medicine behaviour features
  anomaly/detect.py            robust statistics + Isolation Forest
  evaluation/evaluate.py       POST-HOC evaluation against the synthetic ground truth (the only module that reads it)
  validation.py / validation.sql    checks of every stage
  reports/                     all outputs
```

## Run

The warehouse must be loaded (`python -m etl.pipeline`) and `DATABASE_URL` set (see the main README).

```bash
python -m data_mining.run        # about 5 minutes; exits non-zero if a validation check fails
```

Deterministic: `random_state = 42` for K-Means, PCA and Isolation Forest, explicit sort orders everywhere. Two runs give identical reports except
`run_timestamp` and `runtime_seconds` in `run_summary.json`.

## Data leakage controls

The hidden generator truth `data/metadata/ground_truth_private.json` must never influence the mining. The allowed flow is

```
warehouse data -> feature engineering -> detectors -> anomalies.csv written
                                                          |
                                                          v   (only now)
                                          ground truth -> post-hoc evaluation
```

and the forbidden flow is `ground truth -> feature -> detector`. How this is enforced:

* Only `evaluation/evaluate.py` opens the file, and `run.py` calls it after `anomalies.csv` exists (the evaluation records that the file was read after the detection files were written).
* Feature, association, clustering and anomaly code does not reference the ground-truth path or the evaluation module. `validation.py` checks this statically.
* Thresholds (z cut-offs, windows, contamination budgets, run lengths) are fixed a priori in `config.py` and were not tuned on the ground truth.
* Rolling features for day D use only observations up to D. `validation.py` recomputes them from data truncated at D and requires identical values.
* The association rules and clusters are not evaluated against the ground truth at all.

## Interpretation rules

* `A -> B` means *transactions containing A were more likely to also contain B*. It is transaction-level co-occurrence, not causation, and not patient behaviour.
* An anomaly flag means *the detector marks this observation as unusual under the specified method*, not that the observation is proven abnormal.
* Evaluation numbers are a *post-hoc evaluation against synthetic ground truth*; they describe these detectors on this synthetic dataset only.
