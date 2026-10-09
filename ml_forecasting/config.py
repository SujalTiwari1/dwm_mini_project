"""Configuration for the MedStock demand-forecasting layer.

Nothing here (or anywhere in ml_forecasting) reads the private generator ground-truth file. Only observable warehouse data is used.
"""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ML_DIR = Path(__file__).resolve().parent
SQL_DIR = ML_DIR / "sql"
from datasets import paths as _ds
REPORT_DIR = _ds.report_dir("forecast")
GENERATION_METADATA = PROJECT_ROOT / "data" / "metadata" / "generation_metadata.json"   # public dataset descriptor only

RANDOM_STATE = 42
HORIZONS = [7, 14, 30]          # days; 7 is the primary horizon
PRIMARY_HORIZON = 7

# Chronological split. Rows are assigned by where their WHOLE target window lies, so target periods never overlap between splits.
SPLITS = {
    "train": ("2025-01-01", "2026-06-30"),
    "validation": ("2026-07-01", "2026-09-30"),
    "test": ("2026-10-01", "2026-12-31"),
}
MIN_HISTORY_DAYS = 28           # first forecast origin: lags / rolling windows need 28 days of history

LAGS = [1, 2, 3, 7, 14, 21, 28]                 # lag_k = units sold k-1 days before the forecast origin day... see build_features (lag_1 = origin day)
ROLLING_WINDOWS = [7, 14, 28]
ROLLING_MEDIAN_WINDOWS = [7, 28]
DAYS_SINCE_STOCKOUT_CAP = 60

# Pairs excluded from modelling (reasons are reported; exclusions are expected to be rare)
MIN_TRAIN_UNITS_FOR_ELIGIBILITY = 1             # a pair with no observed demand in the training period cannot be forecast from history
MAX_CENSORED_SHARE = 0.50                       # more than half of the training days in stockout = excessive censoring

# Model selection
MODEL_VARIANTS = [                              # (loss, target_transform)
    ("squared_error", "raw"), ("squared_error", "log1p"), ("poisson", "raw"),
]
PARAM_GRID = [                                  # small chronological-validation grid for HistGradientBoostingRegressor
    {"learning_rate": 0.10, "max_iter": 200, "max_leaf_nodes": 31, "min_samples_leaf": 100, "l2_regularization": 0.0},
    {"learning_rate": 0.05, "max_iter": 300, "max_leaf_nodes": 63, "min_samples_leaf": 200, "l2_regularization": 1.0},
    {"learning_rate": 0.10, "max_iter": 200, "max_leaf_nodes": 15, "min_samples_leaf": 400, "l2_regularization": 1.0},
    {"learning_rate": 0.05, "max_iter": 400, "max_leaf_nodes": 31, "min_samples_leaf": 100, "l2_regularization": 5.0},
]
SEARCH_ORIGIN_STRIDE = 3        # the variant / hyperparameter search trains on every 3rd origin day (consecutive days are near-duplicates)
BASELINES = ["naive", "moving_average_7", "moving_average_28", "seasonal_naive_weekly", "seasonal_naive_yearly"]

# Uncertainty: empirical residual quantiles of the validation split, by bins of the point forecast
INTERVAL = {"lower_q": 0.10, "upper_q": 0.90, "bins": 5}     # an approximate 80 percent interval
PERMUTATION_SAMPLE_ROWS = 100_000
PERMUTATION_REPEATS = 3
FORECAST_ORIGIN_STRIDE_DAYS = 7                 # forecasts.csv keeps test forecasts for every 7th origin day (metrics use every day)
SEGMENT_STOCKOUT_QUANTILES = (0.25, 0.75)       # low / high stockout-rate pairs
