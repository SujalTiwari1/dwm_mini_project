"""Transform: FACT_SALES.

Grain: one medicine/batch line sold at one branch in one transaction. Rows are NOT aggregated; the source
order (chronological) defines the surrogate sales_key, so keys are reproducible.
"""
import pandas as pd

from .dimensions import date_to_key


def _map(series: pd.Series, mapping: pd.Series, what: str) -> pd.Series:
    out = series.map(mapping)
    if out.isna().any():
        raise ValueError(f"{what}: {int(out.isna().sum())} source values have no dimension row")
    return out.astype("int64")


def build_fact_sales(raw: dict, keys: dict, dim_date: pd.DataFrame) -> pd.DataFrame:
    s = raw["sales"]
    f = pd.DataFrame({
        "sales_key": range(1, len(s) + 1),
        "date_key": date_to_key(s["transaction_date"]),
        "medicine_key": _map(s["medicine_id"], keys["medicine"], "sales.medicine_id"),
        "branch_key": _map(s["branch_id"], keys["branch"], "sales.branch_id"),
        "batch_key": _map(s["batch_id"], keys["batch"], "sales.batch_id"),
        "transaction_id": s["transaction_id"],
        "quantity": s["quantity"],
        "unit_selling_price": s["unit_selling_price"],
        "discount": s["discount"],
        "total_amount": s["total_amount"],
    })
    if not f["date_key"].isin(dim_date["date_key"]).all():
        raise ValueError("sales.transaction_date outside dim_date")
    return f
