"""Feature preparation: pull mining datasets from PostgreSQL (SQL does the aggregation) and shape them for the algorithms.

Nothing in this module (or in association/, clustering/, anomaly/) may read data/metadata/ground_truth_private.json:
that file is opened only by data_mining/evaluation/evaluate.py after all detections exist.
"""
import json

import numpy as np
import pandas as pd
from scipy import sparse

from analytics.run import split_statements
from etl.load.postgres import get_engine

from .. import config as C

_STATEMENTS = None


def _statements():
    global _STATEMENTS
    if _STATEMENTS is None:
        _STATEMENTS = dict(split_statements((C.SQL_DIR / "mining_data.sql").read_text(encoding="utf-8")))
    return _STATEMENTS


def run_query(conn, name: str) -> pd.DataFrame:
    res = conn.exec_driver_sql(_statements()[name])
    return pd.DataFrame(res.fetchall(), columns=list(res.keys()))


def open_connection():
    """Return (engine, connection). Caller closes both."""
    engine = get_engine()
    conn = engine.connect()
    conn.exec_driver_sql("SET work_mem = '128MB'")        # session-level, avoids disk spills in the big aggregations
    return engine, conn


def dataset_reference() -> dict:
    """Public dataset descriptor (generator version etc.). This file contains no hidden ground truth."""
    meta = json.loads(C.GENERATION_METADATA.read_text(encoding="utf-8"))
    return {k: meta.get(k) for k in ("generator_version", "frozen_on", "random_seed", "date_range", "demand_scale")}


# ---------------------------------------------------------------------------
# association: baskets
# ---------------------------------------------------------------------------
def load_baskets(conn):
    """Return (sparse boolean basket matrix [transactions x medicines], medicine frame, transaction ids)."""
    meds = run_query(conn, "medicines")
    pairs = run_query(conn, "baskets")
    tx_codes, tx_ids = pd.factorize(pairs["transaction_id"], sort=True)
    col = pairs["medicine_key"].map({k: i for i, k in enumerate(meds["medicine_key"])}).to_numpy()
    X = sparse.csr_matrix((np.ones(len(pairs), dtype=bool), (tx_codes, col)), shape=(len(tx_ids), len(meds)))
    return X, meds, tx_ids


# ---------------------------------------------------------------------------
# clustering: medicine feature table
# ---------------------------------------------------------------------------
def load_medicine_features(conn) -> pd.DataFrame:
    df = run_query(conn, "medicine_features")
    for c in df.columns:
        if c not in ("medicine_id", "medicine_name", "category"):
            df[c] = pd.to_numeric(df[c])
    return df


# ---------------------------------------------------------------------------
# anomaly detection: wide daily matrices (dates x series)
# ---------------------------------------------------------------------------
def load_daily_cube(conn):
    """Return dict with dates, meds, branches and arrays shaped [T, B, M] for units, revenue and inventory."""
    dates = run_query(conn, "dates")
    meds = run_query(conn, "medicines")
    branches = run_query(conn, "branches")
    daily = run_query(conn, "daily_series")
    T, B, M = len(dates), len(branches), len(meds)
    if len(daily) != T * B * M:
        raise ValueError(f"daily series is not dense: {len(daily)} rows vs {T * B * M}")
    # rows are ordered by date, branch, medicine (see SQL), so a reshape is exact
    shape = (T, B, M)
    return {
        "dates": dates, "meds": meds, "branches": branches,
        "units": daily["units"].to_numpy(dtype=np.float64).reshape(shape),
        "revenue": daily["revenue"].to_numpy(dtype=np.float64).reshape(shape),
        "inventory": daily["inventory_units"].to_numpy(dtype=np.float64).reshape(shape),
    }


def load_purchase_lots(conn) -> pd.DataFrame:
    df = run_query(conn, "purchase_lots")
    df["unit_cost"] = pd.to_numeric(df["unit_cost"])
    return df


def warehouse_counts(conn) -> dict:
    return run_query(conn, "warehouse_counts").iloc[0].to_dict()
