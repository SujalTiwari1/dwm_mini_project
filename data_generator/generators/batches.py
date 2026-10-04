import numpy as np
import pandas as pd

from .. import config as C
from ..utils import make_id

COLUMNS = [
    "batch_id", "medicine_id", "supplier_id", "manufacture_date",
    "expiry_date", "initial_quantity", "purchase_price",
]


class BatchFactory:
    """Creates a manufacturing lot on delivery.

    Manufacture date < purchase date < expiry date. Expiry = manufacture date
    + the medicine's shelf life. A small share of lots arrive near-dated.
    """

    def __init__(self, rng: np.random.Generator):
        self.rng = rng
        self.rows = []

    def create(self, medicine_id, supplier_id, purchase_date, shelf_months, price, quantity, near_dated_prob, allow_near_dated=True):
        cfg = C.PURCHASE_CONFIG
        purchase_ts = pd.Timestamp(purchase_date)
        shelf_days = (purchase_ts + pd.DateOffset(months=shelf_months) - purchase_ts).days
        near_dated = self.rng.random() < near_dated_prob and allow_near_dated   # always draw: keeps RNG stream stable
        if near_dated:
            lo, hi = cfg["near_dated_remaining_days"]
            expiry_ts = purchase_ts + pd.Timedelta(days=int(self.rng.integers(lo, hi + 1)))
            manufacture_ts = expiry_ts - pd.DateOffset(months=shelf_months)
        else:
            lag_lo, lag_hi = cfg["manufacture_lag_days"]
            lag_hi = min(lag_hi, shelf_days - cfg["min_remaining_days"])
            lag = int(self.rng.integers(lag_lo, max(lag_lo + 1, lag_hi + 1)))
            manufacture_ts = purchase_ts - pd.Timedelta(days=lag)
            expiry_ts = manufacture_ts + pd.DateOffset(months=shelf_months)
        batch_id = make_id("BAT", len(self.rows) + 1, 6)
        self.rows.append((
            batch_id, medicine_id, supplier_id, manufacture_ts.date(),
            expiry_ts.date(), int(quantity), float(price),
        ))
        return batch_id, expiry_ts.date()

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.rows, columns=COLUMNS)
