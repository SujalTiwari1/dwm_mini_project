# MedStock Demand Forecasting

Branch x medicine demand forecasts for 7, 14 and 30 days on the PostgreSQL warehouse. Design: [docs/ml_forecasting_design.md](../docs/ml_forecasting_design.md). Generated results: [reports/forecasting_summary.md](reports/forecasting_summary.md).

```
ml_forecasting/
  run.py                    python -m ml_forecasting.run   (whole pipeline)
  config.py                 seed, horizons, split dates, grids
  sql/forecasting_data.sql  the dense daily series, segment labels and independent checks
  features/build_features.py   causal feature cube, targets, censoring flags, splits
  models/baselines.py       naive, moving averages, seasonal naive (weekly, yearly)
  models/demand_model.py    HistGradientBoostingRegressor, residual intervals, permutation importance
  evaluation/metrics.py     MAE, RMSE, WAPE, MASE, bias
  validation.py             leakage, split, stockout and output checks
  report.py                 generates forecasting_summary.md from the measured results
  reports/                  forecasts.csv, model_comparison.csv, segment_metrics.csv, feature_importance.csv,
                            forecast_summary.json, forecasting_summary.md, validation_results.json
```

## Run

The warehouse must be loaded (`python -m etl.pipeline`) and `DATABASE_URL` set (see the main README).

```bash
python -m ml_forecasting.run      # exits non-zero if a validation check fails
```

Deterministic (`random_state = 42`). Two runs give identical reports apart from `run_timestamp` and `runtime_seconds` in `forecast_summary.json`.

## Key definitions

* **Origin O** = end of day O. **Features** use data through O (lag_1 = the origin day). **Target** = units sold on days O+1 .. O+h.
* **Splits** are chronological and by target window: training 2025-01-01..2026-06-30, validation 2026-07-01..2026-09-30, test 2026-10-01..2026-12-31. Validation is used for all choices; test is scored once.
* **Censored target:** end-of-day stock was zero on at least one day of the target window. Lost sales are never imputed. Strategy A trains on observed targets, strategy B drops censored windows; both are compared on validation.
* **Baselines** are always reported next to the ML model; a baseline that wins is reported as the winner.

## Not used

No ground truth, no hidden generator information, no external demand data. These are not causal forecasts.
