"""Validate and clean an uploaded sales file into the canonical shape the ETL expects.

Required (after column mapping): transaction_date, medicine_id, quantity, unit_selling_price.
Optional: transaction_id (baskets -> association rules), branch_id, medicine_name, category, discount, total_amount.
Nothing is invented: rows that cannot be used are dropped and counted in the report, never silently repaired.
"""
import re

import numpy as np
import pandas as pd

REQUIRED = ["transaction_date", "medicine_id", "quantity", "unit_selling_price"]
OPTIONAL = ["transaction_id", "branch_id", "medicine_name", "category", "discount", "total_amount"]
CANONICAL = REQUIRED + OPTIONAL

MAX_ROWS = 3_000_000
MIN_ROWS = 100
MAX_MEDICINES = 5_000
MAX_BRANCHES = 200
MAX_ID_LENGTH = 40
MIN_SPAN_DAYS_FORECAST = 180      # shorter history: forecasting is skipped (explained to the user)
UNKNOWN_BRANCH = "BR_ALL"
UNKNOWN_CATEGORY = "General"

SYNONYMS = {
    "transaction_date": ["transaction_date", "date", "sale_date", "sales_date", "invoice_date", "order_date", "bill_date", "datetime", "timestamp"],
    "medicine_id": ["medicine_id", "product_id", "item_id", "sku", "drug_id", "item_code", "product_code", "medicine_code"],
    "quantity": ["quantity", "qty", "units", "units_sold", "quantity_sold", "count"],
    "unit_selling_price": ["unit_selling_price", "unit_price", "price", "selling_price", "rate", "mrp", "sale_price"],
    "transaction_id": ["transaction_id", "invoice_id", "invoice_no", "bill_no", "bill_id", "order_id", "receipt_id", "txn_id"],
    "branch_id": ["branch_id", "branch", "store_id", "store", "outlet", "location", "shop_id"],
    "medicine_name": ["medicine_name", "product_name", "item_name", "drug_name", "name", "description", "medicine"],
    "category": ["category", "category_name", "product_category", "drug_class", "type", "department"],
    "discount": ["discount", "discount_amount", "disc"],
    "total_amount": ["total_amount", "total", "amount", "line_total", "revenue", "net_amount", "sales_amount"],
}


class ValidationError(Exception):
    """The upload cannot be used. `messages` are written for the end user."""

    def __init__(self, messages):
        self.messages = [messages] if isinstance(messages, str) else list(messages)
        super().__init__("; ".join(self.messages))


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(s).strip().lower()).strip("_")


def suggest_mapping(headers: list[str]) -> dict:
    """Best-effort {canonical: uploaded header}. Exact (normalised) synonym match only; a header is used at most once."""
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
        raise ValidationError("The file could not be read as a CSV. Upload a comma-separated .csv file with a header row.")
    headers = [str(c) for c in df.columns]
    return {"headers": headers, "suggested_mapping": suggest_mapping(headers), "sample_rows": df.head(nrows).to_dict("records"),
            "required": REQUIRED, "optional": OPTIONAL}


def clean_sales(path, mapping: dict | None = None) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Return (sales, medicine_master, report). Raises ValidationError with every problem found."""
    try:
        raw = pd.read_csv(path, dtype=str, keep_default_na=False, nrows=MAX_ROWS + 1)
    except Exception:
        raise ValidationError("The file could not be read as a CSV. Upload a comma-separated .csv file with a header row.")
    if len(raw) > MAX_ROWS:
        raise ValidationError(f"The file has more than {MAX_ROWS:,} rows. Upload a smaller extract (for example, fewer months).")
    raw.columns = [str(c).strip() for c in raw.columns]

    mapping = {k: v for k, v in (mapping or suggest_mapping(list(raw.columns))).items() if v}
    errors = []
    missing = [c for c in REQUIRED if c not in mapping]
    if missing:
        errors.append("Missing required column(s): " + ", ".join(missing) + ". Map them to columns of your file.")
    bad = [f"{k} -> '{v}'" for k, v in mapping.items() if k not in CANONICAL or v not in raw.columns]
    if bad:
        errors.append("Mapping refers to columns that do not exist: " + ", ".join(bad))
    if len(set(mapping.values())) != len(mapping):
        errors.append("The same file column is mapped to more than one field.")
    if errors:
        raise ValidationError(errors)

    df = pd.DataFrame({k: raw[v] for k, v in mapping.items()})
    rows_in = len(df)
    if rows_in < MIN_ROWS:
        raise ValidationError(f"The file has only {rows_in} data rows; at least {MIN_ROWS} are needed for meaningful analytics.")

    dropped = {}

    def drop(mask, reason):
        n = int(mask.sum())
        if n:
            dropped[reason] = dropped.get(reason, 0) + n
        return df[~mask]

    # ids
    for c in ("medicine_id", "branch_id", "transaction_id", "medicine_name", "category"):
        if c in df:
            df[c] = df[c].astype(str).str.strip()
    df = drop(df["medicine_id"] == "", "missing medicine_id")
    too_long = [c for c in ("medicine_id", "branch_id", "transaction_id") if c in df and (df[c].str.len() > MAX_ID_LENGTH).any()]
    if too_long:
        raise ValidationError(f"Values in {', '.join(too_long)} are longer than {MAX_ID_LENGTH} characters. Use shorter codes.")

    # dates
    dates = pd.to_datetime(df["transaction_date"].str.strip(), errors="coerce")
    if dates.isna().mean() > 0.05:
        raise ValidationError("More than 5% of transaction_date values could not be read as dates (use YYYY-MM-DD, e.g. 2025-03-31).")
    df = df.assign(_date=dates)
    df = drop(df["_date"].isna(), "unreadable date")

    # numbers
    for c in ("quantity", "unit_selling_price", "discount", "total_amount"):
        if c in df:
            df[c] = pd.to_numeric(df[c].str.replace(",", "", regex=False), errors="coerce")
    df = drop(df["quantity"].isna() | df["unit_selling_price"].isna(), "non-numeric quantity or price")
    df = drop(df["quantity"] <= 0, "zero or negative quantity (returns)")
    df = drop(df["unit_selling_price"] <= 0, "zero or negative price")
    df["discount"] = df["discount"].fillna(0).clip(lower=0) if "discount" in df else 0.0
    # The warehouse enforces line total = quantity x unit price - discount exactly, so the line total is always recomputed
    # (a total_amount column in the file is accepted for mapping but not used).

    has_branches = "branch_id" in df and (df["branch_id"] != "").any()
    df["branch_id"] = df["branch_id"].replace("", UNKNOWN_BRANCH) if "branch_id" in df else UNKNOWN_BRANCH
    has_baskets = "transaction_id" in df and (df["transaction_id"] != "").mean() > 0.5
    if has_baskets:
        df["transaction_id"] = df["transaction_id"].replace("", np.nan)
        df = drop(df["transaction_id"].isna(), "missing transaction_id")
    else:
        df["transaction_id"] = [f"TXN{i:08d}" for i in range(1, len(df) + 1)]   # one line per transaction: no basket information

    if len(df) < MIN_ROWS:
        raise ValidationError(f"Only {len(df)} usable rows remain after cleaning; at least {MIN_ROWS} are needed.")
    n_med, n_br = df["medicine_id"].nunique(), df["branch_id"].nunique()
    if n_med > MAX_MEDICINES:
        raise ValidationError(f"The file has {n_med:,} distinct medicines (limit {MAX_MEDICINES:,}).")
    if n_br > MAX_BRANCHES:
        raise ValidationError(f"The file has {n_br:,} distinct branches (limit {MAX_BRANCHES}).")

    # master data derived from the sales rows (no other file is available)
    def first_by_medicine(col):
        if col not in df:
            return pd.Series(dtype=str)
        have = df[df[col].fillna("") != ""]
        return have.groupby("medicine_id")[col].first()

    names, cats = first_by_medicine("medicine_name"), first_by_medicine("category")
    meds = pd.DataFrame({"medicine_id": sorted(df["medicine_id"].unique())})
    meds["medicine_name"] = meds["medicine_id"].map(names).fillna(meds["medicine_id"])
    meds["category"] = meds["medicine_id"].map(cats).fillna(UNKNOWN_CATEGORY)
    meds["medicine_name"] = meds["medicine_name"].str.slice(0, 120)       # fits the warehouse column widths
    meds["category"] = meds["category"].str.slice(0, 60)

    # one row per (transaction, medicine) = the ETL grain; duplicates are merged and counted
    before = len(df)
    df["_gross"] = df["quantity"] * df["unit_selling_price"]
    g = df.groupby(["transaction_id", "medicine_id"], sort=False).agg(
        _date=("_date", "min"), branch_id=("branch_id", "first"), quantity=("quantity", "sum"),
        _gross=("_gross", "sum"), discount=("discount", "sum")).reset_index()
    merged = before - len(g)
    if merged:
        dropped["duplicate lines merged into one"] = merged
    g["quantity"] = g["quantity"].round().astype("int64")
    price_c = np.rint(g["_gross"] / g["quantity"] * 100).astype("int64")          # unit price in paise, 2 decimals
    bad_price = price_c <= 0
    if bad_price.any():
        dropped["price rounds to zero"] = int(bad_price.sum())
        g, price_c = g[~bad_price], price_c[~bad_price]
    g = g.sort_values(["_date", "transaction_id", "medicine_id"], kind="stable")
    price_c = price_c.loc[g.index].to_numpy()
    g = g.reset_index(drop=True)
    gross_c = g["quantity"].to_numpy() * price_c
    disc_c = np.minimum(np.rint(g["discount"].to_numpy() * 100).astype("int64"), gross_c)   # a discount cannot exceed the line value
    total_c = gross_c - disc_c

    def money(c):
        return pd.Series(c / 100.0).map("{:.2f}".format)

    sales = pd.DataFrame({
        "transaction_id": g["transaction_id"],
        "transaction_date": g["_date"].dt.strftime("%Y-%m-%d"),
        "branch_id": g["branch_id"],
        "medicine_id": g["medicine_id"],
        "batch_id": "NOBATCH-" + g["medicine_id"],           # placeholder: replaced by FEFO allocation when purchases are uploaded
        "quantity": g["quantity"],
        "unit_selling_price": money(price_c),
        "discount": money(disc_c),
        "total_amount": money(total_c),
    })
    if (sales["quantity"] <= 0).any():
        raise ValidationError("Quantities must be whole units of at least 1.")

    first, last = pd.Timestamp(sales["transaction_date"].min()), pd.Timestamp(sales["transaction_date"].max())
    span = int((last - first).days) + 1
    if span < 2:
        raise ValidationError("All sales fall on a single day; at least two different dates are needed.")
    warnings = []
    if not has_branches:
        warnings.append("No branch column: all sales are treated as one location.")
    if not has_baskets:
        warnings.append("No transaction id: each line is its own transaction, so association rules (items bought together) are not available.")
    if span < MIN_SPAN_DAYS_FORECAST:
        warnings.append(f"Only {span} days of history (at least {MIN_SPAN_DAYS_FORECAST} are needed): demand forecasting will be skipped.")
    if dropped:
        warnings.append("Rows removed during cleaning: " + "; ".join(f"{n:,} {r}" for r, n in dropped.items()) + ".")

    report = {
        "rows_uploaded": int(rows_in), "rows_loaded": int(len(sales)), "dropped": dropped,
        "date_from": first.strftime("%Y-%m-%d"), "date_to": last.strftime("%Y-%m-%d"), "days_span": span,
        "medicines": int(n_med), "branches": int(n_br), "transactions": int(sales["transaction_id"].nunique()),
        "total_units": int(sales["quantity"].sum()), "total_revenue": round(float(total_c.sum()) / 100, 2),
        "mapping": mapping, "warnings": warnings,
        "capabilities": {
            "sales_analytics": True,
            "association_rules": bool(has_baskets),
            "multi_branch": bool(has_branches and n_br > 1),
            "forecasting": span >= MIN_SPAN_DAYS_FORECAST,        # also needs the stock-free forecasting variant (later phase)
            "inventory_expiry_decisions": False,                   # needs a purchases file
            "decision_support": False,                             # needs a purchases file AND enough history to forecast
        },
    }
    return sales, meds, report
