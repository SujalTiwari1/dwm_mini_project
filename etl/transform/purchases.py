"""Transform: FACT_PURCHASE.

Grain: one batch delivery line (one batch received at one branch from one supplier). Not aggregated.
"""
import pandas as pd

from .dimensions import date_to_key
from .sales import _map


def build_fact_purchase(raw: dict, keys: dict, dim_date: pd.DataFrame) -> pd.DataFrame:
    p = raw["purchases"]
    f = pd.DataFrame({
        "purchase_key": range(1, len(p) + 1),
        "date_key": date_to_key(p["purchase_date"]),
        "medicine_key": _map(p["medicine_id"], keys["medicine"], "purchases.medicine_id"),
        "branch_key": _map(p["branch_id"], keys["branch"], "purchases.branch_id"),
        "supplier_key": _map(p["supplier_id"], keys["supplier"], "purchases.supplier_id"),
        "batch_key": _map(p["batch_id"], keys["batch"], "purchases.batch_id"),
        "purchase_id": p["purchase_id"],
        "quantity": p["quantity"],
        "unit_purchase_price": p["unit_purchase_price"],
        "total_cost": p["total_cost"],
    })
    if not f["date_key"].isin(dim_date["date_key"]).all():
        raise ValueError("purchases.purchase_date outside dim_date")
    return f
