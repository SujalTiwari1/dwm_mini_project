import numpy as np
import pandas as pd

from .. import config as C
from ..catalog import CATALOG, MANUFACTURERS
from ..utils import make_id

PUBLIC_COLUMNS = [
    "medicine_id", "medicine_name", "category_id", "manufacturer",
    "dosage_form", "strength", "base_price", "demand_profile",
]


def generate_medicines(n: int, rng: np.random.Generator):
    """Return (public medicines df, internal df aligned row-by-row).

    The internal frame (catalog key, shelf life, variant flag) is generation
    metadata and is NOT written to medicines.csv.
    """
    items = []  # (entry, strength, manufacturer, price, profile, is_variant)
    for e in CATALOG[:n]:
        items.append((e, e.strengths[0], e.manufacturer, e.price, e.profile, False))

    extra = n - len(items)
    if extra > 0:
        variants = []
        for e in CATALOG:
            for s_i, strength in enumerate(e.strengths):
                for mf in [e.manufacturer] + [m for m in MANUFACTURERS if m != e.manufacturer]:
                    if s_i == 0 and mf == e.manufacturer:
                        continue  # that is the base entry itself
                    variants.append((e, s_i, strength, mf))
        if extra > len(variants):
            raise ValueError(f"num_medicines={n} exceeds catalog capacity ({len(CATALOG) + len(variants)})")
        order = rng.permutation(len(variants))[:extra]
        chosen = sorted((variants[i] for i in order), key=lambda v: (v[0].category, v[0].key, v[1], v[3]))
        profiles = list(C.DEMAND_PROFILES)
        probs = [C.DEMAND_PROFILES[p]["mix"] for p in profiles]
        for e, s_i, strength, mf in chosen:
            price = round(e.price * (1 + 0.18 * s_i) * rng.uniform(0.9, 1.1), 2)
            profile = str(rng.choice(profiles, p=probs))
            items.append((e, strength, mf, price, profile, True))

    used = set()
    pub, internal = [], []
    for i, (e, strength, mf, price, profile, is_variant) in enumerate(items):
        name = f"{e.generic} {strength}"
        if name in used:
            name = f"{e.generic} {strength} ({mf})"
        k = 2
        while name in used:
            name = f"{e.generic} {strength} ({mf}) #{k}"
            k += 1
        used.add(name)
        pub.append((make_id("MED", i + 1), name, e.category, mf, e.form, strength, round(price, 2), profile))
        internal.append((e.key, e.shelf_months, is_variant))

    return (
        pd.DataFrame(pub, columns=PUBLIC_COLUMNS),
        pd.DataFrame(internal, columns=["key", "shelf_life_months", "is_variant"]),
    )
