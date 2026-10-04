"""Transform: reconstruct FACT_INVENTORY (a daily periodic snapshot) from purchases, sales and batch expiry.

There is no inventory source file. For every (date, branch, medicine):

    opening + purchased - sold - expired = closing         (opening on day 1 = 0, opening(t) = closing(t-1))

* purchased: units received that day (fact_purchase).
* sold:      units sold that day from specific batches (fact_sales). The sales batch allocation (FEFO) in the
             source is authoritative: nothing is re-allocated here.
* expired:   for each (branch, batch), whatever is left (received - sold) is written off on the batch's expiry date
             if that date falls inside the calendar; expired stock is unsellable from that day on.
* closing_value_at_cost: closing stock valued at each batch's own purchase price (exact, in integer cents).

The snapshot is dense (every date x branch x medicine), so a row with closing_quantity = 0 is a stockout day.
"""
import numpy as np
import pandas as pd


def money_cents(s: pd.Series) -> pd.Series:
    """'123.45' -> 12345 (the extract step guarantees exact 2-decimal strings)."""
    return s.str.replace(".", "", regex=False).astype("int64")


def _expiry_checks(fs, fp, batch, expiry_key):
    sale_exp = fs["batch_key"].map(expiry_key)
    bad = int((fs["date_key"] >= sale_exp).sum())
    if bad:
        raise ValueError(f"{bad} sales lines are dated on/after their batch expiry date")
    pur_exp = fp["batch_key"].map(expiry_key)
    bad = int((fp["date_key"] >= pur_exp).sum())
    if bad:
        raise ValueError(f"{bad} purchases are dated on/after their batch expiry date")


def build_fact_inventory(dims: dict, fact_sales: pd.DataFrame, fact_purchase: pd.DataFrame):
    """Return (fact_inventory DataFrame, totals dict)."""
    dkeys = dims["dim_date"]["date_key"].to_numpy()
    T = len(dkeys)
    if not (np.diff(dkeys) > 0).all():
        raise ValueError("dim_date keys must be strictly increasing")
    B, M = len(dims["dim_branch"]), len(dims["dim_medicine"])
    P = B * M
    for name, col in (("dim_branch", "branch_key"), ("dim_medicine", "medicine_key")):
        if not (dims[name][col].to_numpy() == np.arange(1, len(dims[name]) + 1)).all():
            raise ValueError(f"{name}.{col} must be contiguous 1..n")
    day_pos = pd.Series(np.arange(T), index=dkeys)

    batch = dims["dim_batch"].set_index("batch_key")
    price_c = money_cents(batch["purchase_price"])
    expiry = pd.to_datetime(batch["expiry_date"])
    expiry_key = expiry.dt.strftime("%Y%m%d").astype("int64")
    _expiry_checks(fact_sales, fact_purchase, batch, expiry_key)

    def flat_index(df, date_col="date_key"):
        pair = (df["branch_key"].to_numpy() - 1) * M + (df["medicine_key"].to_numpy() - 1)
        return pair * T + df[date_col].map(day_pos).to_numpy()

    def accumulate(idx, weights):
        return np.rint(np.bincount(idx, weights=weights.astype("float64"), minlength=P * T)).astype("int64")

    # --- flows ---------------------------------------------------------------
    pi, si = flat_index(fact_purchase), flat_index(fact_sales)
    purchased = accumulate(pi, fact_purchase["quantity"].to_numpy())
    sold = accumulate(si, fact_sales["quantity"].to_numpy())
    purchased_val = accumulate(pi, (fact_purchase["quantity"] * fact_purchase["batch_key"].map(price_c)).to_numpy())
    sold_val = accumulate(si, (fact_sales["quantity"] * fact_sales["batch_key"].map(price_c)).to_numpy())

    # --- expiry write-off: remaining stock of each (branch, batch) on its expiry date --------
    received = fact_purchase.groupby(["branch_key", "batch_key"])["quantity"].sum()
    sold_b = fact_sales.groupby(["branch_key", "batch_key"])["quantity"].sum()
    remaining = received.sub(sold_b, fill_value=0)
    if (remaining < 0).any():
        raise ValueError("a batch was sold in a branch beyond what that branch received")
    rem = remaining[remaining > 0].rename("remaining").reset_index()
    rem["medicine_key"] = rem["batch_key"].map(batch["medicine_key"])
    rem["expiry_key"] = rem["batch_key"].map(expiry_key)
    rem = rem[rem["expiry_key"].isin(dkeys)]          # only expiries inside the calendar are written off
    rem["value_c"] = rem["remaining"] * rem["batch_key"].map(price_c)
    ei = flat_index(rem, "expiry_key")
    expired = accumulate(ei, rem["remaining"].to_numpy())
    expired_val = accumulate(ei, rem["value_c"].to_numpy())

    # --- running balances ---------------------------------------------------------
    delta = (purchased - sold - expired).reshape(P, T)
    closing = delta.cumsum(axis=1)
    opening = closing - delta                         # opening(t) = closing(t-1); 0 on day 1
    delta_val = (purchased_val - sold_val - expired_val).reshape(P, T)
    closing_val = delta_val.cumsum(axis=1)
    if closing.min() < 0 or closing_val.min() < 0:
        raise ValueError("negative inventory produced by the reconstruction")

    def to_rows(a):   # [P, T] -> rows ordered by date, then branch, then medicine
        return a.reshape(B, M, T).transpose(2, 0, 1).reshape(-1)

    fi = pd.DataFrame({
        "date_key": np.repeat(dkeys, B * M),
        "branch_key": np.tile(np.repeat(np.arange(1, B + 1), M), T),
        "medicine_key": np.tile(np.arange(1, M + 1), T * B),
        "opening_quantity": to_rows(opening),
        "purchased_quantity": to_rows(purchased.reshape(P, T)),
        "sold_quantity": to_rows(sold.reshape(P, T)),
        "expired_quantity": to_rows(expired.reshape(P, T)),
        "closing_quantity": to_rows(closing),
        "closing_value_at_cost": to_rows(closing_val) / 100.0,
    })
    totals = {
        "purchased": int(purchased.sum()), "sold": int(sold.sum()), "expired": int(expired.sum()),
        "closing_final_day": int(closing[:, -1].sum()), "rows": len(fi),
        "expired_batches": int(rem["batch_key"].nunique()), "expired_value_cents": int(expired_val.sum()),
    }
    return fi, totals
