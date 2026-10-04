import pandas as pd

from .. import config as C
from ..catalog import BRANCH_POOL
from ..utils import make_id


def generate_branches(n: int) -> pd.DataFrame:
    if n > len(BRANCH_POOL):
        raise ValueError(f"num_branches={n} exceeds branch pool ({len(BRANCH_POOL)}); extend catalog.BRANCH_POOL")
    rows = [
        (make_id("BR", i + 1), name, C.DATASET_CONFIG["branch_city"], area)
        for i, (name, area) in enumerate(BRANCH_POOL[:n])
    ]
    return pd.DataFrame(rows, columns=["branch_id", "branch_name", "city", "area"])
