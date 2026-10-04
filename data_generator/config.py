"""Central configuration for the MedStock synthetic dataset generator.

Every tunable number lives here. To scale from the prototype to the full
dataset, change DATASET_CONFIG only (and optionally DEMAND/ANOMALY knobs).
"""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw"
METADATA_DIR = PROJECT_ROOT / "data" / "metadata"

# --------------------------------------------------------------------------
# Dataset size / period / seed
# --------------------------------------------------------------------------
DATASET_CONFIG = {
    "num_medicines": 500,
    "num_branches": 5,
    "num_suppliers": 30,
    "start_date": "2025-01-01",
    "end_date": "2026-12-31",
    "random_seed": 42,
    "branch_city": "Mumbai",
    # Global multiplier on per-medicine demand (row volume scales linearly with it).
    # 1.0 = the 20-medicine prototype level; the 500-medicine dataset is calibrated to ~1M sales lines.
    "demand_scale": 0.22,
    # Dataset identity. frozen_on is a fixed label (not the wall-clock date) so that regenerating
    # with the same config gives byte-identical output, metadata included.
    "dataset_version": "1.0",
    "frozen_on": "2026-10-04",
}

# --------------------------------------------------------------------------
# Categories (fixed)
# --------------------------------------------------------------------------
CATEGORIES = [
    ("CAT001", "Analgesics"),
    ("CAT002", "Antibiotics"),
    ("CAT003", "Antipyretics"),
    ("CAT004", "Antihistamines"),
    ("CAT005", "Gastrointestinal"),
    ("CAT006", "Cardiovascular"),
    ("CAT007", "Antidiabetic"),
    ("CAT008", "Respiratory"),
    ("CAT009", "Vitamins"),
    ("CAT010", "Dermatological"),
]

# Per-category behaviour.
#   season_amp      : amplitude of the annual sinusoid (0.10 = +-10% swing)
#   season_peak_doy : day-of-year of the seasonal peak
#   qty_lambda      : units per sale line = 1 + Poisson(qty_lambda)
#   variability_scale: multiplier on the medicine's demand variability
CATEGORY_CONFIG = {
    "CAT001": dict(season_amp=0.08, season_peak_doy=15,  qty_lambda=0.35, variability_scale=1.0),
    "CAT002": dict(season_amp=0.12, season_peak_doy=200, qty_lambda=0.30, variability_scale=1.0),
    "CAT003": dict(season_amp=0.15, season_peak_doy=200, qty_lambda=0.30, variability_scale=1.0),
    "CAT004": dict(season_amp=0.18, season_peak_doy=70,  qty_lambda=0.30, variability_scale=1.1),
    "CAT005": dict(season_amp=0.12, season_peak_doy=205, qty_lambda=0.35, variability_scale=1.0),
    "CAT006": dict(season_amp=0.03, season_peak_doy=15,  qty_lambda=1.00, variability_scale=0.6),  # chronic
    "CAT007": dict(season_amp=0.02, season_peak_doy=15,  qty_lambda=1.00, variability_scale=0.6),  # chronic
    "CAT008": dict(season_amp=0.25, season_peak_doy=20,  qty_lambda=0.15, variability_scale=1.1),
    "CAT009": dict(season_amp=0.10, season_peak_doy=15,  qty_lambda=0.50, variability_scale=1.0),
    "CAT010": dict(season_amp=0.12, season_peak_doy=200, qty_lambda=0.10, variability_scale=1.0),
}

# --------------------------------------------------------------------------
# Demand profiles (HIGH / MEDIUM / LOW)
#   base_lines          : sale lines per day per branch (before multipliers)
#   variability         : sigma of the daily lognormal noise
#   target_cover_days   : order-up-to level, in days of expected demand
#   reorder_point_days  : reorder when stock < this many days of demand
#   moq_units           : minimum order quantity (units, summed over branches)
#   mix                 : share of profiles for medicines beyond the curated list
# --------------------------------------------------------------------------
DEMAND_PROFILES = {
    # base_lines: (min, max) sale lines/day/branch; the draw is skewed inside the range with
    # Beta(*skew) so that most medicines sit near the low end and a few reach the top (long tail).
    "HIGH":   dict(base_lines=(5.0, 24.0), skew=(1.0, 2.2), variability=(0.10, 0.20), target_cover_days=21,
                   reorder_point_days=7,  moq_units=60, mix=0.10),
    "MEDIUM": dict(base_lines=(1.2, 4.5), skew=(1.0, 1.8), variability=(0.22, 0.35), target_cover_days=30,
                   reorder_point_days=10, moq_units=60, mix=0.30),
    "LOW":    dict(base_lines=(0.15, 1.0), skew=(1.0, 1.5), variability=(0.40, 0.60), target_cover_days=40,
                   reorder_point_days=14, moq_units=150, mix=0.60),
}

TREND_MIX = {"stable": 0.60, "increasing": 0.20, "decreasing": 0.20}
TREND_ANNUAL_RATE = {          # annualised log-growth ranges
    "stable": (-0.02, 0.02),
    "increasing": (0.05, 0.18),
    "decreasing": (-0.18, -0.05),
}

# Day-of-week demand multipliers (Mon..Sun)
DOW_FACTORS = [1.00, 0.98, 0.98, 1.00, 1.05, 1.12, 0.90]

# Branch behaviour. First entries are fixed; extra branches get random ones.
BRANCH_PROFILES = [
    {"multiplier": 1.20, "category_affinity": {"CAT008": 1.15}},                    # BR001
    {"multiplier": 0.90, "category_affinity": {"CAT006": 1.12, "CAT007": 1.12}},    # BR002
]
RANDOM_BRANCH_MULTIPLIER = (0.80, 1.25)
RANDOM_BRANCH_AFFINITY = (1.08, 1.18)   # 1-2 random categories get this boost

# --------------------------------------------------------------------------
# Baskets / associations
# --------------------------------------------------------------------------
BASKET_SIZE_PROBS = {1: 0.58, 2: 0.27, 3: 0.10, 4: 0.05}

# (antecedent_key, consequent_key, probability that the consequent is added to a basket
#  containing the antecedent). Keys refer to data_generator/catalog.py. Probabilities are
#  large relative to the consequent's baseline so that P(B|A) >> P(B|not A), but never 1.0.
ASSOCIATION_RULES = [
    ("metformin_500", "glimepiride_2", 0.40),
    ("amlodipine_5", "atorvastatin_10", 0.40),
    ("azithromycin_500", "paracetamol_650", 0.45),
    ("diclofenac_50", "pantoprazole_40", 0.40),
    ("cetirizine_10", "ambroxol_levosalbutamol", 0.25),
    ("ambroxol_levosalbutamol", "vitamin_c_500", 0.30),
    ("omeprazole_20", "domperidone_10", 0.35),
    ("clotrimazole_cream", "mupirocin_oint", 0.30),
]

# --------------------------------------------------------------------------
# Sales / pricing
# --------------------------------------------------------------------------
SALES_CONFIG = {
    "discount_prob": 0.12,
    "discount_pcts": [0.05, 0.10, 0.15],
    "monthly_price_jitter": 0.03,       # selling price = base * (1 +- 3%), fixed per medicine-month
}

PURCHASE_CONFIG = {
    "purchase_price_ratio": (0.68, 0.85),   # of base price, before supplier factor
    "supplier_factor": (0.97, 1.03),
    "suppliers_per_medicine": (1, 3),
    "primary_supplier_share": 0.60,
    # Share of lots delivered with short remaining life. "Discount" suppliers ship more of them
    # (and are slightly cheaper); this is where moderate/slow movers pick up expiry risk.
    "near_dated_lot_prob": 0.08,
    "discount_supplier_share": 0.30,
    "discount_supplier_near_dated_prob": 0.45,
    "discount_supplier_price_factor": 0.95,
    "near_dated_remaining_days": (20, 200),
    "manufacture_lag_days": (14, 240),
    "min_remaining_days": 90,               # for normal (non near-dated) lots
    # Replenishment realism: orders arrive after a lead time and policy parameters vary by medicine.
    "supplier_lead_days": (2, 5),           # per-supplier typical lead time
    "lead_noise_days": (-1, 1),             # inclusive daily jitter added to the lead time
    "delay_prob": 0.05,                     # random extra delay on an order
    "delay_days": (4, 10),
    "policy_jitter": (0.80, 1.30),
    # Physical floors so that tiny per-medicine volumes do not cause artificial stockouts:
    "min_reorder_point_units": 3,           # never let a branch run to zero before reordering
    "scale_moq_with_demand": True,          # MOQ shrinks with demand_scale (a scaled-down store orders smaller packs)
    "min_moq_units": 6,          # per-medicine factor on reorder point / cover
}

# --------------------------------------------------------------------------
# Anomalies (ground truth goes to data/metadata/ground_truth_private.json)
# --------------------------------------------------------------------------
ANOMALY_CONFIG = {
    "rate_per_medicine_year": 0.15,
    "min_events": 5,
    "type_weights": {
        "spike": 0.25,
        "drop": 0.20,
        "branch_surge": 0.20,
        "bulk_purchase": 0.15,
        "supply_disruption": 0.20,
    },
    "spike": {"duration": (4, 10), "multiplier": (2.5, 4.0)},
    "drop": {"duration": (7, 15), "multiplier": (0.15, 0.45)},
    "branch_surge": {"duration": (10, 21), "multiplier": (1.8, 2.6)},
    "bulk_purchase": {"multiplier": (3.0, 5.0)},
    "supply_disruption": {"duration": (10, 20), "extra_lead_days": (8, 15)},
    # Visibility guard: anomalies are multipliers on the medicine's own baseline, but a
    # multiplier on a tiny baseline is invisible. Windows are lengthened / multipliers raised
    # (up to the caps) until the expected deviation is at least this many sale lines.
    "min_expected_deviation_lines": 25,
    "max_duration": 30,
    "max_spike_multiplier": 8.0,
}

# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------
VALIDATION_CONFIG = {
    "min_shelf_life_days": 180,
    "max_shelf_life_days": 1100,
    "money_tolerance": 0.005,
}
