"""Dataset quality report (statistical sanity check of the generated data).

Everything is derived from the CSV tables, i.e. from what an analyst would see,
including stockouts and expiries, which are reconstructed from purchases,
sales and batch expiry dates. The report is evaluation-only: it never feeds
anything back into the dataset.
"""
from collections import Counter
from itertools import combinations

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
def reconstruct_stock(t, dates):
    """Return (end-of-day sellable stock [dates x (branch, medicine)], write-off df per branch+batch)."""
    pur, sal, bat = t["purchases"].copy(), t["sales"].copy(), t["batches"]
    pur["d"] = pd.to_datetime(pur["purchase_date"])
    sal["d"] = pd.to_datetime(sal["transaction_date"])
    sold = sal.groupby(["branch_id", "batch_id"])["quantity"].sum().rename("sold")
    pb = (pur.groupby(["branch_id", "batch_id", "medicine_id"])["quantity"].sum().rename("bought")
             .reset_index().merge(bat[["batch_id", "expiry_date"]], on="batch_id")
             .merge(sold.reset_index(), on=["branch_id", "batch_id"], how="left").fillna({"sold": 0}))
    pb["expiry"] = pd.to_datetime(pb["expiry_date"])
    pb["remaining"] = pb["bought"] - pb["sold"]
    wo = pb[(pb["expiry"] <= dates[-1]) & (pb["remaining"] > 0)].copy()      # expired stock written off
    deltas = pd.concat([
        pur[["d", "branch_id", "medicine_id"]].assign(delta=pur["quantity"]),
        sal[["d", "branch_id", "medicine_id"]].assign(delta=-sal["quantity"]),
        wo.rename(columns={"expiry": "d"})[["d", "branch_id", "medicine_id"]].assign(delta=-wo["remaining"]),
    ])
    daily = (deltas.groupby(["d", "branch_id", "medicine_id"])["delta"].sum()
                   .unstack(["branch_id", "medicine_id"]).reindex(dates).fillna(0).cumsum())
    return daily, pb, wo


def _runs(zero_mask: pd.DataFrame) -> int:
    prev = zero_mask.shift(1, fill_value=False)
    return int((zero_mask & ~prev).to_numpy().sum())


def association_pairs(sales, med_names, planted, top=10):
    baskets = sales.groupby("transaction_id")["medicine_id"].agg(lambda s: sorted(set(s)))
    n = len(baskets)
    single, pair = Counter(), Counter()
    for items in baskets:
        single.update(items)
        pair.update(combinations(items, 2))
    min_count = max(60, int(0.0008 * n))
    rows = []
    planted_set = {(r["antecedent_id"], r["consequent_id"]) for r in planted}
    for (a, b), c in pair.items():
        if c < min_count:
            continue
        sup = c / n
        lift = sup / ((single[a] / n) * (single[b] / n))
        for x, y in ((a, b), (b, a)):
            rows.append({"antecedent": med_names[x], "consequent": med_names[y], "support": round(sup, 4),
                         "confidence": round(c / single[x], 4), "lift": round(lift, 2),
                         "direction": f"{med_names[x]} -> {med_names[y]}",
                         "planted_rule": (x, y) in planted_set,
                         "reverse_of_planted_rule": (y, x) in planted_set and (x, y) not in planted_set})
    rows.sort(key=lambda r: -r["lift"])
    planted_rows = []
    for r in planted:
        a, b = r["antecedent_id"], r["consequent_id"]
        c = pair.get(tuple(sorted((a, b))), 0)
        ca = single[a]
        p_b_no_a = (single[b] - c) / max(n - ca, 1)
        planted_rows.append({
            "rule": f"{med_names[a]} -> {med_names[b]}", "support": round(c / n, 4),
            "P(B|A)": round(c / ca, 4) if ca else None, "P(B|not A)": round(p_b_no_a, 4),
            "lift": round((c / n) / ((ca / n) * (single[b] / n)), 2) if ca and single[b] else None})
    return rows[:top * 2], planted_rows


def anomaly_visibility(t, anomalies, dates, stock):
    """How visible each ground-truth anomaly is in the CSV data (evaluation only)."""
    sal = t["sales"]
    daily = (sal.assign(d=pd.to_datetime(sal["transaction_date"]))
                .groupby(["d", "medicine_id", "branch_id"])["quantity"].sum()
                .unstack(["medicine_id", "branch_id"]).reindex(dates).fillna(0))
    demand_windows = {}
    for a in anomalies:
        if a["type"] in ("spike", "drop", "branch_surge"):
            demand_windows.setdefault(a["medicine_id"], []).append(
                (pd.Timestamp(a["start_date"]), pd.Timestamp(a["end_date"])))
    out = {}
    pur = t["purchases"]
    for a in anomalies:
        typ, med = a["type"], a["medicine_id"]
        s, e = pd.Timestamp(a["start_date"]), pd.Timestamp(a["end_date"])
        if typ in ("spike", "drop", "branch_surge"):
            cols = [c for c in daily.columns if c[0] == med and (a["branch_id"] == "ALL" or c[1] == a["branch_id"])]
            ser = daily[cols].sum(axis=1)
            in_any = pd.Series(False, index=dates)
            for ws, we in demand_windows[med]:
                in_any |= (dates >= ws) & (dates <= we)
            win = (dates >= s) & (dates <= e)
            local = (dates >= s - pd.Timedelta(days=45)) & (dates <= e + pd.Timedelta(days=45))
            base = ser[~in_any & local]      # local baseline: robust to trend / seasonality
            if len(base) < 14 or base.mean() == 0:  # not enough clean history
                out[a["anomaly_id"]] = {"observed_ratio": None}
                continue
            z = (ser[win].mean() - base.mean()) / (base.std() / np.sqrt(win.sum()) + 1e-9)
            out[a["anomaly_id"]] = {"observed_ratio": round(float(ser[win].mean() / base.mean()), 2),
                                    "z_score": round(float(z), 1)}
        elif typ == "bulk_purchase":
            lots = pur[pur["medicine_id"] == med].groupby("batch_id")["quantity"].sum()
            mine = pur[pur["purchase_id"].isin(a["purchase_ids"])]["quantity"].sum()
            out[a["anomaly_id"]] = {"lot_quantity": int(mine),
                                    "ratio_vs_median_lot": round(float(mine / lots.median()), 2) if len(lots) else None}
        else:  # supply_disruption: delayed deliveries -> unusually long gap between purchases (+ stockouts)
            days = sorted(pd.to_datetime(pur.loc[pur["medicine_id"] == med, "purchase_date"].unique()))
            gaps = [((b - a).days, a, b) for a, b in zip(days, days[1:])]
            tail = e + pd.Timedelta(days=int(a["extra_lead_days"]) + 7)
            hit = [g for g in gaps if g[1] <= tail and g[2] >= s]
            cols = [c for c in stock.columns if c[1] == med]
            out[a["anomaly_id"]] = {
                "max_purchase_gap_days_in_window": max((g[0] for g in hit), default=None),
                "median_purchase_gap_days": float(np.median([g[0] for g in gaps])) if gaps else None,
                "stockout_days_in_window": int((stock.loc[(stock.index >= s) & (stock.index <= tail), cols] == 0).to_numpy().sum())}
    return out


# ---------------------------------------------------------------------------
def build_quality_report(t, start, end, planted_rules=(), rule_config=()):
    dates = pd.date_range(start, end, freq="D")
    med, bat, pur, sal = t["medicines"], t["batches"], t["purchases"], t["sales"]
    names = med.set_index("medicine_id")["medicine_name"].to_dict()
    med_cat = med.set_index("medicine_id")["category_id"].to_dict()
    cats = t["categories"].set_index("category_id")["category_name"].to_dict()
    sal = sal.assign(d=pd.to_datetime(sal["transaction_date"]))
    n_days = len(dates)
    R = {}

    R["basic"] = {
        "medicines": len(med), "branches": len(t["branches"]), "suppliers": len(t["suppliers"]),
        "categories": len(t["categories"]), "batches": len(bat), "purchases": len(pur),
        "sales_lines": len(sal), "transactions": int(sal["transaction_id"].nunique()),
        "date_range": [str(dates[0].date()), str(dates[-1].date())],
        "sales_date_range": [str(sal["d"].min().date()), str(sal["d"].max().date())],
        "days": n_days,
    }

    # ---- sales -----------------------------------------------------------
    txn_val = sal.groupby("transaction_id")["total_amount"].sum()
    per_med = sal.groupby("medicine_id")["quantity"].sum().reindex(med["medicine_id"]).fillna(0).astype(int)
    ranked = per_med.sort_values(ascending=False)
    ym = sal["d"].dt.strftime("%Y-%m")
    R["sales"] = {
        "total_quantity": int(sal["quantity"].sum()), "total_revenue": round(float(sal["total_amount"].sum()), 2),
        "avg_daily_units": round(float(sal["quantity"].sum() / n_days), 1),
        "avg_daily_revenue": round(float(sal["total_amount"].sum() / n_days), 2),
        "avg_lines_per_transaction": round(len(sal) / R["basic"]["transactions"], 3),
        "avg_transaction_value": round(float(txn_val.mean()), 2), "median_transaction_value": round(float(txn_val.median()), 2),
        "sales_lines_per_month": {k: int(v) for k, v in ym.value_counts().sort_index().items()},
        "transactions_per_month": {k: int(v) for k, v in sal.groupby(ym)["transaction_id"].nunique().items()},
        "top5_medicines": [(names[i], int(q)) for i, q in ranked.head(5).items()],
        "bottom5_medicines": [(names[i], int(q)) for i, q in ranked.tail(5)[::-1].items()],
    }

    # ---- stock reconstruction (shared by inventory sections) -------------
    stock, pb, wo = reconstruct_stock(t, dates)
    sold_daily = (sal.groupby(["d", "branch_id", "medicine_id"])["quantity"].sum()
                     .unstack(["branch_id", "medicine_id"]).reindex(dates).fillna(0)).reindex(columns=stock.columns, fill_value=0)
    zero = stock <= 0
    rate = sold_daily.rolling(30, min_periods=7).mean().shift(1)
    low = (stock > 0) & (stock < 3 * rate)
    col_branch = pd.Series([c[0] for c in stock.columns], index=stock.columns)
    col_med = pd.Series([c[1] for c in stock.columns], index=stock.columns)
    col_cat = col_med.map(med_cat)
    events_col = (zero & ~zero.shift(1, fill_value=False)).sum(axis=0)
    days_col = zero.sum(axis=0)
    ev_med, dy_med = events_col.groupby(col_med).sum(), days_col.groupby(col_med).sum()
    top_so = dy_med.sort_values(ascending=False).head(10)

    # ---- expiry --------------------------------------------------------------
    price = bat.set_index("batch_id")["purchase_price"]
    wo = wo.assign(value=wo["remaining"] * wo["batch_id"].map(price), category=wo["medicine_id"].map(med_cat))
    end_stock = stock.iloc[-1]
    vel = sold_daily.tail(90).mean()
    live = pb[(pb["expiry"] > dates[-1]) & (pb["remaining"] > 0)].copy()
    live["days_left"] = (live["expiry"] - dates[-1]).dt.days
    live["vel"] = [vel.get((b, m), 0.0) for b, m in zip(live["branch_id"], live["medicine_id"])]
    live["value"] = live["remaining"] * live["batch_id"].map(price)
    live["category"] = live["medicine_id"].map(med_cat)
    near = live[live["days_left"] <= 90]
    risky = live[(live["days_left"] <= 180) & (live["remaining"] > live["vel"] * live["days_left"])]
    pur_value = float((pur["quantity"] * pur["unit_purchase_price"]).sum())

    def by(df, col, valcols):
        g = df.groupby(col)[valcols].sum()
        return {str(k): {c: (round(float(v), 2) if c == "value" else int(v)) for c, v in row.items()} for k, row in g.iterrows()}

    R["inventory"] = {
        "total_remaining_stock": int(end_stock.sum()),
        "stockout_events": int(events_col.sum()), "stockout_branch_medicine_days": int(zero.to_numpy().sum()),
        "stockout_day_pct": round(100 * float(zero.to_numpy().mean()), 2),
        "low_stock_day_pct": round(100 * float(low.to_numpy().mean()), 2),
        "medicines_with_stockout": int((ev_med > 0).sum()),
        "medicines_with_10plus_stockout_days": int((dy_med >= 10).sum()),
        "branches_with_stockout": int((events_col.groupby(col_branch).sum() > 0).sum()),
        "stockouts_by_branch": {b: {"events": int(events_col[col_branch == b].sum()), "days": int(days_col[col_branch == b].sum()),
                                    "pct_of_medicine_days": round(100 * float(zero.loc[:, col_branch == b].to_numpy().mean()), 2),
                                    "avg_units_on_hand_per_medicine": round(float(stock.loc[:, col_branch == b].to_numpy().mean()), 1)}
                                for b in sorted(col_branch.unique())},
        "stockouts_by_category": {cats[c]: {"events": int(events_col[col_cat == c].sum()), "days": int(days_col[col_cat == c].sum()),
                                            "pct_of_branch_medicine_days": round(100 * float(zero.loc[:, col_cat == c].to_numpy().mean()), 2)}
                                  for c in sorted(col_cat.unique())},
        "top_stockout_medicines": [(names[m], int(d), int(ev_med[m])) for m, d in top_so.items()],
        "expired_batches": int(wo["batch_id"].nunique()), "expired_branch_lots": len(wo),
        "expired_quantity": int(wo["remaining"].sum()), "expired_value": round(float(wo["value"].sum()), 2),
        "expired_pct_of_purchased_units": round(100 * float(wo["remaining"].sum() / pur["quantity"].sum()), 2),
        "expired_pct_of_purchase_value": round(100 * float(wo["value"].sum() / pur_value), 2),
        "medicines_with_expiry": int(wo["medicine_id"].nunique()),
        "expired_by_category": {cats[k]: v for k, v in by(wo, "category", ["remaining", "value"]).items()},
        "expired_by_branch": by(wo, "branch_id", ["remaining", "value"]),
        "expired_by_medicine_top5": [(names[i], int(q)) for i, q in
                                     wo.groupby("medicine_id")["remaining"].sum().sort_values(ascending=False).head(5).items()],
        "near_expiry_at_end_90d": {"batches": int(near["batch_id"].nunique()), "units": int(near["remaining"].sum()),
                                   "value": round(float(near["value"].sum()), 2)},
        "expiry_risk_at_end": {"batches": int(risky["batch_id"].nunique()), "units": int(risky["remaining"].sum()),
                               "value": round(float(risky["value"].sum()), 2),
                               "by_category": {cats[k]: v for k, v in by(risky, "category", ["remaining", "value"]).items()},
                               "by_branch": by(risky, "branch_id", ["remaining", "value"]),
                               "top5_batches_by_value": [(r.batch_id, names[r.medicine_id], r.branch_id, int(r.remaining), round(float(r.value), 2), int(r.days_left))
                                                         for r in risky.sort_values("value", ascending=False).head(5).itertuples()]},
        "inventory_equation": {
            "opening": 0, "purchases": int(pur["quantity"].sum()), "sales": int(sal["quantity"].sum()),
            "expired_writeoff": int(wo["remaining"].sum()), "closing": int(end_stock.sum())},
    }

    # ---- demand ---------------------------------------------------------------
    D = (sal.groupby(["d", "medicine_id"])["quantity"].sum().unstack("medicine_id")
            .reindex(index=dates, columns=med["medicine_id"]).fillna(0))
    mean_by_med = D.mean()
    srt = np.sort(per_med.to_numpy())[::-1]
    cum = np.cumsum(srt) / srt.sum()
    rev = sal.groupby("medicine_id")["total_amount"].sum().sort_values(ascending=False)
    rcum = rev.cumsum() / rev.sum()
    asc = np.sort(per_med.to_numpy())
    n = len(asc)
    gini = float((2 * np.arange(1, n + 1) - n - 1).dot(asc) / (n * asc.sum()))
    prof = med.set_index("medicine_id")["demand_profile"]
    prof_stats = {}
    for p_name in ("HIGH", "MEDIUM", "LOW"):
        ids = prof[prof == p_name].index
        q = per_med.reindex(ids)
        prof_stats[p_name] = {"medicines": int(len(ids)), "share_of_units_pct": round(100 * float(q.sum() / per_med.sum()), 1),
                              "mean_units_per_day": round(float(q.mean() / n_days), 2),
                              "min_units_per_day": round(float(q.min() / n_days), 3), "max_units_per_day": round(float(q.max() / n_days), 2)}
    R["demand"] = {
        "mean_daily_demand_units_per_medicine": round(float(D.to_numpy().mean()), 2),
        "std_daily_demand_units": round(float(D.to_numpy().std()), 2),
        "highest_demand_medicine": (names[mean_by_med.idxmax()], round(float(mean_by_med.max()), 2)),
        "lowest_demand_medicine": (names[mean_by_med.idxmin()], round(float(mean_by_med.min()), 3)),
        "units_per_medicine_quantiles": {f"p{q}": int(np.percentile(per_med, q)) for q in (10, 25, 50, 75, 90, 99)},
        "top10pct_medicines_share_of_units": round(float(cum[max(1, round(0.1 * n)) - 1]), 3),
        "top20pct_medicines_share_of_units": round(float(cum[max(1, round(0.2 * n)) - 1]), 3),
        "bottom50pct_medicines_share_of_units": round(float(np.sort(per_med.to_numpy())[: n // 2].sum() / per_med.sum()), 3),
        "gini_of_units": round(gini, 3),
        "max_to_min_volume_ratio": round(float(srt[0] / max(srt[-1], 1)), 1),
        "abc_by_revenue": {"A(<=70%)": int((rcum <= 0.70).sum() + 1), "B(<=90%)": int(((rcum > 0.70) & (rcum <= 0.90)).sum()),
                           "C(>90%)": int((rcum > 0.90).sum())},
        "by_demand_profile": prof_stats,
    }

    # ---- categories + seasonality (month-of-year, pooled over the years) -------
    sm = sal.merge(med[["medicine_id", "category_id"]], on="medicine_id")
    sm["month"] = sm["d"].dt.month
    m_units = sm.groupby(["category_id", "month"])["quantity"].sum().unstack("month").fillna(0)
    days = pd.Series({m: int((dates.month == m).sum()) for m in m_units.columns})
    idx = (m_units / days).div((m_units / days).mean(axis=1), axis=0)
    cq = sm.groupby("category_id")["quantity"].sum()
    cr = sm.groupby("category_id")["total_amount"].sum()
    n_cat_med = med.groupby("category_id").size()
    R["categories"] = {cats[c]: {
        "medicines": int(n_cat_med[c]), "sales_quantity": int(cq[c]), "revenue": round(float(cr[c]), 2),
        "avg_daily_units": round(float(cq[c] / n_days), 1), "avg_daily_units_per_medicine": round(float(cq[c] / n_days / n_cat_med[c]), 2),
        "seasonality_index_jan_to_dec": [round(float(x), 2) for x in idx.loc[c]],
        "seasonality_amplitude": round(float((idx.loc[c].max() - idx.loc[c].min()) / 2), 3),
        "peak_month": int(idx.loc[c].idxmax())} for c in idx.index}
    R["seasonality_index_by_category"] = {k: v["seasonality_index_jan_to_dec"] for k, v in R["categories"].items()}

    # ---- branches ----------------------------------------------------------------
    g = sal.groupby("branch_id")
    active = sal.groupby("branch_id")["medicine_id"].nunique()
    R["branches"] = {"revenue": {k: round(float(v), 2) for k, v in g["total_amount"].sum().items()},
                     "quantity": {k: int(v) for k, v in g["quantity"].sum().items()},
                     "active_medicines": {k: int(v) for k, v in active.items()},
                     "transactions": {k: int(v) for k, v in g["transaction_id"].nunique().items()}}
    bc = (sal.merge(med[["medicine_id", "category_id"]], on="medicine_id")
             .groupby(["category_id", "branch_id"])["quantity"].sum().unstack("branch_id"))
    bc_share = bc.div(bc.sum(axis=0), axis=1)
    R["branches"]["category_share_index_vs_all_branches"] = {
        b: {cats[c]: round(float(bc_share.loc[c, b] / bc_share.loc[c].mean()), 2) for c in bc.index} for b in bc.columns}

    # ---- associations ----------------------------------------------------------------
    top_pairs, planted_rows = association_pairs(sal, names, list(planted_rules), top=15)
    R["associations"] = {
        "configured_rules": [{"rule": f"{names[r['antecedent_id']]} -> {names[r['consequent_id']]}",
                              "antecedent_id": r["antecedent_id"], "consequent_id": r["consequent_id"],
                              "added_probability": r["added_probability"]} for r in rule_config],
        "note": "Mined pairs are listed in both directions: A->B and B->A share support and lift but differ in confidence. "
                "A reverse row is not a generation error; it is flagged reverse_of_planted_rule.",
        "mined_strongest_pairs": top_pairs[:20],
        "planted_rule_check": planted_rows,
    }
    R["_stock"] = stock   # not serialised
    return R


def format_report(R, indent="  "):
    b, s, i, d, br = R["basic"], R["sales"], R["inventory"], R["demand"], R["branches"]
    L = ["DATASET QUALITY REPORT", "-" * 60,
         f"Basic: {b['medicines']} medicines, {b['branches']} branches, {b['suppliers']} suppliers, {b['batches']} batches, "
         f"{b['purchases']} purchases, {b['sales_lines']} sales lines, {b['transactions']} transactions, {b['date_range'][0]}..{b['date_range'][1]}",
         f"Sales: qty {s['total_quantity']}, revenue Rs {s['total_revenue']:,.2f}, avg daily units {s['avg_daily_units']}, "
         f"avg txn Rs {s['avg_transaction_value']}, median txn Rs {s['median_transaction_value']}",
         f"{indent}top5 : {s['top5_medicines']}", f"{indent}low5 : {s['bottom5_medicines']}",
         f"Inventory: remaining {i['total_remaining_stock']}, stockout events {i['stockout_events']} "
         f"({i['stockout_branch_medicine_days']} branch-medicine-days = {i['stockout_day_pct']}%), low-stock days {i['low_stock_day_pct']}%, "
         f"{i['medicines_with_stockout']} medicines affected",
         f"{indent}expired: {i['expired_batches']} batches, {i['expired_quantity']} units ({i['expired_pct_of_purchased_units']}% of purchased), "
         f"value Rs {i['expired_value']:,.2f}; near-expiry at end {i['near_expiry_at_end_90d']}; expiry-risk at end {i['expiry_risk_at_end']['batches']} batches "
         f"(Rs {i['expiry_risk_at_end']['value']:,.2f})",
         f"{indent}equation: {i['inventory_equation']}",
         f"Demand: mean {d['mean_daily_demand_units_per_medicine']} units/medicine/day, std {d['std_daily_demand_units']}, "
         f"highest {d['highest_demand_medicine']}, lowest {d['lowest_demand_medicine']}",
         f"{indent}top-10% medicines = {d['top10pct_medicines_share_of_units']:.0%}, top-20% = {d['top20pct_medicines_share_of_units']:.0%}, "
         f"bottom-50% = {d['bottom50pct_medicines_share_of_units']:.0%} of units; Gini {d['gini_of_units']}; ABC {d['abc_by_revenue']}",
         f"{indent}by profile: {d['by_demand_profile']}",
         f"Branches: revenue {br['revenue']}", f"{indent}qty {br['quantity']}, active medicines {br['active_medicines']}",
         f"{indent}stockout days by branch: { {k: v['days'] for k, v in i['stockouts_by_branch'].items()} }"]
    L.append("Categories (qty / revenue / seasonality amplitude / peak month):")
    for k, v in R["categories"].items():
        L.append(f"{indent}{k:<17}{v['sales_quantity']:>9}{v['revenue']:>15,.0f}  amp {v['seasonality_amplitude']:.2f}  peak m{v['peak_month']}  {v['seasonality_index_jan_to_dec']}")
    L.append("Strongest observed pairs (support / confidence / lift):")
    for r in R["associations"]["mined_strongest_pairs"][:10]:
        tag = "  [planted]" if r["planted_rule"] else ("  [reverse of planted]" if r["reverse_of_planted_rule"] else "")
        L.append(f"{indent}{r['direction']}: {r['support']} / {r['confidence']} / {r['lift']}{tag}")
    L.append("Planted rules, observed:")
    for r in R["associations"]["planted_rule_check"]:
        L.append(f"{indent}{r['rule']}: support {r['support']}, P(B|A) {r['P(B|A)']}, P(B|not A) {r['P(B|not A)']}, lift {r['lift']}")
    if "anomalies" in R:
        a = R["anomalies"]
        L.append(f"Anomalies: {a['total']} {a['by_type']}; {a['distinct_medicines']} medicines; "
                 f"visible demand events {a['visible_demand_events']}/{a['demand_events']}")
    return "\n".join(L)
