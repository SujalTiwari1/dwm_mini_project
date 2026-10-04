import pandas as pd

from .. import config as C


def generate_categories() -> pd.DataFrame:
    return pd.DataFrame(C.CATEGORIES, columns=["category_id", "category_name"])
