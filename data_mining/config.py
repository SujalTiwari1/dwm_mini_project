"""Configuration for the MedStock data-mining layer.

Every threshold is a-priori and documented. None of them is tuned against data/metadata/ground_truth_private.json:
the hidden ground truth is read only by data_mining/evaluation after all detections have been written.
"""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MINING_DIR = Path(__file__).resolve().parent
SQL_DIR = MINING_DIR / "sql"
REPORT_DIR = MINING_DIR / "reports"
METADATA_DIR = PROJECT_ROOT / "data" / "metadata"
GENERATION_METADATA = METADATA_DIR / "generation_metadata.json"      # public dataset descriptor (no hidden truth)
GROUND_TRUTH_PRIVATE = METADATA_DIR / "ground_truth_private.json"    # evaluation ONLY (data_mining/evaluation/evaluate.py)

RANDOM_STATE = 42       # seeds KMeans, PCA (svd solver), IsolationForest

# ---------------------------------------------------------------------------
# Association rules (Apriori on transaction -> set of medicines)
# ---------------------------------------------------------------------------
ASSOCIATION = {
    "min_support": 0.0005,        # >= ~307 of 613k transactions; chosen from the sensitivity table written to association_summary.json
    "min_confidence": 0.10,
    "min_lift": 1.0,              # keep lift > 1 (strictly)
    "max_itemset_len": 3,         # rules over at most 3 medicines
    "sensitivity_supports": [0.002, 0.001, 0.0005, 0.0003, 0.0002],
    "top_rules_in_summary": 15,
}

# ---------------------------------------------------------------------------
# Medicine clustering (K-Means on standardised, log-transformed behaviour features)
# ---------------------------------------------------------------------------
CLUSTERING = {
    "k_range": list(range(2, 9)),
    "n_init": 20,
    "skew_threshold": 1.0,             # log1p applied to non-negative features with |skewness| above this
    "redundancy_threshold": 0.90,      # drop a feature whose |Spearman r| with an already kept feature exceeds this
    "min_k_for_selection": 3,          # K = 2 is a trivial high/low split; select among K >= 3 (all K reported)
    "k_parsimony_tolerance": 0.02,     # choose the smallest K >= 3 whose silhouette is within this of the best (curve is flat)
    "days_of_inventory_cap": 365,      # no recent demand -> cover capped at one year
    # candidate features in priority order (first of a redundant pair is kept)
    "candidate_features": [
        "total_units_sold", "avg_selling_price", "demand_dispersion", "weekly_demand_cv", "inventory_turnover", "stockout_rate",
        "days_of_inventory", "total_revenue", "avg_purchase_cost", "expired_value", "expiry_risk_value",
        "sales_days", "avg_inventory_value", "stockout_event_count", "purchase_cost", "avg_daily_revenue",
        "avg_weekly_units", "avg_daily_units", "purchase_units", "avg_inventory_units", "current_inventory_value",
        "expired_units", "zero_sales_days", "weekly_demand_std", "current_inventory_units", "stockout_days",
    ],
}

# ---------------------------------------------------------------------------
# Anomaly detection (all rolling statistics use only observations up to the evaluated day)
# ---------------------------------------------------------------------------
ANOMALY = {
    "short_window": 7,              # days summed to form the "current level"
    "baseline_window": 56,          # days of prior 7-day sums used for median / MAD
    "burn_in_days": 70,             # the baseline needs 2*7 + 56 - 2 = 68 days of history; earlier days are never flagged
    # Cut-offs follow a multiple-testing argument: about 1.65M overlapping windows are tested, so a one-sided z of 3.5 would flag ~380 windows
    # per direction by chance even for Gaussian data (count data has heavier tails). Cut-offs near 5 (7-day level) and 6 (single day) keep chance flags rare.
    # They were revised once, BEFORE any ground-truth evaluation, because the first pass (3.5 / 4.0) flagged ~24k episodes, an implausible alert volume.
    "robust_z_threshold": 5.0,      # modified z-score cut-off on the 7-day level
    "daily_z_threshold": 6.0,       # single-day spike cut-off (daily counts are noisier)
    "mad_to_sigma": 1.4826,
    "min_scale": 0.5,               # floor on the robust scale in sqrt-count units (the Poisson sd of sqrt(x) is about 0.5)
    "stockout_run_days": 7,         # a stockout lasting this many consecutive days (a full week) is a "stockout pattern"
    "purchase_baseline_lots": 8,    # prior lots of a medicine needed before judging a new lot
    "purchase_qty_z_threshold": 5.0,        # judged on units per delivered branch (a lot may go to 1 to 5 branches)
    "purchase_qty_min_ratio": 2.5,          # and at least 2.5x the medicine's prior median per-branch lot size
    "purchase_gap_z_threshold": 5.0,
    "purchase_gap_min_ratio": 2.0,  # and the gap must be at least 2x the medicine's prior median gap
    "purchase_cost_z_threshold": 5.0,
    "purchase_cost_min_rel_dev": 0.25,   # and unit cost must deviate by at least 25 percent from the prior median
    "isolation_contamination": 0.003,    # share of rows flagged by Isolation Forest (an operating budget, not a truth estimate)
    "purchase_isolation_contamination": 0.01,   # share of purchase lots flagged by Isolation Forest (operating budget)
    "isolation_estimators": 200,
    "isolation_max_samples": 4096,
    "episode_gap_days": 3,          # flagged days of one series within this gap form one episode
    "min_abs_units_7d_for_demand_flag": 5,   # ignore demand movements below 5 units per 7 days (too small to be meaningful)
}
