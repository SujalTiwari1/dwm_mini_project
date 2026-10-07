"""Forecast accuracy metrics (computed on the pooled rows of a split).

  MAE   mean absolute error, in units over the horizon.
  RMSE  root mean squared error; penalises large misses more than MAE.
  WAPE  weighted absolute percentage error = sum|error| / sum(actual). Stable when many actuals are zero (unlike MAPE, which is not used).
  MASE  pooled MAE of the model divided by the pooled in-sample MAE of the naive forecast (previous h days) on the training split.
        Below 1 means better than the in-sample naive benchmark.
  bias  sum(prediction - actual) / sum(actual): systematic over- (+) or under- (-) forecasting.
"""
import numpy as np
import pandas as pd


def metrics(actual, pred, naive_train_mae=None):
    actual, pred = np.asarray(actual, dtype=float), np.asarray(pred, dtype=float)
    ok = np.isfinite(actual) & np.isfinite(pred)
    a, p = actual[ok], pred[ok]
    n = int(ok.sum())
    if n == 0:
        return {"sample_count": 0, "MAE": np.nan, "RMSE": np.nan, "WAPE": np.nan, "MASE": np.nan, "bias_pct": np.nan}
    err = p - a
    mae = float(np.abs(err).mean())
    total = float(a.sum())
    return {"sample_count": n, "MAE": round(mae, 4), "RMSE": round(float(np.sqrt((err ** 2).mean())), 4),
            "WAPE": round(float(np.abs(err).sum() / total), 4) if total > 0 else np.nan,
            "MASE": round(mae / naive_train_mae, 4) if naive_train_mae else np.nan,
            "bias_pct": round(100 * float(err.sum() / total), 2) if total > 0 else np.nan}


def segment_table(df, model_cols, segment_col, naive_train_mae=None):
    """df holds 'actual', one column per model and a segment column. Returns one row per (segment, model)."""
    rows = []
    for seg, g in df.groupby(segment_col, sort=True):
        for m in model_cols:
            rows.append({"segment": f"{segment_col}={seg}", "model": m, **metrics(g["actual"], g[m], naive_train_mae)})
    return pd.DataFrame(rows)
