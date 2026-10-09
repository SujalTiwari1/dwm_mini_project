"""Demand forecasting for an UPLOADED dataset (sales only): python -m ml_forecasting.upload_run   (MEDSTOCK_DATASET=<id>)

Same model, features, baselines and metrics as the main pipeline, with the differences a sales-only file requires:
  * no stock data: the stockout features are dropped and no demand is treated as censored;
  * splits are chronological and sized from the length of the history (last ~15% test, the 15% before it validation, the rest training);
  * no hyperparameter search: the configuration selected on the demo dataset is used as is (it is NOT tuned on this data);
  * at most MAX_PAIRS branch x medicine pairs (the highest-volume ones) are forecast, and training rows are capped for speed.
Outputs (same file names/columns as the main pipeline): forecasts.csv, model_comparison.csv, feature_importance.csv, forecast_summary.json.
"""
import json
import sys
import time
import warnings
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from . import config as C
from .evaluation import metrics as M
from .features import build_features as bf
from .models import demand_model as dm
from .models.baselines import baseline_forecasts

warnings.filterwarnings("ignore")
R = C.REPORT_DIR
MAX_PAIRS = 3000
MAX_TRAIN_ROWS = 500_000
MIN_DAYS = 180
STOCK_FEATURES = {"inventory_units", "was_stockout", "stockout_last_7d", "stockout_days_last_7d", "stockout_days_last_28d",
                  "days_since_stockout", "inventory_to_demand_28", "rolling_mean_28_instock"}
CHOICE = {"loss": "squared_error", "transform": "log1p", "params": C.PARAM_GRID[1]}   # selected on the demo dataset, not tuned here
BASELINES = ["naive", "moving_average_7", "moving_average_28", "seasonal_naive_weekly"]


def log(msg):
    print(msg, flush=True)


def load_series(conn):
    """Dense [days x pairs] units from fact_sales (zero where nothing was sold) plus the pair table."""
    dates = pd.read_sql("SELECT date_key, full_date FROM warehouse.dim_date ORDER BY date_key", conn)
    meds = pd.read_sql("SELECT m.medicine_key, m.medicine_id, m.medicine_name, c.category_name AS category FROM warehouse.dim_medicine m "
                       "JOIN warehouse.dim_category c USING (category_key) ORDER BY m.medicine_key", conn)
    brs = pd.read_sql("SELECT branch_key, branch_id FROM warehouse.dim_branch ORDER BY branch_key", conn)
    sales = pd.read_sql("SELECT date_key, branch_key, medicine_key, SUM(quantity)::bigint AS units FROM warehouse.fact_sales "
                        "GROUP BY date_key, branch_key, medicine_key", conn)
    T, B, Mn = len(dates), len(brs), len(meds)
    di = pd.Series(np.arange(T), index=dates["date_key"])
    bi = pd.Series(np.arange(B), index=brs["branch_key"])
    mi = pd.Series(np.arange(Mn), index=meds["medicine_key"])
    units = np.zeros((T, B * Mn), dtype=np.int64)
    np.add.at(units, (di[sales["date_key"]].to_numpy(), bi[sales["branch_key"]].to_numpy() * Mn + mi[sales["medicine_key"]].to_numpy()), sales["units"].to_numpy())
    pairs = pd.DataFrame({
        "branch_id": np.repeat(brs["branch_id"].to_numpy(), Mn), "medicine_id": np.tile(meds["medicine_id"].to_numpy(), B),
        "medicine_name": np.tile(meds["medicine_name"].to_numpy(), B), "category": np.tile(meds["category"].to_numpy(), B),
        "branch_idx": np.repeat(np.arange(B), Mn)})
    keys = {"date": dates["date_key"].to_numpy(), "branch": brs["branch_key"].to_numpy(), "medicine": meds["medicine_key"].to_numpy(), "n_medicines": Mn}
    return pd.to_datetime(dates["full_date"]).reset_index(drop=True), units, pairs, keys


def set_splits(dates):
    T = len(dates)
    test_len = max(35, int(round(0.15 * T)))
    a, b = T - 2 * test_len, T - test_len                       # first index of validation / test
    d = pd.DatetimeIndex(dates).strftime("%Y-%m-%d")
    C.SPLITS.clear()
    C.SPLITS.update({"train": (d[0], d[a - 1]), "validation": (d[a], d[b - 1]), "test": (d[b], d[T - 1])})
    return a, b


def main() -> int:
    t0 = time.time()
    R.mkdir(parents=True, exist_ok=True)
    engine, conn = bf.open_connection()
    dates, units_all, pairs_all, keys = load_series(conn)
    conn.close()
    engine.dispose()
    T = len(dates)
    if T < MIN_DAYS:
        raise SystemExit(f"Only {T} days of history; at least {MIN_DAYS} are needed to forecast.")
    a, _b = set_splits(dates)

    # pair selection: pairs that sold in the training period, highest volume first, capped
    train_units = units_all[:a].sum(axis=0)
    order = np.argsort(-train_units, kind="stable")
    keep = np.sort(order[:MAX_PAIRS][train_units[order[:MAX_PAIRS]] > 0])
    if len(keep) == 0:
        raise SystemExit("No branch-medicine pair has sales in the training period.")
    units, pairs = units_all[:, keep], pairs_all.iloc[keep].reset_index(drop=True)
    pairs["category_idx"] = pd.factorize(pairs["category"], sort=True)[0]
    N = units.shape[1]
    log(f"MedStock upload forecasting | {T} days x {N} pairs ({len(pairs_all)} total, {len(pairs_all) - N} not forecast: no/low training demand or above the {MAX_PAIRS}-pair cap)")
    log(f"splits: {dict(C.SPLITS)}")

    inv = np.ones_like(units)                                   # no stock data: nothing is censored; stock features are removed below
    cube = bf.build_cube(units, inv, dates, pairs)
    cube["names"] = [n for n in cube["names"] if n not in STOCK_FEATURES]
    names = cube["names"]
    cat_idx = dm.categorical_indices(names, bf.CATEGORICAL)
    eligible = np.ones(N, dtype=bool)

    comparison, results, importance = [], {}, None
    for h in C.HORIZONS:
        t = time.time()
        y, _ = bf.targets(units, inv, h)
        origins = bf.split_origins(dates, h)
        base = baseline_forecasts(units, h)
        stride = max(1, int(np.ceil(len(origins["train"]) * N / MAX_TRAIN_ROWS)))
        sets = {}
        for split in ("train", "validation", "test"):
            o_sel = origins[split][::stride] if split == "train" else origins[split]
            X, o, p = bf.assemble(cube, o_sel, eligible)
            sets[split] = {"X": X, "o": o, "p": p, "y": y[o, p], "base": {k: base[k][o, p] for k in BASELINES}}
        tr, va, te = sets["train"], sets["validation"], sets["test"]
        naive_mae = float(np.nanmean(np.abs(tr["y"] - tr["base"]["naive"])))
        m_tr = dm.fit(tr["X"], tr["y"], CHOICE["loss"], CHOICE["transform"], CHOICE["params"], cat_idx)
        val_pred = dm.predict(m_tr, va["X"], CHOICE["transform"])
        interval = dm.Interval(val_pred, va["y"])
        if h == C.PRIMARY_HORIZON:
            importance = dm.permutation_importance(m_tr, CHOICE["transform"], va["X"], va["y"], names, 60_000, 2)
        final = dm.fit(np.vstack([tr["X"], va["X"]]), np.concatenate([tr["y"], va["y"]]), CHOICE["loss"], CHOICE["transform"], CHOICE["params"], cat_idx)
        te_pred = dm.predict(final, te["X"], CHOICE["transform"])
        for split, d, pred in (("validation", va, val_pred), ("test", te, te_pred)):
            for k in BASELINES:
                comparison.append({"model": k, "horizon": h, "split": split, "subset": "all", **M.metrics(d["y"], d["base"][k], naive_mae)})
            comparison.append({"model": "ml_selected", "horizon": h, "split": split, "subset": "all", **M.metrics(d["y"], pred, naive_mae)})
        # deployment refit on every observed target for the future forecast
        all_o = np.arange(C.MIN_HISTORY_DAYS, T - h)
        Xa, oa, pa = bf.assemble(cube, all_o[::max(1, int(np.ceil(len(all_o) * N / MAX_TRAIN_ROWS)))], eligible)
        refit = dm.fit(Xa, y[oa, pa], CHOICE["loss"], CHOICE["transform"], CHOICE["params"], cat_idx)
        results[h] = {"final": final, "refit": refit, "interval": interval, "y": y}
        te_m = M.metrics(te["y"], te_pred, naive_mae)
        log(f"[horizon {h}d] train rows {len(tr['y']):,} (origin stride {stride}) | test WAPE {te_m['WAPE']} MAE {te_m['MAE']} bias {te_m['bias_pct']}% | {time.time() - t:.0f}s")
        del sets

    comp = pd.DataFrame(comparison)[["model", "horizon", "split", "subset", "sample_count", "MAE", "RMSE", "WAPE", "MASE", "bias_pct"]]
    comp.to_csv(R / "model_comparison.csv", index=False)
    imp, _ = importance
    pd.DataFrame(imp, columns=["feature", "importance", "importance_std"]).sort_values("importance", ascending=False).round(5).to_csv(R / "feature_importance.csv", index=False)

    # forecasts.csv: test forecasts (every 7th origin) with actuals, plus the genuine future forecast from the last day
    test_start = pd.DatetimeIndex(dates).get_loc(pd.Timestamp(C.SPLITS["test"][0]))
    fc_o = np.arange(test_start - 1, T - 1, C.FORECAST_ORIGIN_STRIDE_DAYS)
    Xt, ot, pt = bf.assemble(cube, fc_o, eligible)
    Xf, of, pf = bf.assemble(cube, [T - 1], eligible)
    wide_t = {h: dm.predict(results[h]["final"], Xt, CHOICE["transform"]) for h in C.HORIZONS}
    wide_f = {h: dm.predict(results[h]["refit"], Xf, CHOICE["transform"]) for h in C.HORIZONS}
    di = pd.DatetimeIndex(dates)
    frames = []

    # stock levels for display (only when the dataset has an inventory snapshot); the forecasting model itself never uses stock
    inv_lookup = None
    origin_keys = sorted({int(keys["date"][i]) for i in np.concatenate([fc_o, [T - 1]])})
    engine2, conn2 = bf.open_connection()
    try:
        inv_df = pd.read_sql("SELECT date_key, branch_key, medicine_key, closing_quantity FROM warehouse.fact_inventory "
                             f"WHERE date_key IN ({','.join(map(str, origin_keys))})", conn2)
    finally:
        conn2.close()
        engine2.dispose()
    if len(inv_df):
        inv_lookup = inv_df.set_index(["date_key", "branch_key", "medicine_key"])["closing_quantity"]

    def frame(h, split, o, p, actual, pred, lo, hi, wide):
        pr = pairs.iloc[p]
        df = pd.DataFrame({
            "forecast_date": di[o].strftime("%Y-%m-%d"), "target_start": (di[o] + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
            "target_end": (di[o] + pd.Timedelta(days=h)).strftime("%Y-%m-%d"),
            "branch_id": pr["branch_id"].to_numpy(), "medicine_id": pr["medicine_id"].to_numpy(), "medicine_name": pr["medicine_name"].to_numpy(),
            "category": pr["category"].to_numpy(), "horizon": h, "actual_units": actual, "predicted_units": np.round(pred, 3),
            "lower_bound": np.round(lo, 3), "upper_bound": np.round(hi, 3), "model": "ml_selected", "split": split,
            "stockout_flag": np.nan, "current_inventory": np.nan, "recent_stockout_days": np.nan, "censored_target_days": np.nan})
        for hh in C.HORIZONS:
            df[f"forecast_demand_{hh}d"] = np.round(wide[hh], 3)
        if inv_lookup is not None:
            g = keep[p]
            idx = pd.MultiIndex.from_arrays([keys["date"][o], keys["branch"][g // keys["n_medicines"]], keys["medicine"][g % keys["n_medicines"]]])
            cur = inv_lookup.reindex(idx).to_numpy(dtype=float)
            df["current_inventory"] = cur
            df["stockout_flag"] = np.where(np.isnan(cur), np.nan, (cur == 0).astype(float))
        return df

    for h in C.HORIZONS:
        valid = ot + h <= T - 1
        pos = np.flatnonzero(valid)
        o, p = ot[valid], pt[valid]
        ml = wide_t[h][pos]
        lo, hi = results[h]["interval"].bounds(ml)
        frames.append(frame(h, "test", o, p, results[h]["y"][o, p], ml, lo, hi, {k: wide_t[k][pos] for k in C.HORIZONS}))
        mf = wide_f[h]
        lo_f, hi_f = results[h]["interval"].bounds(mf)
        frames.append(frame(h, "future", of, pf, np.full(len(of), np.nan), mf, lo_f, hi_f, wide_f))
    fc = pd.concat(frames, ignore_index=True).sort_values(["split", "horizon", "forecast_date", "branch_id", "medicine_id"], kind="mergesort")
    fc.to_csv(R / "forecasts.csv", index=False)

    test_rows = fc[(fc["split"] == "test") & fc["actual_units"].notna()]
    cover = {int(h): round(float(((g["actual_units"] >= g["lower_bound"]) & (g["actual_units"] <= g["upper_bound"])).mean()), 4) for h, g in test_rows.groupby("horizon")}
    future = fc[fc["split"] == "future"]
    checks = [
        {"check": "no missing predictions", "passed": bool(fc["predicted_units"].notna().all() and (fc["predicted_units"] >= 0).all())},
        {"check": "lower <= forecast <= upper", "passed": bool(((fc["lower_bound"] <= fc["predicted_units"] + 1e-9) & (fc["predicted_units"] <= fc["upper_bound"] + 1e-9)).all())},
        {"check": "future forecasts: one row per pair and horizon", "passed": len(future) == N * len(C.HORIZONS)},
        {"check": "splits are chronological and disjoint", "passed": C.SPLITS["train"][1] < C.SPLITS["validation"][0] <= C.SPLITS["validation"][1] < C.SPLITS["test"][0]},
    ]
    key = comp[(comp["split"] == "test")]
    summary = {
        "run_timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"), "mode": "uploaded sales only (no stock data)",
        "split_dates": {k: list(v) for k, v in C.SPLITS.items()}, "forecast_horizons": C.HORIZONS, "pairs_forecast": int(N), "pairs_total": int(len(pairs_all)),
        "selected_model": "HistGradientBoostingRegressor", "model_config": {**CHOICE, "tuned_on_this_data": False},
        "metrics_test": {f"{h}d": {m: key[(key["horizon"] == h) & (key["model"] == m)].iloc[0][["MAE", "WAPE", "bias_pct"]].to_dict() for m in ["ml_selected"] + BASELINES} for h in C.HORIZONS},
        "interval_empirical_coverage_test": cover, "features": names, "validation": {"checks": len(checks), "failures": sum(not c["passed"] for c in checks), "results": checks},
        "runtime_seconds": round(time.time() - t0, 1)}
    (R / "forecast_summary.json").write_text(json.dumps(summary, indent=2, default=lambda o: o.item() if hasattr(o, "item") else str(o)), encoding="utf-8")
    if summary["validation"]["failures"]:
        raise SystemExit("forecast validation failed: " + json.dumps([c for c in checks if not c["passed"]]))
    log(f"done in {summary['runtime_seconds']}s | validation {len(checks)} checks, 0 failed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
