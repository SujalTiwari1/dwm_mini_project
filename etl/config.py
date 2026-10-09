"""ETL configuration. Database credentials come from the environment (DATABASE_URL), never from code."""
import os
from pathlib import Path

try:  # optional: load a local .env file (git-ignored)
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if load_dotenv:
    load_dotenv(PROJECT_ROOT / ".env")

from datasets import paths as _ds

RAW_DIR = _ds.raw_dir()                          # frozen source data (read-only); per-dataset when MEDSTOCK_DATASET is set
METADATA_DIR = PROJECT_ROOT / "data" / "metadata"
SQL_DIR = PROJECT_ROOT / "sql"
SCHEMA = "warehouse"
RAW_TABLES = ["categories", "medicines", "branches", "suppliers", "batches", "purchases", "sales"]

# Load order respects foreign keys; truncate order is the reverse.
DIM_TABLES = ["dim_date", "dim_category", "dim_medicine", "dim_branch", "dim_supplier", "dim_batch"]
FACT_TABLES = ["fact_sales", "fact_purchase", "fact_inventory"]

COPY_CHUNK_ROWS = 200_000


def get_database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise SystemExit(
            "DATABASE_URL is not set. Copy .env.example to .env and set it, e.g.\n"
            "  DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/medstock"
        )
    # accept the plain libpq-style URL too
    for plain in ("postgresql://", "postgres://"):
        if url.startswith(plain):
            url = "postgresql+psycopg://" + url[len(plain):]
    return url
