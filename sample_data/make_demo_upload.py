"""Build the sample files for the "Upload Data" demo.

    python sample_data/make_demo_upload.py          small sample  -> sample_data/sales_demo.csv, purchases_demo.csv
    python sample_data/make_demo_upload.py --full   FULL dataset  -> sample_data/full/sales_full.csv, purchases_full.csv
        (all 5 branches, all 500 medicines, the whole 2025-2026 period: every page is as rich as for the built-in demo dataset)

Takes a slice of the synthetic MedStock source data (3 branches, 150 medicines, 1 Jun 2025 - 30 Apr 2026) and writes it the way a
pharmacy's own systems might export it: POS-style column names, one row per bill line, and a stock-receipt (GRN) register with batch
numbers and expiry dates. The column names deliberately differ from MedStock's so the column-mapping step has something to show.
"""
from pathlib import Path

import sys

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = Path(__file__).resolve().parent
FULL = "--full" in sys.argv
BRANCHES = ["BR001", "BR002", "BR003", "BR004", "BR005"] if FULL else ["BR001", "BR002", "BR003"]
START, END = ("2025-01-01", "2026-12-31") if FULL else ("2025-06-01", "2026-04-30")
N_MEDICINES = 500 if FULL else 150
SUFFIX = "full" if FULL else "demo"
if FULL:
    OUT = OUT / "full"
    OUT.mkdir(exist_ok=True)
SEED = 7


def main():
    med = pd.read_csv(RAW / "medicines.csv")
    cat = pd.read_csv(RAW / "categories.csv")
    sup = pd.read_csv(RAW / "suppliers.csv")[["supplier_id", "supplier_name"]]
    med = med.merge(cat, on="category_id")
    curated = med[med["medicine_id"] <= "MED040"]                      # the curated catalogue (contains the planted co-purchase pairs)
    rest = med[med["medicine_id"] > "MED040"].sample(N_MEDICINES - len(curated), random_state=SEED) if not FULL else med[med["medicine_id"] > "MED040"]
    chosen = pd.concat([curated, rest])
    ids = set(chosen["medicine_id"])

    sales = pd.read_csv(RAW / "sales.csv")
    sales = sales[sales["branch_id"].isin(BRANCHES) & sales["medicine_id"].isin(ids) & sales["transaction_date"].between(START, END)]
    sales["gross"] = sales["quantity"] * sales["unit_selling_price"]
    bill = sales.groupby(["transaction_id", "transaction_date", "branch_id", "medicine_id"], as_index=False).agg(
        qty=("quantity", "sum"), gross=("gross", "sum"), disc=("discount", "sum"))
    bill["mrp"] = (bill["gross"] / bill["qty"]).round(2)
    bill = bill.merge(chosen[["medicine_id", "medicine_name", "category_name"]], on="medicine_id").sort_values(["transaction_date", "transaction_id", "medicine_id"])
    bill["transaction_id"] = bill["transaction_id"].str.replace("TXN", "INV-", regex=False)
    sales_out = pd.DataFrame({
        "Bill No": bill["transaction_id"], "Bill Date": bill["transaction_date"], "Store": bill["branch_id"], "Item Code": bill["medicine_id"],
        "Item Name": bill["medicine_name"], "Category": bill["category_name"], "Qty": bill["qty"], "MRP": bill["mrp"], "Discount": bill["disc"].round(2)})
    sales_out.to_csv(OUT / f"sales_{SUFFIX}.csv", index=False)

    # Stock register: opening balance on START (what each branch still held per batch: received - sold before START, not yet expired),
    # followed by every receipt from START on. This keeps the sample consistent with the sales slice.
    pur = pd.read_csv(RAW / "purchases.csv")
    bat = pd.read_csv(RAW / "batches.csv")[["batch_id", "expiry_date"]]
    allsales = pd.read_csv(RAW / "sales.csv")
    pur = pur[pur["branch_id"].isin(BRANCHES) & pur["medicine_id"].isin(ids)]
    before = pur[pur["purchase_date"] < START].groupby(["branch_id", "supplier_id", "medicine_id", "batch_id", "unit_purchase_price"], as_index=False)["quantity"].sum()
    sold_before = allsales[(allsales["transaction_date"] < START) & allsales["branch_id"].isin(BRANCHES)].groupby(["branch_id", "batch_id"], as_index=False)["quantity"].sum()         .rename(columns={"quantity": "sold"})
    opening = before.merge(sold_before, on=["branch_id", "batch_id"], how="left").fillna({"sold": 0})
    opening["quantity"] = (opening["quantity"] - opening["sold"]).astype(int)
    opening = opening[opening["quantity"] > 0].drop(columns="sold").assign(purchase_date=START)
    pur = pd.concat([opening, pur[(pur["purchase_date"] >= START) & (pur["purchase_date"] <= END)]], ignore_index=True)
    pur = pur.merge(bat, on="batch_id").merge(sup, on="supplier_id")
    pur = pur[pur["expiry_date"] > START]                                # lots that had already expired are irrelevant
    pur_out = pd.DataFrame({
        "GRN Date": pur["purchase_date"], "Store": pur["branch_id"], "Item Code": pur["medicine_id"], "Batch No": pur["batch_id"], "Expiry": pur["expiry_date"],
        "Supplier": pur["supplier_name"], "Qty Received": pur["quantity"], "Cost Price": pur["unit_purchase_price"]}).sort_values(["GRN Date", "Store", "Item Code"])
    pur_out.to_csv(OUT / f"purchases_{SUFFIX}.csv", index=False)

    print(f"sales_{SUFFIX}.csv     {len(sales_out):>8,} rows | {sales_out['Bill No'].nunique():,} bills | {sales_out['Item Code'].nunique()} medicines | "
          f"{sales_out['Bill Date'].min()} -> {sales_out['Bill Date'].max()} | revenue INR {(sales_out['Qty'] * sales_out['MRP'] - sales_out['Discount']).sum():,.0f}")
    print(f"purchases_{SUFFIX}.csv {len(pur_out):>8,} rows | {pur_out['Batch No'].nunique():,} batches | {pur_out['Qty Received'].sum():,} units")


if __name__ == "__main__":
    main()
