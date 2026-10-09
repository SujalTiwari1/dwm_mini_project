"""Validate and clean an uploaded purchases (stock receipts) file.

Required (after column mapping): purchase_date, medicine_id, quantity, unit_purchase_price.
Optional: batch_id, expiry_date (without it expiry analytics are unavailable), branch_id, supplier.
The file is aligned to the sales calendar: receipts before the first sale are treated as received on the first day (opening stock),
receipts after the last sale are ignored (inventory is only reconstructed up to the last sale date).
"""
import re

import numpy as np
import pandas as pd

from .sales_validation import (MAX_ID_LENGTH, UNKNOWN_BRANCH, ValidationError, _norm)

REQUIRED = ["purchase_date", "medicine_id", "quantity", "unit_purchase_price"]
OPTIONAL = ["batch_id", "expiry_date", "branch_id", "supplier"]
CANONICAL = REQUIRED + OPTIONAL
MAX_ROWS = 1_000_000
UNKNOWN_SUPPLIER = "SUP_UNKNOWN"
NO_EXPIRY = "2099-12-31"
MAX_DENSE_ROWS = 20_000_000       # inventory is a dense date x branch x medicine snapshot

SYNONYMS = {
    "purchase_date": ["purchase_date", "date", "received_date", "receipt_date", "grn_date", "invoice_date", "order_date", "stock_in_date"],
    "medicine_id": ["medicine_id", "product_id", "item_id", "sku", "drug_id", "item_code", "product_code", "medicine_code"],
    "quantity": ["quantity", "qty", "units", "received_qty", "quantity_received", "purchase_qty", "qty_in", "qty_received"],
    "unit_purchase_price": ["unit_purchase_price", "unit_cost", "cost", "purchase_price", "cost_price", "rate", "buy_price", "ptr"],
    "batch_id": ["batch_id", "batch", "batch_no", "batch_number", "lot", "lot_no"],
    "expiry_date": ["expiry_date", "expiry", "exp_date", "expiration_date", "expires", "best_before", "exp", "expiry_dt"],
    "branch_id": ["branch_id", "branch", "store_id", "store", "outlet", "location", "shop_id"],
    "supplier": ["supplier", "supplier_name", "vendor", "vendor_name", "supplier_id", "distributor"],
}


def suggest_mapping(headers: list[str]) -> dict:
    by_norm = {_norm(h): h for h in headers}
    used, out = set(), {}
    for canon in CANONICAL:
        for syn in SYNONYMS[canon]:
            h = by_norm.get(syn)
            if h is not None and h not in used:
                out[canon] = h
                used.add(h)
                break
    return out


def read_preview(path, nrows: int = 8) -> dict:
    try:
        df = pd.read_csv(path, nrows=nrows, dtype=str, keep_default_na=False)
    except Exception:
        raise ValidationError("The purchases file could not be read as a CSV. Upload a comma-separated .csv file with a header row.")
    headers = [str(c) for c in df.columns]
    return {"headers": headers, "suggested_mapping": suggest_mapping(headers), "sample_rows": df.head(nrows).to_dict("records"),
            "required": REQUIRED, "optional": OPTIONAL}


def clean_purchases(path, mapping: dict | None, sales: pd.DataFrame, n_medicines_in_sales: int, n_branches_in_sales: int):
    """Return (purchases, batches, suppliers, report). `purchases` includes `expiry_date` for the batch builder."""
    try:
        raw = pd.read_csv(path, dtype=str, keep_default_na=False, nrows=MAX_ROWS + 1)
    except Exception:
        raise ValidationError("The purchases file could not be read as a CSV. Upload a comma-separated .csv file with a header row.")
    if len(raw) > MAX_ROWS:
        raise ValidationError(f"The purchases file has more than {MAX_ROWS:,} rows.")
    raw.columns = [str(c).strip() for c in raw.columns]
    mapping = {k: v for k, v in (mapping or suggest_mapping(list(raw.columns))).items() if v}
    errors = []
    missing = [c for c in REQUIRED if c not in mapping]
    if missing:
        errors.append("Purchases file: missing required column(s): " + ", ".join(missing) + ". Map them to columns of the file.")
    bad = [f"{k} -> '{v}'" for k, v in mapping.items() if k not in CANONICAL or v not in raw.columns]
    if bad:
        errors.append("Purchases file: the mapping refers to columns that do not exist: " + ", ".join(bad))
    if len(set(mapping.values())) != len(mapping):
        errors.append("Purchases file: the same column is mapped to more than one field.")
    if errors:
        raise ValidationError(errors)

    df = pd.DataFrame({k: raw[v] for k, v in mapping.items()})
    rows_in = len(df)
    if rows_in == 0:
        raise ValidationError("The purchases file has no data rows.")
    dropped = {}

    def drop(mask, reason):
        nonlocal df
        n = int(mask.sum())
        if n:
            dropped[reason] = dropped.get(reason, 0) + n
        df = df[~mask]

    for c in ("medicine_id", "batch_id", "branch_id", "supplier"):
        if c in df:
            df[c] = df[c].astype(str).str.strip()
    drop(df["medicine_id"] == "", "missing medicine_id")
    for c in ("medicine_id", "batch_id", "branch_id"):
        if c in df and (df[c].str.len() > MAX_ID_LENGTH).any():
            raise ValidationError(f"Purchases file: values in {c} are longer than {MAX_ID_LENGTH} characters. Use shorter codes.")

    dates = pd.to_datetime(df["purchase_date"].str.strip(), errors="coerce")
    if dates.isna().mean() > 0.05:
        raise ValidationError("Purchases file: more than 5% of purchase_date values could not be read as dates (use YYYY-MM-DD).")
    df["_date"] = dates
    drop(df["_date"].isna(), "unreadable date")
    for c in ("quantity", "unit_purchase_price"):
        df[c] = pd.to_numeric(df[c].str.replace(",", "", regex=False), errors="coerce")
    drop(df["quantity"].isna() | df["unit_purchase_price"].isna(), "non-numeric quantity or price")
    drop(df["quantity"] <= 0, "zero or negative quantity")
    df["quantity"] = df["quantity"].round().astype("int64")
    drop(df["quantity"] <= 0, "zero or negative quantity")
    df["_price_c"] = np.rint(df["unit_purchase_price"] * 100).astype("int64")
    drop(df["_price_c"] <= 0, "zero or negative cost")

    # align to the sales calendar
    first, last = pd.Timestamp(sales["transaction_date"].min()), pd.Timestamp(sales["transaction_date"].max())
    before = int((df["_date"] < first).sum())
    df.loc[df["_date"] < first, "_date"] = first
    drop(df["_date"] > last, "received after the last sale date (ignored)")

    has_expiry = "expiry_date" in df
    if has_expiry:
        exp = pd.to_datetime(df["expiry_date"].str.strip(), errors="coerce")
        n_bad_exp = int(exp.isna().sum())
        if n_bad_exp / max(len(df), 1) > 0.5:
            raise ValidationError("Purchases file: more than half of the expiry_date values could not be read as dates (use YYYY-MM-DD).")
        df["_expiry"] = exp.fillna(pd.Timestamp(NO_EXPIRY))
        drop(df["_expiry"] <= df["_date"], "already expired when received")
    else:
        df["_expiry"] = pd.Timestamp(NO_EXPIRY)
        n_bad_exp = 0

    if len(df) == 0:
        raise ValidationError("No usable purchase rows remain after cleaning.")

    df["branch_id"] = df["branch_id"].replace("", UNKNOWN_BRANCH) if "branch_id" in df else UNKNOWN_BRANCH
    sale_branches = set(sales["branch_id"].unique())
    if "branch_id" not in mapping and len(sale_branches) > 1:
        raise ValidationError("Purchases file: your sales have several branches, so the purchases need a branch column (map branch_id).")
    if "branch_id" not in mapping and sale_branches != {UNKNOWN_BRANCH}:
        df["branch_id"] = next(iter(sale_branches))                       # single named branch in sales
    elif "branch_id" not in mapping:
        df["branch_id"] = UNKNOWN_BRANCH

    # batches: a batch id is local to a medicine; suffix the medicine id if the same id is used by several medicines
    warnings = []
    if "batch_id" in df and (df["batch_id"] != "").any():
        df["_batch"] = df["batch_id"].where(df["batch_id"] != "", other=pd.NA)
        clash = df.dropna(subset=["_batch"]).groupby("_batch")["medicine_id"].nunique()
        if (clash > 1).any():
            df["_batch"] = df["_batch"].where(~df["_batch"].isin(clash[clash > 1].index), df["_batch"] + "-" + df["medicine_id"])
            warnings.append(f"{int((clash > 1).sum())} batch ids were used by more than one medicine; the medicine id was appended to keep them distinct.")
    else:
        df["_batch"] = pd.NA
    df = df.reset_index(drop=True)
    df["purchase_id"] = [f"PUR{i:08d}" for i in range(1, len(df) + 1)]
    df["_batch"] = df["_batch"].fillna("L-" + df["purchase_id"])         # no batch id: every receipt is its own lot
    df["_batch"] = df["_batch"].str.slice(0, 60)

    if "supplier" in df and (df["supplier"] != "").any():
        sup_name = df["supplier"].replace("", "Unknown supplier").str.slice(0, 120)
        codes = {n: f"SUP{i:04d}" for i, n in enumerate(sorted(sup_name.unique()), 1)}
        df["_supplier_id"] = sup_name.map(codes)
        suppliers = pd.DataFrame({"supplier_id": list(codes.values()), "supplier_name": list(codes.keys()), "city": "Unknown"})
    else:
        df["_supplier_id"] = UNKNOWN_SUPPLIER
        suppliers = pd.DataFrame({"supplier_id": [UNKNOWN_SUPPLIER], "supplier_name": ["Unknown supplier"], "city": ["Unknown"]})

    # one lot per batch id: consistent expiry (the earliest wins), weighted-average cost, first receipt date as 'manufacture' date
    df["_value_c"] = df["quantity"] * df["_price_c"]
    lots = df.groupby("_batch", sort=True).agg(
        medicine_id=("medicine_id", "first"), supplier_id=("_supplier_id", "first"), first_receipt=("_date", "min"),
        expiry_min=("_expiry", "min"), expiry_max=("_expiry", "max"), qty=("quantity", "sum"), value_c=("_value_c", "sum")).reset_index()
    if (lots["expiry_min"] != lots["expiry_max"]).any():
        warnings.append(f"{int((lots['expiry_min'] != lots['expiry_max']).sum())} batches had different expiry dates on different receipts; the earliest was used.")
    df["_expiry"] = df["_batch"].map(lots.set_index("_batch")["expiry_min"])
    lots["avg_price_c"] = np.maximum(np.rint(lots["value_c"] / lots["qty"]).astype("int64"), 1)
    batches = pd.DataFrame({
        "batch_id": lots["_batch"], "medicine_id": lots["medicine_id"], "supplier_id": lots["supplier_id"],
        "manufacture_date": lots["first_receipt"].dt.strftime("%Y-%m-%d"), "expiry_date": lots["expiry_min"].dt.strftime("%Y-%m-%d"),
        "initial_quantity": lots["qty"].astype("int64"), "purchase_price": (lots["avg_price_c"] / 100).map("{:.2f}".format)})

    unit = (df["_price_c"] / 100).map("{:.2f}".format)
    purchases = pd.DataFrame({
        "purchase_id": df["purchase_id"], "purchase_date": df["_date"].dt.strftime("%Y-%m-%d"), "branch_id": df["branch_id"],
        "supplier_id": df["_supplier_id"], "medicine_id": df["medicine_id"], "batch_id": df["_batch"], "quantity": df["quantity"],
        "unit_purchase_price": unit, "total_cost": (df["quantity"] * df["_price_c"] / 100).map("{:.2f}".format)})

    new_meds = sorted(set(purchases["medicine_id"]) - set(sales["medicine_id"]))
    new_branches = sorted(set(purchases["branch_id"]) - set(sales["branch_id"]))
    med_total = n_medicines_in_sales + len(new_meds)
    br_total = n_branches_in_sales + len(new_branches)
    days = int((last - first).days) + 1
    dense = days * med_total * br_total
    if dense > MAX_DENSE_ROWS:
        raise ValidationError(f"Stock levels are tracked for every date × branch × medicine ({days} days × {br_total} branches × {med_total} medicines = "
                              f"{dense:,} rows, limit {MAX_DENSE_ROWS:,}). Upload a shorter period or fewer medicines/branches.")

    if before:
        warnings.append(f"{before:,} receipts dated before the first sale were counted as opening stock on {first.strftime('%Y-%m-%d')}.")
    if n_bad_exp:
        warnings.append(f"{n_bad_exp:,} receipts had no readable expiry date and are treated as never expiring.")
    if not has_expiry:
        warnings.append("No expiry date column: expiry risk analysis is unavailable (stock, reorder and overstock decisions still work).")
    if dropped:
        warnings.append("Purchase rows removed during cleaning: " + "; ".join(f"{n:,} {r}" for r, n in dropped.items()) + ".")
    if new_meds:
        warnings.append(f"{len(new_meds)} purchased medicines never appear in the sales file; they were added with no sales history.")

    report = {
        "rows_uploaded": int(rows_in), "rows_loaded": int(len(purchases)), "dropped": dropped, "batches": int(len(batches)),
        "units_received": int(purchases["quantity"].sum()), "has_expiry": bool(has_expiry), "mapping": mapping,
        "medicines_added": new_meds[:50], "branches_added": new_branches, "warnings": warnings}
    return purchases, batches, suppliers, report
