# MedStock Decision Support

Explainable inventory recommendations (stockout risk, reorder, overstock, expiry, unified action queue) built from the warehouse, the analytics definitions and the ML demand forecasts.
Design: [docs/decision_support_design.md](../docs/decision_support_design.md). Generated results: [reports/decision_support_summary.md](reports/decision_support_summary.md).

```
decision_support/
  run.py                    python -m decision_support.run   (whole pipeline)
  config.py                 every threshold and planning assumption (labelled ALIGNED or ASSUMPTION)
  inputs.py                 as-of-date warehouse state (SQL) merged with the ML forecasts of that date
  sql/decision_data.sql     as-of state, live batch lots, and analytics reference queries for reconciliation
  rules/stockout.py reorder.py overstock.py expiry.py
  scoring/priority.py       unified action queue (explicit rules first; numeric score only orders rows)
  validation.py             structure, reconciliation, decision-time leakage, deterministic scenarios
  report.py                 generates decision_support_summary.md from the results
  reports/                  stockout_risk.csv reorder_recommendations.csv overstock_risk.csv expiry_actions.csv action_queue.csv
                            decision_summary.json decision_support_summary.md validation_results.json
```

## Run

Needs the warehouse (`python -m etl.pipeline`), the forecasts (`python -m ml_forecasting.run`) and `DATABASE_URL` (see the main README).

```bash
python -m decision_support.run      # exits non-zero if any validation check fails (about 30 seconds)
```

## Principles
* **Explainable:** every recommendation has evidence fields and a plain-language reason; secondary risks are never hidden; the numeric score only orders rows inside a priority.
* **Decision-time safe:** only information available on the decision date plus forecasts. A historical run (2026-09-30) is validated against an independent recomputation from truncated data.
* **Planning assumptions are explicit:** supplier lead time (7 days), service level (95%), order cover (14 days) are NOT in the data. They live in `config.py`.
* **Inventory management only:** no clinical, prescribing or substitution advice. Exposures are potential exposure / estimates, never actual losses.
* **Upstream layers are not modified.** Where a definition does not reconcile exactly (a 90.0-day boundary in the analytics overstock view) it is reported, not changed.
