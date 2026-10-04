"""Transform: build the six dimension tables.

Surrogate keys are contiguous integers 1..n assigned in natural-key order, so they are deterministic across
runs (the inventory reconstruction relies on this contiguity). dim_date uses the smart key YYYYMMDD.
Source/natural identifiers are always kept next to the surrogate key.
"""
import pandas as pd


def derive_date_range(raw):
    """Calendar span covered by the transactional data (first to last fact date)."""
    lo = min(raw["sales"]["transaction_date"].min(), raw["purchases"]["purchase_date"].min())
    hi = max(raw["sales"]["transaction_date"].max(), raw["purchases"]["purchase_date"].max())
    return pd.Timestamp(lo), pd.Timestamp(hi)


def date_to_key(series: pd.Series) -> pd.Series:
    return series.str.replace("-", "", regex=False).astype("int64")


def build_dim_date(start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    d = pd.date_range(start, end, freq="D")
    return pd.DataFrame({
        "date_key": d.strftime("%Y%m%d").astype("int64"),
        "full_date": d.date,
        "day": d.day,
        "day_of_week": d.dayofweek + 1,                 # ISO: Monday = 1
        "day_name": d.day_name(),
        "week": d.isocalendar().week.astype("int64").to_numpy(),
        "month": d.month,
        "month_name": d.month_name(),
        "quarter": d.quarter,
        "year": d.year,
        "is_weekend": d.dayofweek >= 5,
    })


def _with_key(df: pd.DataFrame, natural: str, key: str) -> pd.DataFrame:
    df = df.sort_values(natural).reset_index(drop=True)
    df.insert(0, key, range(1, len(df) + 1))
    return df


def build_dimensions(raw: dict, start: pd.Timestamp, end: pd.Timestamp) -> dict:
    dims = {"dim_date": build_dim_date(start, end)}

    cat = _with_key(raw["categories"], "category_id", "category_key")
    dims["dim_category"] = cat[["category_key", "category_id", "category_name"]]
    cat_key = cat.set_index("category_id")["category_key"]

    med = _with_key(raw["medicines"], "medicine_id", "medicine_key")
    med["category_key"] = med["category_id"].map(cat_key)
    # demand_profile is generation metadata (would leak the generator's design into analytics): not loaded.
    dims["dim_medicine"] = med[["medicine_key", "medicine_id", "medicine_name", "category_key", "manufacturer",
                                "dosage_form", "strength", "base_price"]]
    med_key = med.set_index("medicine_id")["medicine_key"]

    br = _with_key(raw["branches"], "branch_id", "branch_key")
    dims["dim_branch"] = br[["branch_key", "branch_id", "branch_name", "city", "area"]]
    br_key = br.set_index("branch_id")["branch_key"]

    sup = _with_key(raw["suppliers"], "supplier_id", "supplier_key")
    dims["dim_supplier"] = sup[["supplier_key", "supplier_id", "supplier_name", "city"]]
    sup_key = sup.set_index("supplier_id")["supplier_key"]

    bat = _with_key(raw["batches"], "batch_id", "batch_key")
    bat["medicine_key"] = bat["medicine_id"].map(med_key)
    bat["supplier_key"] = bat["supplier_id"].map(sup_key)
    dims["dim_batch"] = bat[["batch_key", "batch_id", "medicine_key", "supplier_key", "manufacture_date",
                             "expiry_date", "initial_quantity", "purchase_price"]]
    batch_key = bat.set_index("batch_id")["batch_key"]

    for name, df in dims.items():
        if df.isna().any().any():
            raise ValueError(f"{name}: unresolved foreign key or null after transform")
    keys = {"category": cat_key, "medicine": med_key, "branch": br_key, "supplier": sup_key, "batch": batch_key}
    return dims, keys
