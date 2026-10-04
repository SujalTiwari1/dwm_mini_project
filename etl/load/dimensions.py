"""Load the dimension tables (in foreign-key order)."""
from .. import config as C
from .postgres import copy_dataframe


def load_dimensions(conn, dims: dict) -> dict:
    return {name: copy_dataframe(conn, name, dims[name]) for name in C.DIM_TABLES}
