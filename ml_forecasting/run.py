"""Run the demand-forecasting layer:   python -m ml_forecasting.run

Flow
  1. load the daily branch x medicine series from the warehouse (one SQL query), build causal features, targets and censoring flags
  2. for the 7-day horizon: choose loss / target transform and hyperparameters on VALIDATION (strategy A), then compare stockout strategies A and B
  3. for every horizon: fit A and B on the training split, evaluate on validation, keep the selected strategy
  4. final models = selected strategy trained on training + validation, evaluated ONCE on the test split; baselines evaluated on the same rows
  5. a deployment refit on all observed targets produces the genuinely future forecast (origin = last date)
"""
import json
import platform
import sys
import time
import warnings
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from . import config as C
from . import validation as V
from .evaluation import metrics as M
from .features import build_features as bf
from .models import demand_model as dm
from .models.baselines import baseline_forecasts

warnings.filterwarnings("ignore")
R = C.REPORT_DIR
LOG = []


def log(msg):
    print(msg, flush=True)
    LOG.append(msg)


def _json(path, obj):
    path.write_text(json.dumps(obj, indent=2, default=lambda o: o.item() if hasattr(o, "item") else str(o)), encoding="utf-8")


def _rows(cube, origins, eligible):
    X, o_idx, p_idx = bf.assemble(cube, origins, eligible)
    return X, o_idx, p_idx


def process_horizon(h, data, cube, eligible, names, cat_idx, choice, search):
    """All fitting and evaluation for one horizon. `choice` holds the selected variant/params/strategy (None while searching at the primary horizon)."""
    units, inv, dates, pairs = data["units"], data["inventory"], data["dates"], data["pairs"]
    y, sk = bf.targets(units, inv, h)
    origins = bf.split_origins(dates, h)
    base = baseline_forecasts(units, h)
    sets = {}
    for split in ("train", "validation", "test"):
        X, o, p = _rows(cube, origins[split], eligible)
        sets[split] = {"X": X, "o": o, "p": p, "y": y[o, p], "cens": sk[o, p] > 0}
        sets[split]["baselines"] = {k: base[k][o, p] for k in C.BASELINES}
    tr, va, te = sets["train"], sets["validation"], sets["test"]
    info = {"horizon": h, "rows": {k: int(len(v["y"])) for k, v in sets.items()},
            "censored_rows": {k: int(v["cens"].sum()) for k, v in sets.items()}}
    naive_train_mae = float(np.nanmean(np.abs(tr["y"] - tr["baselines"]["naive"])))
    info["naive_train_mae"] = round(naive_train_mae, 4)

    def val_metrics(pred, subset):
        m = va["cens"] == False if subset == "uncensored" else np.ones(len(va["y"]), dtype=bool)
        return M.metrics(va["y"][m], pred[m], naive_train_mae)

    search_log = []
    if search:
        stride = np.isin(tr["o"], origins["train"][::C.SEARCH_ORIGIN_STRIDE])
        best = None
        default = C.PARAM_GRID[0]
        for loss, transform in C.MODEL_VARIANTS:
            t = time.time()
            mdl = dm.fit(tr["X"][stride], tr["y"][stride], loss, transform, default, cat_idx)
            w = val_metrics(dm.predict(mdl, va["X"], transform), "all")["WAPE"]
            search_log.append({"stage": "loss/target-transform", "loss": loss, "transform": transform, "params": 0, "validation_WAPE": w})
            log(f"    [search h={h}] {loss:<13} {transform:<5} default params -> validation WAPE {w:.4f}  ({time.time() - t:.0f}s)")
            if best is None or w < best["w"]:
                best = {"w": w, "loss": loss, "transform": transform, "params_idx": 0}
        for i, params in enumerate(C.PARAM_GRID[1:], start=1):
            t = time.time()
            mdl = dm.fit(tr["X"][stride], tr["y"][stride], best["loss"], best["transform"], params, cat_idx)
            w = val_metrics(dm.predict(mdl, va["X"], best["transform"]), "all")["WAPE"]
            search_log.append({"stage": "hyperparameters", "loss": best["loss"], "transform": best["transform"], "params": i, "validation_WAPE": w})
            log(f"    [search h={h}] params #{i} {params} -> validation WAPE {w:.4f}  ({time.time() - t:.0f}s)")
            if w < best["w"]:
                best.update({"w": w, "params_idx": i})
        choice = {"loss": best["loss"], "transform": best["transform"], "params": C.PARAM_GRID[best["params_idx"]], "params_idx": best["params_idx"]}
    info["search_log"] = search_log

    # --- strategies A (observed targets) and B (drop censored target windows) on the TRAINING split ---------------------------
    fits = {}
    for strat in ("A_observed", "B_uncensored"):
        keep = np.ones(len(tr["y"]), dtype=bool) if strat == "A_observed" else ~tr["cens"]
        t = time.time()
        fits[strat] = dm.fit(tr["X"][keep], tr["y"][keep], choice["loss"], choice["transform"], choice["params"], cat_idx)
        info[f"train_rows_{strat}"] = int(keep.sum())
        log(f"    [h={h}] strategy {strat}: trained on {int(keep.sum()):,} of {len(keep):,} training rows ({time.time() - t:.0f}s)")
    val_pred = {s: dm.predict(m, va["X"], choice["transform"]) for s, m in fits.items()}
    comparison = []

    def add(model, split, subset, actual, pred, mask=None):
        m = np.ones(len(actual), dtype=bool) if mask is None else mask
        comparison.append({"model": model, "horizon": h, "split": split, "subset": subset, **M.metrics(actual[m], pred[m], naive_train_mae)})

    unc = ~va["cens"]
    for k in C.BASELINES:
        add(k, "validation", "all", va["y"], va["baselines"][k])
        add(k, "validation", "uncensored", va["y"], va["baselines"][k], unc)
    for s, name in (("A_observed", "ml_observed"), ("B_uncensored", "ml_uncensored")):
        add(name, "validation", "all", va["y"], val_pred[s])
        add(name, "validation", "uncensored", va["y"], val_pred[s], unc)
    strat_cmp = {s: {"all": M.metrics(va["y"], val_pred[s], naive_train_mae), "uncensored": M.metrics(va["y"][unc], val_pred[s][unc], naive_train_mae)} for s in val_pred}
    if choice.get("strategy") is None:   # decided at the primary horizon: lowest validation WAPE on UNCENSORED rows (true-demand proxy)
        choice["strategy"] = "B_uncensored" if strat_cmp["B_uncensored"]["uncensored"]["WAPE"] < strat_cmp["A_observed"]["uncensored"]["WAPE"] else "A_observed"
        log(f"    selected stockout strategy: {choice['strategy']} (validation WAPE on uncensored rows A {strat_cmp['A_observed']['uncensored']['WAPE']}, B {strat_cmp['B_uncensored']['uncensored']['WAPE']})")
    info["strategy_comparison"] = strat_cmp

    # --- residual interval and permutation importance from the TRAIN-ONLY model of the selected strategy -------------------------
    sel_val = val_pred[choice["strategy"]]
    interval = dm.Interval(sel_val, va["y"])
    importance = None
    if h == C.PRIMARY_HORIZON:
        importance = dm.permutation_importance(fits[choice["strategy"]], choice["transform"], va["X"], va["y"], names, C.PERMUTATION_SAMPLE_ROWS, C.PERMUTATION_REPEATS)

    # --- final model: selected strategy on training + validation, then the test split ---------------------------------------------
    keep_tr = np.ones(len(tr["y"]), dtype=bool) if choice["strategy"] == "A_observed" else ~tr["cens"]
    keep_va = np.ones(len(va["y"]), dtype=bool) if choice["strategy"] == "A_observed" else ~va["cens"]
    Xf = np.vstack([tr["X"][keep_tr], va["X"][keep_va]])
    yf = np.concatenate([tr["y"][keep_tr], va["y"][keep_va]])
    t = time.time()
    final = dm.fit(Xf, yf, choice["loss"], choice["transform"], choice["params"], cat_idx)
    del Xf
    te_pred = dm.predict(final, te["X"], choice["transform"])
    log(f"    [h={h}] final model on train+validation ({len(yf):,} rows) -> test  ({time.time() - t:.0f}s)")
    te_unc = ~te["cens"]
    for k in C.BASELINES:
        add(k, "test", "all", te["y"], te["baselines"][k])
        add(k, "test", "uncensored", te["y"], te["baselines"][k], te_unc)
    add("ml_selected", "test", "all", te["y"], te_pred)
    add("ml_selected", "test", "uncensored", te["y"], te_pred, te_unc)

    # --- deployment refit on every observed target (training + validation + test) for the future forecast -----------------------
    all_origins = np.arange(C.MIN_HISTORY_DAYS, units.shape[0] - h)
    Xa, oa, pa = _rows(cube, all_origins, eligible)
    ya, ska = y[oa, pa], sk[oa, pa]
    keep = np.ones(len(ya), dtype=bool) if choice["strategy"] == "A_observed" else ska == 0
    refit = dm.fit(Xa[keep], ya[keep], choice["loss"], choice["transform"], choice["params"], cat_idx)
    del Xa

    # row-level frames (for segments and forecast export); X matrices are released
    for s in sets.values():
        s.pop("X", None)
    return {"info": info, "choice": choice, "comparison": comparison, "val": va, "test": te, "val_pred": val_pred, "test_pred": te_pred, "interval": interval,
            "importance": importance, "final_model": final, "refit_model": refit, "naive_train_mae": naive_train_mae, "fits_val": fits}


def segment_rows(res, pairs, split, best_baseline):
    d = res[("val" if split == "validation" else "test")]
    pred = res["val_pred"][res["choice"]["strategy"]] if split == "validation" else res["test_pred"]
    df = pd.DataFrame({"actual": d["y"], "ml": pred, best_baseline: d["baselines"][best_baseline]})
    pr = pairs.iloc[d["p"]]
    q = C.SEGMENT_STOCKOUT_QUANTILES
    lo, hi = np.quantile(pairs["stockout_rate_pct"], q[0]), np.quantile(pairs["stockout_rate_pct"], q[1])
    rate = pr["stockout_rate_pct"].to_numpy()
    df["volume_class"] = pr["mover_class"].to_numpy()
    df["stockout_group"] = np.where(rate <= lo, "low", np.where(rate >= hi, "high", "mid"))
    df["variability_class"] = pr["variability_class"].to_numpy()
    rows = []
    for col in ("volume_class", "stockout_group", "variability_class"):
        t = M.segment_table(df, ["ml", best_baseline], col, res["naive_train_mae"])
        t["model"] = t["model"].replace({"ml": "ml_selected"})
        rows.append(t)
    out = pd.concat(rows, ignore_index=True)
    out.insert(1, "horizon", res["info"]["horizon"])
    out.insert(2, "split", split)
    return out


def main() -> int:
    t0 = time.time()
    R.mkdir(parents=True, exist_ok=True)
    engine, conn = bf.open_connection()
    ref = bf.dataset_reference()
    data = bf.load_data(conn)
    units, inv, dates, pairs = data["units"], data["inventory"], data["dates"], data["pairs"]
    T, N = units.shape
    log(f"MedStock demand forecasting | dataset {ref['generator_version']} (frozen {ref['frozen_on']}) | {T} days x {N} branch-medicine pairs")
    eligible, reason = bf.pair_eligibility(units, inv, dates)
    t = time.time()
    cube = bf.build_cube(units, inv, dates, pairs)
    names = cube["names"]
    cat_idx = dm.categorical_indices(names, bf.CATEGORICAL)
    log(f"features: {len(names)} per row, cube built in {time.time() - t:.0f}s | eligible pairs {int(eligible.sum())} of {N}")

    results, choice = {}, None
    for h in [C.PRIMARY_HORIZON] + [x for x in C.HORIZONS if x != C.PRIMARY_HORIZON]:
        log(f"[horizon {h}d]")
        results[h] = process_horizon(h, data, cube, eligible, names, cat_idx, choice, search=(choice is None))
        choice = results[h]["choice"]
    log(f"selected: loss={choice['loss']}, transform={choice['transform']}, params={choice['params']}, strategy={choice['strategy']}")

    # ---- model comparison / segments -------------------------------------------------------------------------------------------
    comparison = pd.DataFrame([r for h in C.HORIZONS for r in results[h]["comparison"]])
    comparison = comparison[["model", "horizon", "split", "subset", "sample_count", "MAE", "RMSE", "WAPE", "MASE", "bias_pct"]]
    comparison.to_csv(R / "model_comparison.csv", index=False)
    best_base = {}
    for h in C.HORIZONS:
        v = comparison[(comparison["horizon"] == h) & (comparison["split"] == "validation") & (comparison["subset"] == "all") & (comparison["model"].isin(C.BASELINES))]
        best_base[h] = v.sort_values(["WAPE", "model"]).iloc[0]["model"]
    seg = pd.concat([segment_rows(results[h], pairs, s, best_base[h]) for h in C.HORIZONS for s in ("validation", "test")], ignore_index=True)
    seg.to_csv(R / "segment_metrics.csv", index=False)

    # ---- feature importance --------------------------------------------------------------------------------------------------------
    imp, base_mae = results[C.PRIMARY_HORIZON]["importance"]
    fi = pd.DataFrame(imp, columns=["feature", "importance", "importance_std"]).sort_values("importance", ascending=False).reset_index(drop=True)
    fi["importance"] = fi["importance"].round(5)
    fi["importance_std"] = fi["importance_std"].round(5)
    fi[["feature", "importance", "importance_std"]].to_csv(R / "feature_importance.csv", index=False)

    # ---- forecasts.csv -----------------------------------------------------------------------------------------------------------------
    cal_test_start = pd.DatetimeIndex(dates).get_loc(pd.Timestamp(C.SPLITS["test"][0]))
    fc_origins_test = np.arange(cal_test_start - 1, T - 1, C.FORECAST_ORIGIN_STRIDE_DAYS)
    Xt, ot, pt = bf.assemble(cube, fc_origins_test, eligible)
    Xf_, of_, pf_ = bf.assemble(cube, [T - 1], eligible)
    wide_test = {h: dm.predict(results[h]["final_model"], Xt, choice["transform"]) for h in C.HORIZONS}
    wide_future = {h: dm.predict(results[h]["refit_model"], Xf_, choice["transform"]) for h in C.HORIZONS}
    stock_last28 = cube["matrix"]["stockout_days_last_28d"]
    frames = []

    def frame(h, model, split, o, p, actual, pred, lo, hi, wide):
        pr = pairs.iloc[p]
        df = pd.DataFrame({
            "forecast_date": pd.DatetimeIndex(dates)[o].strftime("%Y-%m-%d"),
            "target_start": (pd.DatetimeIndex(dates)[o] + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
            "target_end": (pd.DatetimeIndex(dates)[o] + pd.Timedelta(days=h)).strftime("%Y-%m-%d"),
            "branch_id": pr["branch_id"].to_numpy(), "medicine_id": pr["medicine_id"].to_numpy(), "medicine_name": pr["medicine_name"].to_numpy(),
            "category": pr["category"].to_numpy(), "horizon": h, "actual_units": actual, "predicted_units": np.round(pred, 3),
            "lower_bound": np.round(lo, 3), "upper_bound": np.round(hi, 3), "model": model, "split": split,
            "stockout_flag": (inv[o, p] == 0).astype(int), "current_inventory": inv[o, p], "recent_stockout_days": stock_last28[o, p].astype(int)})
        for hh in C.HORIZONS:
            df[f"forecast_demand_{hh}d"] = np.round(wide[hh], 3) if wide is not None else np.nan
        df["censored_target_days"] = np.nan
        return df

    for h in C.HORIZONS:
        r = results[h]
        yv, skv = bf.targets(units, inv, h)
        valid = ot + h <= T - 1
        o, p = ot[valid], pt[valid]
        # row positions of these (origin, pair) rows within the wide arrays
        pos = np.flatnonzero(valid)
        actual = yv[o, p]
        ml = wide_test[h][pos]
        lo, hi = r["interval"].bounds(ml)
        fr = frame(h, "ml_selected", "test", o, p, actual, ml, lo, hi, {k: wide_test[k][pos] for k in C.HORIZONS})
        fr["censored_target_days"] = skv[o, p]
        frames.append(fr)
        b = baseline_forecasts(units, h)[best_base[h]][o, p]
        fb = frame(h, best_base[h], "test", o, p, actual, b, np.full(len(b), np.nan), np.full(len(b), np.nan), None)
        fb["censored_target_days"] = skv[o, p]
        fb["lower_bound"] = fb["upper_bound"] = np.nan
        frames.append(fb)
        mf = wide_future[h]
        lo_f, hi_f = r["interval"].bounds(mf)
        frames.append(frame(h, "ml_selected", "future", of_, pf_, np.full(len(of_), np.nan), mf, lo_f, hi_f, wide_future))
    forecasts = pd.concat(frames, ignore_index=True)
    # baselines cannot be NaN-bounded in the validity check: drop the empty interval columns from baseline rows' ordering test by using prediction
    forecasts.loc[forecasts["lower_bound"].isna(), ["lower_bound", "upper_bound"]] = np.nan
    forecasts["forecast_date"] = pd.to_datetime(forecasts["forecast_date"])
    out_cols = ["forecast_date", "target_start", "target_end", "branch_id", "medicine_id", "medicine_name", "category", "horizon", "actual_units", "predicted_units",
                "lower_bound", "upper_bound", "model", "split", "stockout_flag", "current_inventory", "recent_stockout_days", "censored_target_days",
                "forecast_demand_7d", "forecast_demand_14d", "forecast_demand_30d"]
    forecasts = forecasts[out_cols].sort_values(["split", "horizon", "model", "forecast_date", "branch_id", "medicine_id"], kind="mergesort").reset_index(drop=True)
    forecasts.assign(forecast_date=forecasts["forecast_date"].dt.strftime("%Y-%m-%d")).to_csv(R / "forecasts.csv", index=False)

    # ---- coverage / interval coverage / summary ---------------------------------------------------------------------------------
    ml_test = forecasts[(forecasts["model"] == "ml_selected") & (forecasts["split"] == "test") & forecasts["actual_units"].notna()]
    cover = {int(h): round(float(((g["actual_units"] >= g["lower_bound"]) & (g["actual_units"] <= g["upper_bound"])).mean()), 4) for h, g in ml_test.groupby("horizon")}
    excl = pd.Series(reason[~eligible]).value_counts().to_dict()
    coverage = {"branch_medicine_pairs": int(N), "eligible_pairs": int(eligible.sum()), "forecasted_pairs": int(eligible.sum()),
                "excluded_pairs": int((~eligible).sum()), "exclusion_reasons": {str(k): int(v) for k, v in excl.items()},
                "insufficient_history_pairs": 0, "note": "every pair has the full 730 days of history; exclusions use training-period information only"}
    key = comparison[(comparison["subset"] == "all")]
    metrics_summary = {f"{h}d": {s: {m: key[(key["horizon"] == h) & (key["split"] == s) & (key["model"] == m)].iloc[0][["MAE", "RMSE", "WAPE", "MASE", "bias_pct"]].to_dict()
                                      for m in (C.BASELINES + (["ml_observed", "ml_uncensored"] if s == "validation" else ["ml_selected"]))} for s in ("validation", "test")} for h in C.HORIZONS}
    # ---- validation -----------------------------------------------------------------------------------------------------------------------
    cens_counts = {}
    stock0 = (inv == 0).astype(np.int64)
    for h in C.HORIZONS:
        _, skh = bf.targets(units, inv, h)
        data_count = int((skh[~np.isnan(skh)] > 0).sum())
        cs = np.vstack([np.zeros((1, N), dtype=np.int64), np.cumsum(stock0, axis=0)])
        indep = int(((cs[h + 1:] - cs[1:T - h + 1]) > 0).sum())
        cens_counts[h] = (data_count, indep)
    val = []
    val += V.leakage_tests(data)
    val += V.split_checks(dates)
    val += V.stockout_checks(data, conn, cube["matrix"]["was_stockout"] > 0, cens_counts)
    val += V.source_checks()
    import sklearn
    summary = {
        "run_timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dataset_version": f"{ref['generator_version']} (frozen {ref['frozen_on']}, seed {ref['random_seed']})",
        "split_dates": {k: list(v) for k, v in C.SPLITS.items()}, "training_range": list(C.SPLITS["train"]), "validation_range": list(C.SPLITS["validation"]),
        "test_range": list(C.SPLITS["test"]), "forecast_horizons": C.HORIZONS, "primary_horizon": C.PRIMARY_HORIZON,
        "models": C.BASELINES + ["ml_hist_gradient_boosting"], "selected_model": "HistGradientBoostingRegressor",
        "selected_model_config": {"loss": choice["loss"], "target_transform": choice["transform"], "params": choice["params"], "params_grid_index": choice["params_idx"]},
        "selected_stockout_strategy": choice["strategy"], "best_baseline_by_validation_wape": {f"{h}d": best_base[h] for h in C.HORIZONS},
        "metrics": metrics_summary, "interval_empirical_coverage_test": cover, "interval_nominal": f"{int((C.INTERVAL['upper_q'] - C.INTERVAL['lower_q']) * 100)} percent",
        "forecast_coverage": coverage, "excluded_pairs": coverage["excluded_pairs"],
        "per_horizon": {f"{h}d": {k: v for k, v in results[h]["info"].items()} for h in C.HORIZONS},
        "feature_count": len(names), "features": names, "categorical_features": bf.CATEGORICAL, "feature_configuration": {
            "lags": C.LAGS, "rolling_windows": C.ROLLING_WINDOWS, "rolling_median_windows": C.ROLLING_MEDIAN_WINDOWS, "days_since_stockout_cap": C.DAYS_SINCE_STOCKOUT_CAP,
            "min_history_days": C.MIN_HISTORY_DAYS},
        "random_seed": C.RANDOM_STATE, "python": platform.python_version(),
        "packages": {"numpy": np.__version__, "pandas": pd.__version__, "scikit-learn": sklearn.__version__},
        "permutation_importance_baseline_mae_7d": round(base_mae, 4),
    }
    out_val = V.output_checks(forecasts, comparison, summary)
    val += out_val
    failures = [v for v in val if not v["passed"]]
    _json(R / "validation_results.json", {"checks": len(val), "failures": len(failures), "results": val})
    summary["validation"] = {"checks": len(val), "failures": len(failures)}
    summary["runtime_seconds"] = round(time.time() - t0, 1)
    _json(R / "forecast_summary.json", summary)
    write_markdown(summary, comparison, seg, fi, results, best_base, coverage, pairs)
    for v in failures:
        log(f"  FAIL [{v['area']}] {v['check']}: {v['detail']}")
    log(f"Validation: {len(val)} checks, {len(failures)} failed | runtime {summary['runtime_seconds']}s")
    conn.close()
    engine.dispose()
    return 1 if failures else 0


def _fmt(df):
    return df.to_string(index=False)


def write_markdown(S, comparison, seg, fi, results, best_base, coverage, pairs):
    from .report import render
    (R / "forecasting_summary.md").write_text(render(S, comparison, seg, fi, results, best_base, coverage, pairs), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
