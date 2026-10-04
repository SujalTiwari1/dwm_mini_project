"""Extract: read the frozen raw CSVs (read-only) and run source sanity checks.

Money columns are read as text so they reach PostgreSQL NUMERIC exactly as written (no float round-trip).
"""
import hashlib
import re

import pandas as pd

from .. import config as C

EXPECTED_COLUMNS = {
    "categories": ["category_id", "category_name"],
    "medicines": ["medicine_id", "medicine_name", "category_id", "manufacturer", "dosage_form", "strength",
                  "base_price", "demand_profile"],
    "branches": ["branch_id", "branch_name", "city", "area"],
    "suppliers": ["supplier_id", "supplier_name", "city"],
    "batches": ["batch_id", "medicine_id", "supplier_id", "manufacture_date", "expiry_date",
                "initial_quantity", "purchase_price"],
    "purchases": ["purchase_id", "purchase_date", "branch_id", "supplier_id", "medicine_id", "batch_id",
                  "quantity", "unit_purchase_price", "total_cost"],
    "sales": ["transaction_id", "transaction_date", "branch_id", "medicine_id", "batch_id", "quantity",
              "unit_selling_price", "discount", "total_amount"],
}
MONEY_COLUMNS = {
    "medicines": ["base_price"], "batches": ["purchase_price"],
    "purchases": ["unit_purchase_price", "total_cost"],
    "sales": ["unit_selling_price", "discount", "total_amount"],
}
INT_COLUMNS = {"batches": ["initial_quantity"], "purchases": ["quantity"], "sales": ["quantity"]}
PRIMARY_KEYS = {"categories": ["category_id"], "medicines": ["medicine_id"], "branches": ["branch_id"],
                "suppliers": ["supplier_id"], "batches": ["batch_id"], "purchases": ["purchase_id"],
                "sales": ["transaction_id", "medicine_id", "batch_id"]}
_MONEY_RE = re.compile(r"^\d+\.\d{2}$")


def file_checksums() -> dict:
    """MD5 of each raw file; used to prove the frozen data was not modified by the ETL."""
    out = {}
    for name in C.RAW_TABLES:
        h = hashlib.md5()
        with open(C.RAW_DIR / f"{name}.csv", "rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                h.update(block)
        out[name] = h.hexdigest()
    return out


def extract() -> dict:
    """Return {table: DataFrame}. Raises ValueError if the source does not match the expected structure."""
    raw = {}
    for name in C.RAW_TABLES:
        df = pd.read_csv(C.RAW_DIR / f"{name}.csv", dtype=str, keep_default_na=False)
        if list(df.columns) != EXPECTED_COLUMNS[name]:
            raise ValueError(f"{name}.csv columns {list(df.columns)} differ from expected {EXPECTED_COLUMNS[name]}")
        if (df == "").any().any():
            raise ValueError(f"{name}.csv contains empty values")
        for col in MONEY_COLUMNS.get(name, []):
            if not df[col].str.fullmatch(_MONEY_RE).all():
                raise ValueError(f"{name}.{col} has values that are not exact 2-decimal amounts")
        for col in INT_COLUMNS.get(name, []):
            df[col] = df[col].astype("int64")
        if df.duplicated(PRIMARY_KEYS[name]).any():
            raise ValueError(f"{name}.csv has duplicate source keys {PRIMARY_KEYS[name]}")
        raw[name] = df
    return raw
