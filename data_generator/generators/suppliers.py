import numpy as np
import pandas as pd

from .. import config as C
from ..catalog import SUPPLIER_POOL
from ..utils import make_id


def generate_suppliers(n: int, rng: np.random.Generator):
    """Return (suppliers df, internal dict supplier_id -> {price_factor, categories})."""
    if n > len(SUPPLIER_POOL):
        raise ValueError(f"num_suppliers={n} exceeds pool ({len(SUPPLIER_POOL)}); extend catalog.SUPPLIER_POOL")
    cat_ids = [c[0] for c in C.CATEGORIES]
    lo, hi = C.PURCHASE_CONFIG["supplier_factor"]
    rows, internal = [], {}
    for i in range(n):
        sid = make_id("SUP", i + 1)
        name, city = SUPPLIER_POOL[i]
        # Each supplier specialises in 2 categories (round-robin guarantees coverage) + 2 random extras.
        cats = {cat_ids[(2 * i) % len(cat_ids)], cat_ids[(2 * i + 1) % len(cat_ids)]}
        for j in rng.choice(len(cat_ids), size=2, replace=False):
            cats.add(cat_ids[j])
        discount = bool(rng.random() < C.PURCHASE_CONFIG["discount_supplier_share"])
        rows.append((sid, name, city))
        internal[sid] = {
            "price_factor": round(float(rng.uniform(lo, hi)) * (
                C.PURCHASE_CONFIG["discount_supplier_price_factor"] if discount else 1.0), 4),
            "near_dated_prob": (C.PURCHASE_CONFIG["discount_supplier_near_dated_prob"] if discount
                                else C.PURCHASE_CONFIG["near_dated_lot_prob"]),
            "discount_supplier": discount,
            "lead_time_days": int(rng.integers(C.PURCHASE_CONFIG["supplier_lead_days"][0],
                                               C.PURCHASE_CONFIG["supplier_lead_days"][1] + 1)),
            "categories": [c for c in cat_ids if c in cats],
        }
    return pd.DataFrame(rows, columns=["supplier_id", "supplier_name", "city"]), internal


def build_supplier_map(suppliers_internal, medicines: pd.DataFrame, rng: np.random.Generator):
    """medicine_id -> (list of supplier_ids, list of selection weights)."""
    lo, hi = C.PURCHASE_CONFIG["suppliers_per_medicine"]
    primary = C.PURCHASE_CONFIG["primary_supplier_share"]
    all_sids = list(suppliers_internal)
    result = {}
    for med_id, cat in zip(medicines["medicine_id"], medicines["category_id"]):
        eligible = [s for s in all_sids if cat in suppliers_internal[s]["categories"]] or all_sids
        k = min(len(eligible), int(rng.integers(lo, hi + 1)))
        picks = [eligible[j] for j in rng.choice(len(eligible), size=k, replace=False)]
        weights = [1.0] if k == 1 else [primary] + [(1 - primary) / (k - 1)] * (k - 1)
        result[med_id] = (picks, weights)
    return result
