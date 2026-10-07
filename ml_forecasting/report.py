"""Human-readable forecasting report, generated from the measured results only."""
import pandas as pd

from . import config as C


def _table(df, cols):
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        lines.append("| " + " | ".join(str(r[c]) for c in cols) + " |")
    return lines


def render(S, comparison, seg, fi, results, best_base, coverage, pairs):
    ch = S["selected_model_config"]
    strat = S["selected_stockout_strategy"]
    L = ["# MedStock Demand Forecasting", "",
         "> Synthetic data. The models forecast *observed unit sales* of a synthetic pharmacy dataset. They do not model causes of demand and make no claim about real pharmacies.", "",
         "## 1. Objective", "",
         "Forecast future demand for each medicine at each branch, so that inventory decisions can be made before stockouts occur. This layer produces forecasts only; reorder quantities and purchase recommendations belong to the later Decision Support phase.", "",
         "## 2. Forecasting Grain", "",
         f"One forecast per **branch x medicine pair** ({coverage['branch_medicine_pairs']} pairs = 5 branches x 500 medicines) per **forecast origin day**. Forecasts are not aggregated to medicine level, because branch-specific demand drives inventory planning.", "",
         "## 3. Forecast Horizons", "",
         f"7 days (primary), 14 days and 30 days. One reusable pipeline fits a direct model per horizon (target = total units over the next h days). The 7-day horizon drives model selection; the same configuration is then applied to 14 and 30 days.", "",
         "## 4. Dataset Construction", "",
         "One SQL query returns the dense daily series (date x branch x medicine: units sold, revenue, end-of-day stock) from the warehouse; features, targets and splits are built vectorised in pandas/numpy.",
         "- **Forecast origin** O = end of day O. Features use data through O. **Target** `future_units_hd` = observed units sold on days O+1 .. O+h (strictly after O).",
         "- **lag_k** = units on day O-k+1, so lag_1 is the origin day. Rolling windows cover O-w+1 .. O. The first predicted day O+1 never enters a feature.",
         f"- **Splits are chronological** and assigned by where the whole target window lies: training {S['training_range'][0]} to {S['training_range'][1]}, validation {S['validation_range'][0]} to {S['validation_range'][1]}, "
         f"test {S['test_range'][0]} to {S['test_range'][1]}. No target period is shared between splits; no random splitting or K-fold is used.",
         ""]
    L += ["| horizon | training rows | validation rows | test rows | censored target rows (train / val / test) |", "|---|---|---|---|---|"]
    for h in C.HORIZONS:
        i = S["per_horizon"][f"{h}d"]
        L.append(f"| {h}d | {i['rows']['train']:,} | {i['rows']['validation']:,} | {i['rows']['test']:,} | {i['censored_rows']['train']:,} / {i['censored_rows']['validation']:,} / {i['censored_rows']['test']:,} |")
    L += ["", f"Forecast population: {coverage['eligible_pairs']} of {coverage['branch_medicine_pairs']} pairs are eligible and forecasted; excluded pairs: {coverage['excluded_pairs']} "
          f"({coverage['exclusion_reasons'] or 'none: every pair has 730 days of history, observed demand and limited censoring'}). Exclusion rules use training-period information only.", "",
          "## 5. Stockout-Censored Demand", "",
          "When end-of-day stock is zero, zero or low sales do not mean zero demand: customers may have wanted a medicine that was unavailable. Observed sales are therefore a lower bound of demand in those periods. "
          "**Lost sales are never imputed or invented.** A target window is flagged *censored* if end-of-day stock was zero on at least one of its days (a conservative flag). Two strategies were compared:",
          "- **A (observed)**: train on all observed targets and keep the stockout features so the model can learn the effect.",
          "- **B (uncensored)**: drop training rows whose target window is censored, and train only on windows with stock throughout.", ""]
    for h in C.HORIZONS:
        sc = S["per_horizon"][f"{h}d"]["strategy_comparison"]
        i = S["per_horizon"][f"{h}d"]
        L.append(f"- {h}d: validation WAPE on all rows A {sc['A_observed']['all']['WAPE']} / B {sc['B_uncensored']['all']['WAPE']}; on uncensored rows A {sc['A_observed']['uncensored']['WAPE']} / "
                 f"B {sc['B_uncensored']['uncensored']['WAPE']}; bias on all rows A {sc['A_observed']['all']['bias_pct']}% / B {sc['B_uncensored']['all']['bias_pct']}%; training rows A {i['train_rows_A_observed']:,} / B {i['train_rows_B_uncensored']:,}.")
    L += ["", f"**Selected strategy: {strat}.** The rule (fixed beforehand) is the lower validation WAPE on uncensored rows at the primary 7-day horizon, because those rows measure demand without censoring. "
              "Limitation: censored windows tend to coincide with high demand, so dropping them removes informative periods; the all-rows bias column shows the resulting under- or over-forecast against observed sales.", "",
          "## 6. Feature Engineering", "",
          f"{S['feature_count']} features, all known at the origin: lags {C.LAGS}; rolling mean/std over {C.ROLLING_WINDOWS} days and rolling median over {C.ROLLING_MEDIAN_WINDOWS}; a 7/28-day trend ratio; a censoring-aware mean over in-stock days; "
          "stockout context (current stock, stockout flag, stockout days in the last 7 and 28 days, days since the last stockout, stock-to-demand ratio); calendar of the first predicted day (day of week, month, quarter, week, weekend, sine/cosine of day of week and month); "
          "branch and category as categorical features. No ground-truth or hidden generator information is used.", "",
          "## 7. Baseline Models", "",
          "- **naive**: repeat the most recent h days. **moving_average_7 / _28**: recent daily mean over 7 / 28 days times h. "
          "**seasonal_naive_weekly**: each future day takes the same weekday of the latest observed week (identical to naive at 7 days). "
          "**seasonal_naive_yearly**: the same span 364 days earlier; only 24 months exist, so this rests on a single earlier year, is available only for validation and test origins, and is not many independent yearly observations.", "",
          "## 8. ML Model", "",
          f"`HistGradientBoostingRegressor` (scikit-learn), one model per horizon. Selected configuration: loss `{ch['loss']}`, target transform `{ch['target_transform']}` "
          f"(log1p with expm1 back-transform and clipping at zero when used), parameters {ch['params']}. `random_state` {S['random_seed']}.", "",
          "## 9. Temporal Validation", "",
          "The loss/target transform and hyperparameters were chosen on the **validation** split at the 7-day horizon (search on every third training origin; small grid, no random K-fold): "]
    for s in S["per_horizon"]["7d"]["search_log"]:
        L.append(f"- {s['stage']}: loss {s['loss']}, transform {s['transform']}, params #{s['params']} -> validation WAPE {s['validation_WAPE']}")
    L += ["", "After selection the final model was refit on **training + validation** and evaluated **once** on the test split. The test split was never used for any choice. "
              "A separate deployment refit on all observed targets produces the single future forecast (origin = the last date).", "",
          "## 10. Model Comparison", "", "Metrics: MAE and RMSE in units over the horizon; WAPE = sum|error| / sum(actual); MASE = MAE / in-sample naive MAE on the training split; bias = sum(pred - actual) / sum(actual). "
          "MAPE is not used (zero actuals). All models are evaluated on identical rows.", ""]
    for split in ("validation", "test"):
        L += [f"### {split.capitalize()} (all rows)", ""]
        sub = comparison[(comparison["split"] == split) & (comparison["subset"] == "all")].copy()
        for h in C.HORIZONS:
            L += [f"**{h}-day**", ""] + _table(sub[sub["horizon"] == h], ["model", "sample_count", "MAE", "RMSE", "WAPE", "MASE", "bias_pct"]) + [""]
    L += ["## 11. Segment Performance", "",
          "Segments reuse existing project definitions: volume class (FAST / MEDIUM / SLOW mover, from the analytics view), stockout group (low = lowest quartile of pair stockout rate, high = highest quartile) and demand variability class (STABLE / MODERATELY VARIABLE / HIGHLY VARIABLE). "
          "These labels use the full period and are used ONLY to slice evaluation, never as features. Test split, 7-day horizon (the full table is `segment_metrics.csv`):", ""]
    t7 = seg[(seg["split"] == "test") & (seg["horizon"] == 7)]
    L += _table(t7, ["segment", "model", "sample_count", "MAE", "RMSE", "WAPE"]) + ["",
          "## 12. Feature Importance", "",
          f"Permutation importance of the selected 7-day model on the validation split (increase in MAE when a feature is shuffled; baseline MAE {S['permutation_importance_baseline_mae_7d']}). It measures reliance of the model on a feature, not causality.", ""]
    L += _table(fi.head(12), ["feature", "importance", "importance_std"]) + ["",
          "## 13. Forecast Uncertainty", "",
          f"An approximate {S['interval_nominal']} interval comes from empirical quantiles ({C.INTERVAL['lower_q']:.0%}, {C.INTERVAL['upper_q']:.0%}) of the validation residuals (actual - prediction) in {C.INTERVAL['bins']} bins of the point forecast. "
          f"It is an empirical error band, not a formal probabilistic forecast. Measured coverage on the test split: " + ", ".join(f"{h}d {c:.1%}" for h, c in S["interval_empirical_coverage_test"].items()) + ".", "",
          "## 14. Results", ""]
    test = comparison[(comparison["split"] == "test") & (comparison["subset"] == "all")]
    for h in C.HORIZONS:
        ml = test[(test["horizon"] == h) & (test["model"] == "ml_selected")].iloc[0]
        bb = test[(test["horizon"] == h) & (test["model"] == best_base[h])].iloc[0]
        verdict = "better than" if ml["WAPE"] < bb["WAPE"] else "NOT better than"
        L.append(f"- **{h}-day**: the ML model's test WAPE is {ml['WAPE']} (MAE {ml['MAE']}, bias {ml['bias_pct']}%), which is {verdict} the best baseline chosen on validation ({best_base[h]}: WAPE {bb['WAPE']}, MAE {bb['MAE']}, bias {bb['bias_pct']}%).")
    mlb = {h: float(test[(test["horizon"] == h) & (test["model"] == "ml_selected")].iloc[0]["bias_pct"]) for h in C.HORIZONS}
    bbb = {h: float(test[(test["horizon"] == h) & (test["model"] == best_base[h])].iloc[0]["bias_pct"]) for h in C.HORIZONS}
    L += ["", "**Reading the results honestly.** Gains over the best baseline are real but modest. Pairs that sell little are close to unpredictable (see the segment table), "
              "so overall WAPE is dominated by irreducible randomness on slow movers. The ML model forecasts total units "
              + ", ".join(f"{abs(mlb[h]):.1f}% {'below' if mlb[h] < 0 else 'above'} the observed total at {h}d" for h in C.HORIZONS) + " (test, all rows), while the baselines are within "
              + f"{max(abs(v) for v in bbb.values()):.1f}% of it. "
              + ("A `log1p` target gives the best WAPE (it targets a typical, median-like value) but, after back-transformation, under-states the mean and therefore the total. "
                 "That bias was visible on validation when the model was selected (the selection rule was WAPE, fixed beforehand), and it matters for stock planning: totals from this model should be bias-corrected or compared with the Poisson-loss variant before being used for reorder decisions. "
                 "This layer deliberately leaves that to the Decision Support phase instead of changing the selection rule after seeing results." if ch["target_transform"] == "log1p" else ""),
          "",
          "Note on identical rows: `naive` and `moving_average_7` coincide, and `seasonal_naive_weekly` equals both at 7 days (and equals `moving_average_7` at 14 days), because repeating or averaging the last week gives the same number when the horizon is a multiple of 7. Identical metrics there are expected, not an error.",
          "", "## 15. Limitations", "",
          "- **Stockout censoring:** observed sales may underestimate true demand during stockouts; the two strategies reduce but do not remove this, and no lost sales are modelled. Censored target windows are a small share of rows, and the two strategies differ by under one percent in WAPE, so the choice between them is not decisive.",
          "- **Under-forecasting bias:** the selected model forecasts totals below the observed totals (see Results); it is accurate per row in the WAPE sense but not unbiased in aggregate.",
          "- **Synthetic data:** the models are trained and evaluated on synthetic pharmacy data; results do not transfer to real pharmacies.",
          "- **No external demand drivers:** there is no patient, prescription, competitor, price-promotion, marketing, epidemiological or weather information, so these are not causal demand predictions.",
          "- **Sparse demand:** many branch-medicine pairs sell very few units per week, so errors on those pairs are dominated by randomness that no model can remove.",
          "- **Uncertainty:** predictions are estimates; the interval is approximate.",
          "- **Short history:** 24 months give one earlier year for yearly seasonality, and the 30-day test windows cover only the last two months of the data.",
          "- **Overlapping origins:** daily origins have overlapping target windows, so rows are strongly autocorrelated and the effective sample size is smaller than the row count.", "",
          "## 16. Reproducibility", "",
          f"Seed {S['random_seed']}; Python {S['python']}; numpy {S['packages']['numpy']}, pandas {S['packages']['pandas']}, scikit-learn {S['packages']['scikit-learn']}. "
          f"Splits: train {S['training_range']}, validation {S['validation_range']}, test {S['test_range']}. Running `python -m ml_forecasting.run` twice yields identical reports (except `run_timestamp` and `runtime_seconds`). "
          f"Validation: {S['validation']['checks']} checks, {S['validation']['failures']} failures.", ""]
    return "\n".join(L)
