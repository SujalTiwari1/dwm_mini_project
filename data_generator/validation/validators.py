"""Independent validation of the generated tables.

Everything here works only from the DataFrames (as they would be read back
from CSV), never from generator internals, so it can catch generator bugs.
"""
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .. import config as C


@dataclass
class ValidationReport:
    results: list = field(default_factory=list)  # (check name, violating rows)

    def add(self, name, bad):
        self.results.append((name, int(bad)))

    @property
    def checks_run(self):
        return len(self.results)

    @property
    def failed(self):
        return [(n, b) for n, b in self.results if b > 0]

    @property
    def total_violations(self):
        return sum(b for _, b in self.results)


def _dates(s):
    return pd.to_datetime(s)


def validate(t, supplier_map=None, ledger_closing=None, start=None, end=None) -> ValidationReport:
    """t: dict of DataFrames keyed categories/medicines/branches/suppliers/batches/purchases/sales."""
    v = C.VALIDATION_CONFIG
    tol = v["money_tolerance"]
    r = ValidationReport()
    cat, med, br, sup = t["categories"], t["medicines"], t["branches"], t["suppliers"]
    bat, pur, sal = t["batches"], t["purchases"], t["sales"]

    # ---- keys -----------------------------------------------------------
    for name, df, key in [
        ("categories", cat, "category_id"), ("medicines", med, "medicine_id"),
        ("branches", br, "branch_id"), ("suppliers", sup, "supplier_id"),
        ("batches", bat, "batch_id"), ("purchases", pur, "purchase_id"),
    ]:
        r.add(f"{name}: primary key unique", df[key].duplicated().sum())
    r.add("sales: no duplicate (transaction, medicine, batch) lines",
          sal.duplicated(["transaction_id", "medicine_id", "batch_id"]).sum())
    r.add("no null values in any table", sum(int(df.isna().sum().sum()) for df in t.values()))

    # ---- referential integrity -----------------------------------------
    def fk(label, child, col, parent_ids):
        r.add(f"FK {label}", (~child[col].isin(parent_ids)).sum())

    fk("medicines.category_id -> categories", med, "category_id", cat["category_id"])
    fk("batches.medicine_id -> medicines", bat, "medicine_id", med["medicine_id"])
    fk("batches.supplier_id -> suppliers", bat, "supplier_id", sup["supplier_id"])
    for col, parent in [("branch_id", br["branch_id"]), ("supplier_id", sup["supplier_id"]),
                        ("medicine_id", med["medicine_id"]), ("batch_id", bat["batch_id"])]:
        fk(f"purchases.{col}", pur, col, parent)
    for col, parent in [("branch_id", br["branch_id"]), ("medicine_id", med["medicine_id"]),
                        ("batch_id", bat["batch_id"])]:
        fk(f"sales.{col}", sal, col, parent)

    # ---- positivity -----------------------------------------------------
    r.add("medicines.base_price > 0", (med["base_price"] <= 0).sum())
    r.add("medicines.demand_profile in HIGH/MEDIUM/LOW", (~med["demand_profile"].isin(list(C.DEMAND_PROFILES))).sum())
    r.add("batches.initial_quantity > 0", (bat["initial_quantity"] <= 0).sum())
    r.add("batches.purchase_price > 0", (bat["purchase_price"] <= 0).sum())
    r.add("purchases.quantity > 0", (pur["quantity"] <= 0).sum())
    r.add("purchases.unit_purchase_price > 0", (pur["unit_purchase_price"] <= 0).sum())
    r.add("sales.quantity > 0", (sal["quantity"] <= 0).sum())
    r.add("sales.unit_selling_price > 0", (sal["unit_selling_price"] <= 0).sum())
    r.add("sales.discount >= 0", (sal["discount"] < 0).sum())
    r.add("sales.total_amount > 0", (sal["total_amount"] <= 0).sum())

    # ---- arithmetic -------------------------------------------------------
    r.add("purchases.total_cost = quantity x unit_purchase_price",
          ((pur["quantity"] * pur["unit_purchase_price"] - pur["total_cost"]).abs() > tol).sum())
    r.add("sales.total_amount = quantity x unit_selling_price - discount",
          ((sal["quantity"] * sal["unit_selling_price"] - sal["discount"] - sal["total_amount"]).abs() > tol).sum())

    # ---- batch consistency ---------------------------------------------
    pb = pur.merge(bat, on="batch_id", suffixes=("", "_batch"), how="left")
    r.add("purchases.medicine_id matches batch", (pb["medicine_id"] != pb["medicine_id_batch"]).sum())
    r.add("purchases.supplier_id matches batch", (pb["supplier_id"] != pb["supplier_id_batch"]).sum())
    r.add("purchases.unit_purchase_price = batch.purchase_price",
          ((pb["unit_purchase_price"] - pb["purchase_price"]).abs() > tol).sum())
    sb = sal.merge(bat[["batch_id", "medicine_id", "expiry_date"]], on="batch_id", suffixes=("", "_batch"), how="left")
    r.add("sales.medicine_id matches batch", (sb["medicine_id"] != sb["medicine_id_batch"]).sum())
    per_batch = pur.groupby("batch_id").agg(qty=("quantity", "sum"), first=("purchase_date", "min"),
                                            last=("purchase_date", "max"))
    chk = bat.set_index("batch_id").join(per_batch)
    r.add("every batch has at least one purchase", chk["qty"].isna().sum())
    r.add("batch.initial_quantity = sum of its purchases", (chk["qty"] != chk["initial_quantity"]).sum())
    r.add("all purchases of a batch share one date", (chk["first"] != chk["last"]).sum())
    if supplier_map is not None:
        allowed = pur.apply(lambda row: row["supplier_id"] in supplier_map[row["medicine_id"]][0], axis=1)
        r.add("purchase supplier is an approved supplier of the medicine", (~allowed).sum())

    # ---- dates ----------------------------------------------------------
    manu, exp = _dates(chk["manufacture_date"]), _dates(chk["expiry_date"])
    first = _dates(chk["first"])
    r.add("manufacture_date < purchase_date", (~(manu < first)).sum())
    r.add("purchase_date < expiry_date", (~(first < exp)).sum())
    shelf = (exp - manu).dt.days
    r.add("shelf life between 6 and 36 months",
          ((shelf < v["min_shelf_life_days"]) | (shelf > v["max_shelf_life_days"])).sum())
    sdate = _dates(sal["transaction_date"])
    r.add("sales never after batch expiry (sale_date < expiry_date)", (~(sdate.values < _dates(sb["expiry_date"]).values)).sum())
    if start is not None:
        r.add("purchase/sale dates within configured period",
              (_dates(pur["purchase_date"]) < start).sum() + (_dates(pur["purchase_date"]) > end).sum()
              + (sdate < start).sum() + (sdate > end).sum())

    # ---- prices -----------------------------------------------------------
    r.add("unit_purchase_price < unit_selling_price on every sold batch",
          (sb.merge(bat[["batch_id", "purchase_price"]], on="batch_id")
             .eval("purchase_price >= unit_selling_price")).sum())
    pm = pur.merge(med[["medicine_id", "base_price"]], on="medicine_id")
    r.add("purchase price <= 90% of medicine base price", (pm["unit_purchase_price"] > 0.9 * pm["base_price"]).sum())

    # ---- transactions -----------------------------------------------------
    g = sal.groupby("transaction_id")
    r.add("each transaction has a single date", (g["transaction_date"].nunique() > 1).sum())
    r.add("each transaction has a single branch", (g["branch_id"].nunique() > 1).sum())

    # ---- inventory replay ---------------------------------------------
    ev = pd.concat([
        pd.DataFrame({"d": _dates(pur["purchase_date"]), "o": 0, "branch": pur["branch_id"],
                      "batch": pur["batch_id"], "delta": pur["quantity"]}),
        pd.DataFrame({"d": sdate, "o": 1, "branch": sal["branch_id"],
                      "batch": sal["batch_id"], "delta": -sal["quantity"]}),
    ]).sort_values(["branch", "batch", "d", "o"], kind="stable")
    ev["stock"] = ev.groupby(["branch", "batch"])["delta"].cumsum()
    r.add("inventory never negative (replay of purchases/sales per branch+batch)", (ev["stock"] < 0).sum())
    r.add("every sale draws from a batch received at that branch earlier or same day",
          (~sal.set_index(["branch_id", "batch_id"]).index.isin(
              pur.set_index(["branch_id", "batch_id"]).index)).sum())

    if ledger_closing is not None:
        replay = int(pur["quantity"].sum() - sal["quantity"].sum())
        r.add("reconciliation: purchases - sales = on hand + expired write-offs", abs(replay - ledger_closing))
    return r
