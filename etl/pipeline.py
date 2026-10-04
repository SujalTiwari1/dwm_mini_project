"""MedStock ETL: frozen raw CSVs -> PostgreSQL star schema.

    Extract -> Transform -> (create schema, truncate) -> Load dimensions -> Load facts
            -> Reconstruct inventory (transform) & load -> ANALYZE -> Validate warehouse

Run from the repository root:   python -m etl.pipeline
Idempotent by full rebuild: every run truncates all warehouse tables and reloads them in one transaction.
"""
import json
import sys
import time

from . import config as C
from .extract.csv_loader import extract, file_checksums
from .load.dimensions import load_dimensions
from .load.facts import load_facts
from .load.postgres import (analyze_all, create_schema, drop_fact_foreign_keys, drop_secondary_indexes, get_engine,
                            restore_foreign_keys, truncate_all)
from .transform.dimensions import build_dimensions, derive_date_range
from .transform.inventory import build_fact_inventory
from .transform.purchases import build_fact_purchase
from .transform.sales import build_fact_sales
from .validation.warehouse_checks import print_results, run_all


class Timer:
    def __init__(self):
        self.t0 = time.time()
        self.steps = {}

    def step(self, name, t_start):
        self.steps[name] = round(time.time() - t_start, 1)
        print(f"  {name:<34}{self.steps[name]:>7.1f}s")


def main() -> int:
    timer, total0 = Timer(), time.time()
    print("MedStock ETL -> PostgreSQL warehouse")
    checksums_before = file_checksums()

    t = time.time()
    raw = extract()
    timer.step("extract (7 CSVs)", t)
    print("   source rows: " + ", ".join(f"{k}={len(v):,}" for k, v in raw.items()))

    t = time.time()
    start, end = derive_date_range(raw)
    dims, keys = build_dimensions(raw, start, end)
    fact_sales = build_fact_sales(raw, keys, dims["dim_date"])
    fact_purchase = build_fact_purchase(raw, keys, dims["dim_date"])
    timer.step("transform dimensions + facts", t)

    t = time.time()
    fact_inventory, inv_totals = build_fact_inventory(dims, fact_sales, fact_purchase)
    timer.step("reconstruct inventory", t)
    print(f"   inventory: purchased {inv_totals['purchased']:,} - sold {inv_totals['sold']:,} - expired "
          f"{inv_totals['expired']:,} = closing {inv_totals['closing_final_day']:,} units")

    facts = {"fact_sales": fact_sales, "fact_purchase": fact_purchase, "fact_inventory": fact_inventory}
    engine = get_engine()
    loaded = {}
    with engine.begin() as conn:                      # one transaction: all-or-nothing rebuild
        t = time.time()
        create_schema(conn)
        truncate_all(conn)
        drop_secondary_indexes(conn)
        saved_fks = drop_fact_foreign_keys(conn)
        timer.step("create schema + truncate", t)
        t = time.time()
        loaded.update(load_dimensions(conn, dims))
        timer.step("load dimensions", t)
        t = time.time()
        loaded.update(load_facts(conn, facts))
        timer.step("load facts (COPY)", t)
        t = time.time()
        restore_foreign_keys(conn, saved_fks)         # validates every loaded fact row
        create_schema(conn)                           # idempotent: recreates the secondary indexes
        timer.step("restore FKs + rebuild indexes", t)
        t = time.time()
        analyze_all(conn)
        timer.step("analyze", t)

    t = time.time()
    results = run_all(raw=raw)
    timer.step("validate warehouse", t)
    engine.dispose()

    checksums_after = file_checksums()
    results.append({"source": "raw", "check": "frozen raw CSVs unchanged by the ETL (MD5 before = after)",
                    "expected": "identical", "actual": "identical" if checksums_before == checksums_after else "CHANGED",
                    "status": "PASS" if checksums_before == checksums_after else "FAIL"})

    total = round(time.time() - total0, 1)
    print(f"Rows loaded: " + ", ".join(f"{k}={v:,}" for k, v in loaded.items()) + f"  (total {sum(loaded.values()):,})")
    print(f"ETL duration: {total}s")
    errors = print_results(results)

    C.METADATA_DIR.mkdir(parents=True, exist_ok=True)
    (C.METADATA_DIR / "warehouse_validation.json").write_text(json.dumps({
        "rows_loaded": loaded, "etl_seconds": total, "step_seconds": timer.steps,
        "inventory_totals": inv_totals, "raw_md5": checksums_after,
        "validation_errors": errors, "checks": results}, indent=2, default=str), encoding="utf-8")
    print("WAREHOUSE VALIDATION " + ("PASSED" if not errors else "FAILED"))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
