# MedStock Demand Forecasting: Design

> Source data is synthetic (generated for the MedStock academic DWM project). The models forecast observed unit sales of that synthetic data; they say nothing about real pharmacies.

## 1. Objective
Forecast future medicine demand so inventory decisions can be made before stockouts occur. This layer produces forecasts and their accuracy only. Reorder quantities, purchase orders and supplier recommendations belong to the next
Decision Support phase.

## 2. Forecasting grain
**Branch x medicine x forecast origin day**: 5 branches x 500 medicines = 2,500 series, never pre-aggregated to medicine level, because stock decisions are made per branch. Horizons: **7 days (primary), 14 and 30 days**.
One reusable pipeline (`ml_forecasting/run.py`) is parameterised by the horizon; there are no three separate implementations.

## 3. Target construction
* **Forecast origin O** = the end of day O: everything observed through O is known.
* **Target** `future_units_{h}d` = observed units sold on days **O+1 .. O+h**.
* **Features** use information through O only. `lag_k` = units on day O-k+1 (so `lag_1` is the origin day); rolling windows cover O-w+1 .. O. The first predicted day (O+1) is never inside a feature window.
* Calendar features describe the first predicted day (O+1), which is known in advance and is not leakage.

## 4. Temporal split
Chronological, no random split and no random K-fold. Rows are assigned to a split by where their **whole target window** lies:

| Split | Target days |
|---|---|
| training | 2025-01-01 .. 2026-06-30 |
| validation | 2026-07-01 .. 2026-09-30 |
| test | 2026-10-01 .. 2026-12-31 |

Consequently no target period is shared between splits (for the 30-day horizon the last test origin is 30 days before the end of the data). Validation is used for every selection; test is evaluated once with the final model
(the selected configuration refit on training + validation). The first origin is day 28 (lags and rolling windows need 28 days of history).

## 5. Baseline models
* **naive:** the most recent h days repeated. **moving_average_7 / moving_average_28:** daily mean of the last 7 / 28 days times h.
* **seasonal_naive_weekly:** each future day takes the same weekday of the latest observed week (identical to naive at h = 7).
* **seasonal_naive_yearly:** the same span 364 days earlier. Only 24 months exist, so it is available only for origins from 2025-12-31 onward and rests on a single earlier year; it is not many independent yearly observations.

All models are evaluated on identical rows.

## 6. Feature engineering (`features/build_features.py`)
Built vectorised on [days x pairs] matrices from one SQL result set. 36 features per row:
* lags 1, 2, 3, 7, 14, 21, 28; rolling mean and standard deviation over 7, 14, 28 days; rolling median over 7 and 28 days; a 7/28-day trend ratio;
* stockout context: current stock, stockout flag, stockout in last 7 days (flag and days), stockout days in last 28, days since last stockout (capped), stock-to-demand ratio, and a mean over in-stock days only (a censoring-aware level);
* calendar of the first predicted day: day of week, day of month, month, quarter, week of year, weekend flag, sine/cosine of day of week and month;
* branch and category as categorical features.

No scaling is fitted (trees are scale-invariant). The only transformation is `log1p` on the training target when it is selected.

## 7. Stockout censoring
When end-of-day stock is zero, low or zero sales do not mean low demand. A target window is flagged **censored** if end-of-day stock was zero on at least one of its days (conservative: some such days may not have lost any sales). **Lost sales are never imputed.** Two strategies are compared:

* **A, observed:** train on all observed targets with the stockout features included.
* **B, uncensored:** exclude training rows whose target window is censored.

Both are scored on all validation rows and on uncensored rows only. The selection rule, fixed beforehand, is the lower validation WAPE on uncensored rows at the 7-day horizon, because those rows measure demand without censoring.
The all-rows WAPE and bias are reported next to it. Limitation: censored windows tend to coincide with high demand, so dropping them removes informative periods.

## 8. ML model
`HistGradientBoostingRegressor` (scikit-learn), one direct model per horizon. Loss and target transform are chosen on validation among squared error on raw units, squared error on `log1p(units)` (with `expm1` back-transform, clipped at zero),
and Poisson loss on raw units. No XGBoost, LightGBM or deep learning is used.

## 9. Hyperparameter selection
A small grid of four configurations (learning rate, iterations, leaf count, minimum leaf size, L2) evaluated on the chronological validation split at the 7-day horizon, after choosing the loss/transform with default parameters.
The search trains on every third training origin (consecutive days are near-duplicates); the final models use all rows. The selected configuration is reused for 14 and 30 days.

## 10. Evaluation
* **MAE, RMSE** in units over the horizon; **WAPE** = sum|error| / sum(actual) (stable when actuals are zero; MAPE is not used); **MASE** = MAE / the in-sample naive MAE on the training split (pooled); **bias** = sum(prediction - actual) / sum(actual).
* Reported per horizon for validation and test, for all rows and for uncensored rows, and per segment: volume class (existing FAST/MEDIUM/SLOW mover class), stockout group (lowest/highest quartile of pair stockout rate) and demand variability class (existing analytics view).
  These full-period labels are used only to slice the evaluation, never as features.
* The ML model is not assumed to win: if a baseline is better the report says so.

## 11. Leakage prevention (tested in `validation.py`)
1. Features at a sample of origins are rebuilt from data **truncated immediately after the origin** and must be identical.
2. Features at the same origins must not change when **all later data is replaced by random values**.
3. Targets are recomputed independently and must equal the sum of the h days after the origin; they are undefined when those days are missing.
4. Baseline forecasts at an origin are identical when computed from truncated data.
5. Splits: every target window lies inside its own split period.
6. No fitted scaler or encoder exists; the target transform is applied to training targets only.
7. The hidden ground-truth file is never referenced (static check).

## 12. Uncertainty
An approximate 80 percent band from empirical quantiles (10 percent and 90 percent) of validation residuals (actual - prediction) in five bins of the point forecast (so the band widens with the forecast level).
It is an empirical error band, not a formal probabilistic forecast. Empirical coverage on the test split is measured and reported.

## 13. Limitations
* Observed sales understate demand during stockouts; the strategies reduce but do not remove this. No lost sales are modelled.
* Synthetic data; no patient, prescription, competitor, promotion, epidemiological or weather information, so forecasts are not causal.
* Sparse series: many branch-medicine pairs sell very little, so most of their error is irreducible randomness.
* One earlier year for yearly seasonality; the 30-day test windows only cover origins up to December 1.
* Daily origins overlap, so rows are autocorrelated and the effective sample size is smaller than the row count.
* Segment labels use the full period (descriptive slicing only).

## 14. Reproducibility
`random_state = 42`; the Python version, package versions, model parameters, feature configuration and the split dates are written to `forecast_summary.json`. Running `python -m ml_forecasting.run` twice produces identical reports
apart from `run_timestamp` and `runtime_seconds`.

## Architecture

```
                PostgreSQL Warehouse
                         │
                         ↓
              Forecasting Dataset  (one SQL query, dense daily date x branch x medicine)
                         │
              ┌──────────┴──────────┐
              ↓                     ↓
        Historical Demand      Inventory Context
              │                     │
              └──────────┬──────────┘
                         ↓
                Feature Engineering   (causal; origin-day information only)
                         │
                         ↓
              Temporal Train/Val/Test
                         │
              ┌──────────┼──────────┐
              ↓          ↓          ↓
            Naive    Moving Avg   Seasonal Naive
              │          │          │
              └──────────┼──────────┘
                         ↓
                   ML Model  (HistGradientBoosting; strategy A / B)
                         │
                         ↓
                 Model Evaluation
                         │
                         ↓
                  Forecast Outputs  (forecasts.csv, model_comparison.csv, ...)
                         │
                         ↓
                Future Decision Support
```
