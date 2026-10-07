# MedStock Demand Forecasting

> Synthetic data. The models forecast *observed unit sales* of a synthetic pharmacy dataset. They do not model causes of demand and make no claim about real pharmacies.

## 1. Objective

Forecast future demand for each medicine at each branch, so that inventory decisions can be made before stockouts occur. This layer produces forecasts only; reorder quantities and purchase recommendations belong to the later Decision Support phase.

## 2. Forecasting Grain

One forecast per **branch x medicine pair** (2500 pairs = 5 branches x 500 medicines) per **forecast origin day**. Forecasts are not aggregated to medicine level, because branch-specific demand drives inventory planning.

## 3. Forecast Horizons

7 days (primary), 14 days and 30 days. One reusable pipeline fits a direct model per horizon (target = total units over the next h days). The 7-day horizon drives model selection; the same configuration is then applied to 14 and 30 days.

## 4. Dataset Construction

One SQL query returns the dense daily series (date x branch x medicine: units sold, revenue, end-of-day stock) from the warehouse; features, targets and splits are built vectorised in pandas/numpy.
- **Forecast origin** O = end of day O. Features use data through O. **Target** `future_units_hd` = observed units sold on days O+1 .. O+h (strictly after O).
- **lag_k** = units on day O-k+1, so lag_1 is the origin day. Rolling windows cover O-w+1 .. O. The first predicted day O+1 never enters a feature.
- **Splits are chronological** and assigned by where the whole target window lies: training 2025-01-01 to 2026-06-30, validation 2026-07-01 to 2026-09-30, test 2026-10-01 to 2026-12-31. No target period is shared between splits; no random splitting or K-fold is used.

| horizon | training rows | validation rows | test rows | censored target rows (train / val / test) |
|---|---|---|---|---|
| 7d | 1,277,500 | 215,000 | 215,000 | 39,523 / 7,071 / 6,098 |
| 14d | 1,260,000 | 197,500 | 197,500 | 68,654 / 11,349 / 10,036 |
| 30d | 1,220,000 | 157,500 | 157,500 | 125,456 / 16,780 / 15,515 |

Forecast population: 2500 of 2500 pairs are eligible and forecasted; excluded pairs: 0 (none: every pair has 730 days of history, observed demand and limited censoring). Exclusion rules use training-period information only.

## 5. Stockout-Censored Demand

When end-of-day stock is zero, zero or low sales do not mean zero demand: customers may have wanted a medicine that was unavailable. Observed sales are therefore a lower bound of demand in those periods. **Lost sales are never imputed or invented.** A target window is flagged *censored* if end-of-day stock was zero on at least one of its days (a conservative flag). Two strategies were compared:
- **A (observed)**: train on all observed targets and keep the stockout features so the model can learn the effect.
- **B (uncensored)**: drop training rows whose target window is censored, and train only on windows with stock throughout.

- 7d: validation WAPE on all rows A 0.3923 / B 0.3941; on uncensored rows A 0.3887 / B 0.3874; bias on all rows A -11.55% / B -11.51%; training rows A 1,277,500 / B 1,237,977.
- 14d: validation WAPE on all rows A 0.2988 / B 0.3006; on uncensored rows A 0.2972 / B 0.2974; bias on all rows A -7.9% / B -8.69%; training rows A 1,260,000 / B 1,191,346.
- 30d: validation WAPE on all rows A 0.2318 / B 0.2346; on uncensored rows A 0.2375 / B 0.2387; bias on all rows A -5.35% / B -6.73%; training rows A 1,220,000 / B 1,094,544.

**Selected strategy: B_uncensored.** The rule (fixed beforehand) is the lower validation WAPE on uncensored rows at the primary 7-day horizon, because those rows measure demand without censoring. Limitation: censored windows tend to coincide with high demand, so dropping them removes informative periods; the all-rows bias column shows the resulting under- or over-forecast against observed sales.

## 6. Feature Engineering

36 features, all known at the origin: lags [1, 2, 3, 7, 14, 21, 28]; rolling mean/std over [7, 14, 28] days and rolling median over [7, 28]; a 7/28-day trend ratio; a censoring-aware mean over in-stock days; stockout context (current stock, stockout flag, stockout days in the last 7 and 28 days, days since the last stockout, stock-to-demand ratio); calendar of the first predicted day (day of week, month, quarter, week, weekend, sine/cosine of day of week and month); branch and category as categorical features. No ground-truth or hidden generator information is used.

## 7. Baseline Models

- **naive**: repeat the most recent h days. **moving_average_7 / _28**: recent daily mean over 7 / 28 days times h. **seasonal_naive_weekly**: each future day takes the same weekday of the latest observed week (identical to naive at 7 days). **seasonal_naive_yearly**: the same span 364 days earlier; only 24 months exist, so this rests on a single earlier year, is available only for validation and test origins, and is not many independent yearly observations.

## 8. ML Model

`HistGradientBoostingRegressor` (scikit-learn), one model per horizon. Selected configuration: loss `squared_error`, target transform `log1p` (log1p with expm1 back-transform and clipping at zero when used), parameters {'learning_rate': 0.05, 'max_iter': 300, 'max_leaf_nodes': 63, 'min_samples_leaf': 200, 'l2_regularization': 1.0}. `random_state` 42.

## 9. Temporal Validation

The loss/target transform and hyperparameters were chosen on the **validation** split at the 7-day horizon (search on every third training origin; small grid, no random K-fold): 
- loss/target-transform: loss squared_error, transform raw, params #0 -> validation WAPE 0.3985
- loss/target-transform: loss squared_error, transform log1p, params #0 -> validation WAPE 0.393
- loss/target-transform: loss poisson, transform raw, params #0 -> validation WAPE 0.3978
- hyperparameters: loss squared_error, transform log1p, params #1 -> validation WAPE 0.3928
- hyperparameters: loss squared_error, transform log1p, params #2 -> validation WAPE 0.3936
- hyperparameters: loss squared_error, transform log1p, params #3 -> validation WAPE 0.3928

After selection the final model was refit on **training + validation** and evaluated **once** on the test split. The test split was never used for any choice. A separate deployment refit on all observed targets produces the single future forecast (origin = the last date).

## 10. Model Comparison

Metrics: MAE and RMSE in units over the horizon; WAPE = sum|error| / sum(actual); MASE = MAE / in-sample naive MAE on the training split; bias = sum(pred - actual) / sum(actual). MAPE is not used (zero actuals). All models are evaluated on identical rows.

### Validation (all rows)

**7-day**

| model | sample_count | MAE | RMSE | WAPE | MASE | bias_pct |
|---|---|---|---|---|---|---|
| naive | 215000 | 3.0408 | 5.3704 | 0.5013 | 0.9982 | -0.16 |
| moving_average_7 | 215000 | 3.0408 | 5.3704 | 0.5013 | 0.9982 | -0.16 |
| moving_average_28 | 215000 | 2.4747 | 4.2858 | 0.4079 | 0.8124 | -0.35 |
| seasonal_naive_weekly | 215000 | 3.0408 | 5.3704 | 0.5013 | 0.9982 | -0.16 |
| seasonal_naive_yearly | 215000 | 3.0537 | 5.3598 | 0.5034 | 1.0025 | -1.68 |
| ml_observed | 215000 | 2.3797 | 4.1663 | 0.3923 | 0.7812 | -11.55 |
| ml_uncensored | 215000 | 2.3905 | 4.2123 | 0.3941 | 0.7847 | -11.51 |

**14-day**

| model | sample_count | MAE | RMSE | WAPE | MASE | bias_pct |
|---|---|---|---|---|---|---|
| naive | 197500 | 4.417 | 7.7096 | 0.364 | 1.0028 | -0.32 |
| moving_average_7 | 197500 | 5.3724 | 9.3888 | 0.4427 | 1.2197 | -0.27 |
| moving_average_28 | 197500 | 3.8631 | 6.6586 | 0.3183 | 0.877 | -0.46 |
| seasonal_naive_weekly | 197500 | 5.3724 | 9.3888 | 0.4427 | 1.2197 | -0.27 |
| seasonal_naive_yearly | 197500 | 4.4506 | 7.6341 | 0.3667 | 1.0104 | -1.75 |
| ml_observed | 197500 | 3.6264 | 6.3224 | 0.2988 | 0.8233 | -7.9 |
| ml_uncensored | 197500 | 3.6478 | 6.3674 | 0.3006 | 0.8281 | -8.69 |

**30-day**

| model | sample_count | MAE | RMSE | WAPE | MASE | bias_pct |
|---|---|---|---|---|---|---|
| naive | 157500 | 6.5881 | 11.2698 | 0.2532 | 0.9982 | -0.63 |
| moving_average_7 | 157500 | 10.4872 | 18.1155 | 0.4031 | 1.589 | -0.55 |
| moving_average_28 | 157500 | 6.7082 | 11.4712 | 0.2578 | 1.0164 | -0.66 |
| seasonal_naive_weekly | 157500 | 10.5246 | 18.1866 | 0.4045 | 1.5947 | -0.56 |
| seasonal_naive_yearly | 157500 | 6.6613 | 11.4408 | 0.256 | 1.0093 | -1.73 |
| ml_observed | 157500 | 6.0319 | 10.4959 | 0.2318 | 0.914 | -5.35 |
| ml_uncensored | 157500 | 6.1049 | 10.6656 | 0.2346 | 0.925 | -6.73 |

### Test (all rows)

**7-day**

| model | sample_count | MAE | RMSE | WAPE | MASE | bias_pct |
|---|---|---|---|---|---|---|
| naive | 215000 | 3.0598 | 5.3422 | 0.4972 | 1.0045 | -0.12 |
| moving_average_7 | 215000 | 3.0598 | 5.3422 | 0.4972 | 1.0045 | -0.12 |
| moving_average_28 | 215000 | 2.4809 | 4.2582 | 0.4031 | 0.8144 | -0.42 |
| seasonal_naive_weekly | 215000 | 3.0598 | 5.3422 | 0.4972 | 1.0045 | -0.12 |
| seasonal_naive_yearly | 215000 | 3.0738 | 5.4175 | 0.4995 | 1.009 | -2.8 |
| ml_selected | 215000 | 2.403 | 4.2063 | 0.3905 | 0.7888 | -11.37 |

**14-day**

| model | sample_count | MAE | RMSE | WAPE | MASE | bias_pct |
|---|---|---|---|---|---|---|
| naive | 197500 | 4.4539 | 7.765 | 0.3618 | 1.0112 | -0.47 |
| moving_average_7 | 197500 | 5.396 | 9.3659 | 0.4383 | 1.225 | -0.34 |
| moving_average_28 | 197500 | 3.8761 | 6.6937 | 0.3148 | 0.88 | -0.58 |
| seasonal_naive_weekly | 197500 | 5.396 | 9.3659 | 0.4383 | 1.225 | -0.34 |
| seasonal_naive_yearly | 197500 | 4.5059 | 7.9069 | 0.366 | 1.023 | -2.82 |
| ml_selected | 197500 | 3.6728 | 6.4622 | 0.2983 | 0.8338 | -8.6 |

**30-day**

| model | sample_count | MAE | RMSE | WAPE | MASE | bias_pct |
|---|---|---|---|---|---|---|
| naive | 157500 | 6.5727 | 11.4522 | 0.2493 | 0.9959 | -0.88 |
| moving_average_7 | 157500 | 10.599 | 18.3131 | 0.402 | 1.606 | -0.52 |
| moving_average_28 | 157500 | 6.7027 | 11.6587 | 0.2542 | 1.0156 | -0.87 |
| seasonal_naive_weekly | 157500 | 10.6303 | 18.382 | 0.4031 | 1.6107 | -0.52 |
| seasonal_naive_yearly | 157500 | 6.796 | 12.0775 | 0.2577 | 1.0297 | -3.05 |
| ml_selected | 157500 | 6.0913 | 10.9181 | 0.231 | 0.923 | -6.57 |

## 11. Segment Performance

Segments reuse existing project definitions: volume class (FAST / MEDIUM / SLOW mover, from the analytics view), stockout group (low = lowest quartile of pair stockout rate, high = highest quartile) and demand variability class (STABLE / MODERATELY VARIABLE / HIGHLY VARIABLE). These labels use the full period and are used ONLY to slice evaluation, never as features. Test split, 7-day horizon (the full table is `segment_metrics.csv`):

| segment | model | sample_count | MAE | RMSE | WAPE |
|---|---|---|---|---|---|
| volume_class=FAST | ml_selected | 43000 | 5.8811 | 8.2748 | 0.271 |
| volume_class=FAST | moving_average_28 | 43000 | 5.9471 | 8.3496 | 0.2741 |
| volume_class=MEDIUM | ml_selected | 64500 | 2.3336 | 3.1193 | 0.5454 |
| volume_class=MEDIUM | moving_average_28 | 64500 | 2.4142 | 3.1384 | 0.5642 |
| volume_class=SLOW | ml_selected | 107500 | 1.0534 | 1.4694 | 0.9924 |
| volume_class=SLOW | moving_average_28 | 107500 | 1.1344 | 1.5714 | 1.0688 |
| stockout_group=high | ml_selected | 53836 | 3.7363 | 6.0991 | 0.3223 |
| stockout_group=high | moving_average_28 | 53836 | 3.82 | 6.192 | 0.3295 |
| stockout_group=low | ml_selected | 69746 | 1.3465 | 2.3352 | 0.5748 |
| stockout_group=low | moving_average_28 | 69746 | 1.4177 | 2.3896 | 0.6051 |
| stockout_group=mid | ml_selected | 91418 | 2.4238 | 3.9425 | 0.4137 |
| stockout_group=mid | moving_average_28 | 91418 | 2.5034 | 3.9635 | 0.4273 |
| variability_class=HIGHLY VARIABLE | ml_selected | 99846 | 1.0685 | 1.502 | 1.0335 |
| variability_class=HIGHLY VARIABLE | moving_average_28 | 99846 | 1.1514 | 1.6114 | 1.1137 |
| variability_class=MODERATELY VARIABLE | ml_selected | 74992 | 2.3737 | 3.3236 | 0.5447 |
| variability_class=MODERATELY VARIABLE | moving_average_28 | 74992 | 2.4569 | 3.3358 | 0.5638 |
| variability_class=STABLE | ml_selected | 40162 | 5.775 | 8.2753 | 0.2597 |
| variability_class=STABLE | moving_average_28 | 40162 | 5.8307 | 8.3568 | 0.2622 |

## 12. Feature Importance

Permutation importance of the selected 7-day model on the validation split (increase in MAE when a feature is shuffled; baseline MAE 2.3888). It measures reliance of the model on a feature, not causality.

| feature | importance | importance_std |
|---|---|---|
| rolling_mean_28_instock | 2.26922 | 0.00305 |
| rolling_mean_28 | 2.01783 | 0.01074 |
| inventory_units | 0.12391 | 0.00235 |
| rolling_mean_7 | 0.04676 | 0.00029 |
| rolling_mean_14 | 0.04551 | 0.00024 |
| rolling_median_28 | 0.03858 | 0.00022 |
| rolling_std_28 | 0.02076 | 0.00145 |
| category_idx | 0.01818 | 0.00072 |
| days_since_stockout | 0.0138 | 0.00041 |
| rolling_median_7 | 0.01107 | 0.00019 |
| units_ratio_7_28 | 0.00525 | 0.00023 |
| lag_2 | 0.0048 | 6e-05 |

## 13. Forecast Uncertainty

An approximate 80 percent interval comes from empirical quantiles (10%, 90%) of the validation residuals (actual - prediction) in 5 bins of the point forecast. It is an empirical error band, not a formal probabilistic forecast. Measured coverage on the test split: 7d 80.4%, 14d 80.4%, 30d 80.5%.

## 14. Results

- **7-day**: the ML model's test WAPE is 0.3905 (MAE 2.403, bias -11.37%), which is better than the best baseline chosen on validation (moving_average_28: WAPE 0.4031, MAE 2.4809, bias -0.42%).
- **14-day**: the ML model's test WAPE is 0.2983 (MAE 3.6728, bias -8.6%), which is better than the best baseline chosen on validation (moving_average_28: WAPE 0.3148, MAE 3.8761, bias -0.58%).
- **30-day**: the ML model's test WAPE is 0.231 (MAE 6.0913, bias -6.57%), which is better than the best baseline chosen on validation (naive: WAPE 0.2493, MAE 6.5727, bias -0.88%).

**Reading the results honestly.** Gains over the best baseline are real but modest. Pairs that sell little are close to unpredictable (see the segment table), so overall WAPE is dominated by irreducible randomness on slow movers. The ML model forecasts total units 11.4% below the observed total at 7d, 8.6% below the observed total at 14d, 6.6% below the observed total at 30d (test, all rows), while the baselines are within 0.9% of it. A `log1p` target gives the best WAPE (it targets a typical, median-like value) but, after back-transformation, under-states the mean and therefore the total. That bias was visible on validation when the model was selected (the selection rule was WAPE, fixed beforehand), and it matters for stock planning: totals from this model should be bias-corrected or compared with the Poisson-loss variant before being used for reorder decisions. This layer deliberately leaves that to the Decision Support phase instead of changing the selection rule after seeing results.

Note on identical rows: `naive` and `moving_average_7` coincide, and `seasonal_naive_weekly` equals both at 7 days (and equals `moving_average_7` at 14 days), because repeating or averaging the last week gives the same number when the horizon is a multiple of 7. Identical metrics there are expected, not an error.

## 15. Limitations

- **Stockout censoring:** observed sales may underestimate true demand during stockouts; the two strategies reduce but do not remove this, and no lost sales are modelled. Censored target windows are a small share of rows, and the two strategies differ by under one percent in WAPE, so the choice between them is not decisive.
- **Under-forecasting bias:** the selected model forecasts totals below the observed totals (see Results); it is accurate per row in the WAPE sense but not unbiased in aggregate.
- **Synthetic data:** the models are trained and evaluated on synthetic pharmacy data; results do not transfer to real pharmacies.
- **No external demand drivers:** there is no patient, prescription, competitor, price-promotion, marketing, epidemiological or weather information, so these are not causal demand predictions.
- **Sparse demand:** many branch-medicine pairs sell very few units per week, so errors on those pairs are dominated by randomness that no model can remove.
- **Uncertainty:** predictions are estimates; the interval is approximate.
- **Short history:** 24 months give one earlier year for yearly seasonality, and the 30-day test windows cover only the last two months of the data.
- **Overlapping origins:** daily origins have overlapping target windows, so rows are strongly autocorrelated and the effective sample size is smaller than the row count.

## 16. Reproducibility

Seed 42; Python 3.11.0; numpy 1.26.4, pandas 2.2.2, scikit-learn 1.4.2. Splits: train ['2025-01-01', '2026-06-30'], validation ['2026-07-01', '2026-09-30'], test ['2026-10-01', '2026-12-31']. Running `python -m ml_forecasting.run` twice yields identical reports (except `run_timestamp` and `runtime_seconds`). Validation: 24 checks, 0 failures.
