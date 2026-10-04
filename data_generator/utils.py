"""Small shared helpers."""
import numpy as np


def make_id(prefix: str, n: int, width: int = 3) -> str:
    return f"{prefix}{n:0{width}d}"


def spawn_rngs(seed: int, names):
    """Independent, reproducible RNG streams, one per named component."""
    children = np.random.SeedSequence(seed).spawn(len(names))
    return {name: np.random.default_rng(c) for name, c in zip(names, children)}
