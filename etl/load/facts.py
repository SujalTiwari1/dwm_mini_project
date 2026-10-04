"""Load the fact tables."""
from .postgres import copy_dataframe


def load_facts(conn, facts: dict) -> dict:
    return {name: copy_dataframe(conn, name, facts[name]) for name in ("fact_sales", "fact_purchase", "fact_inventory")}
