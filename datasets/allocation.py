"""Allocate sales to stock lots (FEFO) so inventory can be reconstructed from sales + purchases.

A sales file does not say which batch each sale came from. For every branch x medicine the sales are replayed in date order and each
line is filled from the received lots that have not expired, earliest expiry first (first-expiry-first-out, ties by receipt date).

Stock the files do not explain (sales that exceed everything received so far) is covered by an IMPLIED OPENING stock: a lot named
OPENING-<medicine> that never expires, received on the first day. Its size is the smallest quantity that keeps every pair's stock
non-negative. It is an estimate and is reported to the user, never hidden.
"""
import heapq

import numpy as np
import pandas as pd

OPENING_PREFIX = "OPENING-"
NO_EXPIRY = "2099-12-31"


def allocate_fefo(sales: pd.DataFrame, purchases: pd.DataFrame, batches: pd.DataFrame, calendar_start: str):
    """Return (sales_allocated, opening_purchases, opening_batches, stats)."""
    exp_of = batches.set_index("batch_id")["expiry_date"].to_dict()
    recv = {}
    for pid, b, bt, d, q in zip(purchases["branch_id"], purchases["medicine_id"], purchases["batch_id"], purchases["purchase_date"], purchases["quantity"]):
        recv.setdefault((pid, b), []).append((d, exp_of[bt], bt, int(q)))
    for v in recv.values():
        v.sort()

    out_rows = []                                   # (sale index, batch_id, part quantity)
    opening_need = {}
    sales = sales.reset_index(drop=True)
    order = sales.sort_values(["branch_id", "medicine_id", "transaction_date"], kind="stable").index.to_numpy()
    s_branch, s_med = sales["branch_id"].to_numpy(), sales["medicine_id"].to_numpy()
    s_date, s_qty = sales["transaction_date"].to_numpy(), sales["quantity"].to_numpy()

    cur_pair, receipts, ptr, lots = None, [], 0, []        # lots: heap of [expiry, receipt_date, batch_id, remaining]
    shortfall_units = 0
    for i in order:
        pair = (s_branch[i], s_med[i])
        if pair != cur_pair:
            cur_pair, receipts, ptr, lots = pair, recv.get(pair, []), 0, []
        d = s_date[i]
        while ptr < len(receipts) and receipts[ptr][0] <= d:            # receipts on or before the sale date are available
            rd, ex, bt, q = receipts[ptr]
            heapq.heappush(lots, [ex, rd, bt, q])
            ptr += 1
        need = int(s_qty[i])
        skipped = []
        while need > 0 and lots:
            top = lots[0]
            if top[0] <= d:                                             # expired lots cannot be sold; they stay out of the heap for later sales too
                heapq.heappop(lots)
                continue
            take = min(need, top[3])
            out_rows.append((i, top[2], take))
            top[3] -= take
            need -= take
            if top[3] == 0:
                heapq.heappop(lots)
        if need > 0:
            out_rows.append((i, OPENING_PREFIX + s_med[i], need))
            opening_need[pair] = opening_need.get(pair, 0) + need
            shortfall_units += need

    parts = pd.DataFrame(out_rows, columns=["i", "batch_id", "q"])
    base = sales.loc[parts["i"]].reset_index(drop=True)
    q_orig = base["quantity"].to_numpy()
    price_c = np.rint(base["unit_selling_price"].astype(float).to_numpy() * 100).astype("int64")
    disc_c = np.rint(base["discount"].astype(float).to_numpy() * 100).astype("int64")
    q_part = parts["q"].to_numpy()
    # split the line discount across its parts (largest share of the line gets the rounding remainder), keeping every part valid
    disc_part = (disc_c * q_part) // q_orig
    parts["_i"] = parts["i"].to_numpy()
    rem = disc_c - pd.Series(disc_part).groupby(parts["_i"].to_numpy()).transform("sum").to_numpy()
    first_of_line = ~parts["_i"].duplicated(keep="first").to_numpy()
    disc_part = disc_part + np.where(first_of_line, rem, 0)
    gross_part = q_part * price_c
    disc_part = np.minimum(disc_part, gross_part)
    total_part = gross_part - disc_part
    money = lambda c: pd.Series(c / 100.0).map("{:.2f}".format)
    allocated = pd.DataFrame({
        "transaction_id": base["transaction_id"], "transaction_date": base["transaction_date"], "branch_id": base["branch_id"],
        "medicine_id": base["medicine_id"], "batch_id": parts["batch_id"], "quantity": q_part.astype("int64"),
        "unit_selling_price": base["unit_selling_price"], "discount": money(disc_part), "total_amount": money(total_part)})
    allocated = allocated.sort_values(["transaction_date", "transaction_id", "medicine_id", "batch_id"], kind="stable").reset_index(drop=True)

    # implied opening stock: purchase lines on the first day + one batch per medicine
    avg_cost = _estimate_costs(sales, purchases)
    op_rows = [(b, m, q) for (b, m), q in sorted(opening_need.items())]
    total_units = int(sales["quantity"].sum())
    stats = {"opening_units_estimated": int(shortfall_units), "pairs_with_opening_stock": len(op_rows),
             "share_of_sales_from_opening_stock": round(shortfall_units / total_units, 4) if total_units else 0.0,
             "sales_lines": int(len(sales)), "sales_rows_after_allocation": int(len(allocated))}
    if not op_rows:
        cols_p = ["purchase_id", "purchase_date", "branch_id", "supplier_id", "medicine_id", "batch_id", "quantity", "unit_purchase_price", "total_cost"]
        cols_b = ["batch_id", "medicine_id", "supplier_id", "manufacture_date", "expiry_date", "initial_quantity", "purchase_price"]
        return allocated, pd.DataFrame(columns=cols_p), pd.DataFrame(columns=cols_b), stats
    opening_purchases = pd.DataFrame({
        "purchase_id": [f"OPEN{i:07d}" for i in range(1, len(op_rows) + 1)], "purchase_date": calendar_start,
        "branch_id": [r[0] for r in op_rows], "supplier_id": "SUP_UNKNOWN", "medicine_id": [r[1] for r in op_rows],
        "batch_id": [OPENING_PREFIX + r[1] for r in op_rows], "quantity": [r[2] for r in op_rows]})
    unit = opening_purchases["medicine_id"].map(avg_cost)
    opening_purchases["unit_purchase_price"] = unit.map("{:.2f}".format)
    opening_purchases["total_cost"] = (opening_purchases["quantity"] * unit.round(2)).round(2).map("{:.2f}".format)
    ob = opening_purchases.groupby("medicine_id").agg(initial_quantity=("quantity", "sum"), purchase_price=("unit_purchase_price", "first")).reset_index()
    opening_batches = pd.DataFrame({
        "batch_id": OPENING_PREFIX + ob["medicine_id"], "medicine_id": ob["medicine_id"], "supplier_id": "SUP_UNKNOWN",
        "manufacture_date": calendar_start, "expiry_date": NO_EXPIRY,
        "initial_quantity": ob["initial_quantity"].astype("int64"), "purchase_price": ob["purchase_price"]})
    return allocated, opening_purchases, opening_batches, stats


def _estimate_costs(sales: pd.DataFrame, purchases: pd.DataFrame) -> pd.Series:
    """Unit cost for implied opening stock: the medicine's own average purchase cost; if it was never purchased, its selling price times the
    median cost/price ratio observed on other medicines (1.0 when nothing can be observed)."""
    sell = sales.assign(_v=sales["quantity"] * sales["unit_selling_price"].astype(float)).groupby("medicine_id").agg(v=("_v", "sum"), q=("quantity", "sum"))
    sell_avg = sell["v"] / sell["q"]
    pur = purchases.assign(_v=purchases["quantity"] * purchases["unit_purchase_price"].astype(float)).groupby("medicine_id").agg(v=("_v", "sum"), q=("quantity", "sum"))
    cost_avg = pur["v"] / pur["q"]
    both = cost_avg.index.intersection(sell_avg.index)
    ratio = float((cost_avg[both] / sell_avg[both]).median()) if len(both) else 1.0
    if not np.isfinite(ratio) or ratio <= 0:
        ratio = 1.0
    out = (sell_avg * ratio).clip(lower=0.01)
    out.update(cost_avg)
    return out.clip(lower=0.01).round(2)
