"""Gradient-boosted demand model (scikit-learn HistGradientBoostingRegressor), direct multi-horizon: one model per horizon from ONE pipeline.

Target transform options: raw units, or log1p(units) with expm1 back-transform (predictions are clipped at zero). The loss may be squared error or
Poisson (counts). Feature importance is permutation importance on the original scale (sklearn 1.4's HistGradientBoosting has no native importances).
"""
import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor

from .. import config as C


def categorical_indices(names, categorical):
    return [names.index(c) for c in categorical]


def fit(X, y, loss, transform, params, cat_idx):
    target = np.log1p(y) if transform == "log1p" else y
    model = HistGradientBoostingRegressor(loss=loss, random_state=C.RANDOM_STATE, early_stopping=False, categorical_features=cat_idx, **params)
    return model.fit(X, target)


def predict(model, X, transform):
    p = model.predict(X)
    if transform == "log1p":
        p = np.expm1(p)
    return np.clip(p, 0.0, None)


def permutation_importance(model, transform, X, y, names, n_rows, repeats):
    """Increase in mean absolute error when one feature column is shuffled (original scale). Deterministic (seeded)."""
    rng = np.random.default_rng(C.RANDOM_STATE)
    take = rng.choice(len(X), size=min(n_rows, len(X)), replace=False)
    Xs, ys = X[take].copy(), y[take]
    base = np.abs(predict(model, Xs, transform) - ys).mean()
    rows = []
    for j, name in enumerate(names):
        col = Xs[:, j].copy()
        deltas = []
        for _ in range(repeats):
            Xs[:, j] = rng.permutation(col)
            deltas.append(np.abs(predict(model, Xs, transform) - ys).mean() - base)
        Xs[:, j] = col
        rows.append((name, float(np.mean(deltas)), float(np.std(deltas))))
    return rows, float(base)


class Interval:
    """Approximate prediction interval from validation residuals (actual - prediction), by bins of the point forecast.
    This is an empirical, level-dependent error band, not a formal probabilistic forecast."""

    def __init__(self, pred, actual):
        cfg = C.INTERVAL
        self.edges = np.quantile(pred, np.linspace(0, 1, cfg["bins"] + 1))[1:-1]
        b = np.searchsorted(self.edges, pred, side="right")
        res = actual - pred
        self.lo = np.array([np.quantile(res[b == i], cfg["lower_q"]) if (b == i).any() else 0.0 for i in range(cfg["bins"])])
        self.hi = np.array([np.quantile(res[b == i], cfg["upper_q"]) if (b == i).any() else 0.0 for i in range(cfg["bins"])])

    def bounds(self, pred):
        b = np.searchsorted(self.edges, pred, side="right")
        return np.clip(pred + self.lo[b], 0.0, None), np.clip(pred + self.hi[b], 0.0, None)
