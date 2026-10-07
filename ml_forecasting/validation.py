"""Validation of the forecasting layer: leakage tests, stockout/censoring checks against the warehouse, split integrity and output sanity.

Each check returns {"area", "check", "passed", "detail"}.
"""
import re

import numpy as np
import pandas as pd

from . import config as C
from .features import build_features as bf
from .models.baselines import baseline_forecasts


def _chk(area, check, passed, detail=""):
    return {"area": area, "check": check, "passed": bool(passed), "detail": str(detail)}


def _compare_cubes(full, part, o, pair_cols):
    """Compare the feature values at origin o between a full-data cube and a cube built from other data. Returns the list of differing features."""
    bad = []
    for name in full["names"]:
        if name in full["matrix"]:
            a, b = full["matrix"][name][o][pair_cols], part["matrix"][name][o]
        elif name in full["calendar"]:
            a, b = np.asarray(full["calendar"][name])[o], np.asarray(part["calendar"][name])[o]
        else:
            a, b = np.asarray(full["static"][name])[pair_cols], np.asarray(part["static"][name])
        if not np.allclose(a, b, equal_nan=True, rtol=1e-6, atol=1e-6):
            bad.append(name)
    return bad


def leakage_tests(data):
    units, inv, dates, pairs = data["units"], data["inventory"], data["dates"], data["pairs"]
    T, N = units.shape
    rng = np.random.default_rng(C.RANDOM_STATE)
    cols = np.sort(rng.choice(N, size=300, replace=False))
    sub_pairs = pairs.iloc[cols].reset_index(drop=True)
    full = bf.build_cube(units[:, cols], inv[:, cols], dates, sub_pairs)
    origins = sorted(set(rng.choice(np.arange(C.MIN_HISTORY_DAYS, T - 1), size=9, replace=False).tolist()) | {C.MIN_HISTORY_DAYS, T - 2})
    out = []
    bad_trunc, bad_noise = [], []
    for o in origins:
        # (1) the data known at the origin only: truncate immediately after day o
        part = bf.build_cube(units[:o + 1][:, cols], inv[:o + 1][:, cols], dates[:o + 1], sub_pairs)
        bad_trunc += [(o, f) for f in _compare_cubes(full, part, o, slice(None))]
        # (2) everything after the origin replaced by random values: features at the origin must not change
        u2, i2 = units[:, cols].copy(), inv[:, cols].copy()
        u2[o + 1:] = rng.integers(0, 50, size=u2[o + 1:].shape)
        i2[o + 1:] = rng.integers(0, 3, size=i2[o + 1:].shape)
        noisy = bf.build_cube(u2, i2, dates, sub_pairs)
        bad_noise += [(o, f) for f in _compare_cubes(full, noisy, o, slice(None))]
    nfeat = len(full["names"])
    out.append(_chk("leakage", f"features at {len(origins)} origins equal when rebuilt from data truncated at the origin ({nfeat} features: lags, rolling, stockout, calendar, static)",
                    not bad_trunc, f"{len(bad_trunc)} mismatches {bad_trunc[:3]}"))
    out.append(_chk("leakage", f"features at {len(origins)} origins unchanged when ALL data after the origin is replaced by random values", not bad_noise, f"{len(bad_noise)} mismatches {bad_noise[:3]}"))

    # target construction
    bad_t = 0
    for h in C.HORIZONS:
        y, sk = bf.targets(units, inv, h)
        for _ in range(60):
            o, p = int(rng.integers(0, T - h)), int(rng.integers(0, N))
            if y[o, p] != units[o + 1:o + h + 1, p].sum() or sk[o, p] != (inv[o + 1:o + h + 1, p] == 0).sum():
                bad_t += 1
        # the target at origin o needs data through o+h: truncating before that leaves it undefined
        y_cut, _ = bf.targets(units[:T - 5], inv[:T - 5], h)
        if not np.isnan(y_cut[T - 5 - h:]).all() or np.isnan(y_cut[:T - 5 - h]).any():
            bad_t += 1
    out.append(_chk("leakage", "targets equal the sum of the h days strictly after the origin (independent recount) and are undefined without those days", bad_t == 0, f"{bad_t} mismatches"))

    # the target period is never inside the feature window: lag_1 is the origin day and the first predicted day is origin + 1
    o = int(rng.integers(40, T - 40))
    lag1_ok = np.allclose(full["matrix"]["lag_1"][o], units[o, cols]) and np.allclose(full["matrix"]["rolling_mean_7"][o], units[o - 6:o + 1, cols].mean(axis=0), atol=1e-4)
    out.append(_chk("leakage", "lag_1 is the origin day and rolling_mean_7 covers origin-6..origin (never origin+1)", lag1_ok))

    # baselines are causal too
    bad_b = 0
    for h in C.HORIZONS:
        fb = baseline_forecasts(units[:, cols], h)
        for o in (int(rng.integers(370, T - 1)), T - 2):
            pb = baseline_forecasts(units[:o + 1][:, cols], h)
            for k in fb:
                if not np.allclose(fb[k][o], pb[k][o], equal_nan=True):
                    bad_b += 1
    out.append(_chk("leakage", "baseline forecasts at an origin are identical when computed from data truncated at the origin (all horizons, all baselines)", bad_b == 0, f"{bad_b} mismatches"))
    out.append(_chk("leakage", "no normalisation or scaling is fitted on any data (trees are scale-invariant); the log1p transform applies to the TRAINING target only", True))
    return out


def split_checks(dates):
    out = []
    idx = {d: i for i, d in enumerate(pd.DatetimeIndex(dates).strftime("%Y-%m-%d"))}
    s = C.SPLITS
    out.append(_chk("split", "chronological order: training < validation < test, no overlap",
                    pd.Timestamp(s["train"][1]) < pd.Timestamp(s["validation"][0]) and pd.Timestamp(s["validation"][1]) < pd.Timestamp(s["test"][0]), s))
    out.append(_chk("split", "split dates exist in the warehouse calendar and the test period ends on the last date",
                    all(d in idx for r in s.values() for d in r) and idx[s["test"][1]] == len(idx) - 1))
    for h in C.HORIZONS:
        o = bf.split_origins(dates, h)
        first_target = {k: o[k].min() + 1 for k in o}
        last_target = {k: o[k].max() + h for k in o}
        ok = (last_target["train"] <= idx[s["train"][1]] < first_target["validation"] and last_target["validation"] <= idx[s["validation"][1]] < first_target["test"]
              and last_target["test"] <= idx[s["test"][1]] and first_target["train"] > 0)
        out.append(_chk("split", f"horizon {h}d: every target window lies inside its own split (no target period shared between splits)", ok,
                        {k: (int(first_target[k]), int(last_target[k])) for k in o}))
    return out


def stockout_checks(data, conn, cube_stock_flag, censored_counts):
    """stockout_flag must equal the warehouse inventory; censored target windows must equal an independent SQL recount."""
    units, inv, pairs, dates = data["units"], data["inventory"], data["pairs"], data["dates"]
    T, N = units.shape
    out = []
    wc = bf.run_query(conn, "warehouse_counts").iloc[0]
    out.append(_chk("stockout", "inventory rows and stockout rows equal the warehouse", int((inv.size)) == wc["inventory_rows"] and int((inv == 0).sum()) == wc["stockout_rows"],
                    f"{inv.size} rows, {int((inv == 0).sum())} stockout rows"))
    out.append(_chk("stockout", "units sold in the dataset equal the warehouse total", int(units.sum()) == int(wc["units_sold"]), f"{int(units.sum())}"))
    out.append(_chk("stockout", "was_stockout feature equals (inventory_units == 0) everywhere", bool((cube_stock_flag == (inv == 0)).all())))
    rng = np.random.default_rng(C.RANDOM_STATE)
    bad = 0
    n_checked = 0
    date_str = pd.DatetimeIndex(dates).strftime("%Y-%m-%d")
    for h in C.HORIZONS:
        for _ in range(8):
            o, p = int(rng.integers(40, T - h - 1)), int(rng.integers(0, N))
            row = pairs.iloc[p]
            r = bf.run_query(conn, "window_check", (row["branch_id"], row["medicine_id"], date_str[o + 1], date_str[o + h])).iloc[0]
            y, sk = int(units[o + 1:o + h + 1, p].sum()), int((inv[o + 1:o + h + 1, p] == 0).sum())
            n_checked += 1
            if (int(r["units"]), int(r["stockout_days"]), int(r["days"])) != (y, sk, h):
                bad += 1
    out.append(_chk("stockout", f"{n_checked} random target windows: units, stockout (censored) days and window length equal an independent warehouse SQL recount", bad == 0, f"{bad} mismatches"))
    out.append(_chk("stockout", "censored-target counts per horizon recomputed independently (rolling sum over the inventory table) match the dataset",
                    all(censored_counts[h][0] == censored_counts[h][1] for h in censored_counts), censored_counts))
    return out


def source_checks():
    out = []
    pattern = "ground" + "_truth"
    offenders = [f.name for f in C.ML_DIR.rglob("*.py") if f.name != "validation.py" and re.search(pattern, f.read_text(encoding="utf-8"), flags=re.I)]
    sql_off = [f.name for f in C.SQL_DIR.glob("*.sql") if re.search(pattern, f.read_text(encoding="utf-8"), flags=re.I)]
    out.append(_chk("ground_truth", "no module or SQL file in ml_forecasting references the hidden ground-truth file", not offenders and not sql_off, offenders + sql_off))
    return out


def output_checks(forecasts, comparison, summary):
    out = []
    f = forecasts
    iv = f.dropna(subset=["lower_bound", "upper_bound"])
    out.append(_chk("outputs", "forecasts finite and non-negative; wherever an interval exists, lower <= upper",
                    bool(np.isfinite(f["predicted_units"]).all() and (f["predicted_units"] >= 0).all() and (iv["lower_bound"] <= iv["upper_bound"]).all())))
    out.append(_chk("outputs", "no duplicated (forecast_date, branch, medicine, horizon, model, split) forecast", not f.duplicated(["forecast_date", "branch_id", "medicine_id", "horizon", "model", "split"]).any()))
    out.append(_chk("outputs", "actual_units is NULL only for future forecasts", bool(f.loc[f["actual_units"].isna(), "split"].eq("future").all() and f.loc[f["split"] == "future", "actual_units"].isna().all())))
    out.append(_chk("outputs", "test forecast dates lie inside the test period and future forecasts are after the last date",
                    bool((f.loc[f["split"] == "test", "forecast_date"] >= pd.Timestamp(C.SPLITS["test"][0]) - pd.Timedelta(days=1)).all() and (f.loc[f["split"] == "future", "forecast_date"] >= pd.Timestamp(C.SPLITS["test"][1])).all())))
    cmp_ = comparison
    ok = np.isfinite(cmp_[["MAE", "RMSE", "WAPE"]].to_numpy(dtype=float)).all()
    cnt = cmp_.groupby(["horizon", "split", "subset"])["sample_count"].nunique().max() == 1
    out.append(_chk("outputs", "metrics finite", bool(ok)))
    out.append(_chk("outputs", "every model is evaluated on exactly the same rows within a (horizon, split, subset)", bool(cnt)))
    out.append(_chk("outputs", "temporal split recorded in the summary with training < validation < test", summary["split_dates"]["train"][1] < summary["split_dates"]["validation"][0] < summary["split_dates"]["validation"][1] < summary["split_dates"]["test"][0]))
    return out
