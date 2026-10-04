"""Association rule mining: Apriori on transaction baskets (item = medicine).

Interpretation: a rule A -> B says "transactions containing A were more likely to also contain B". It is transaction-level
co-occurrence. It is not causation and it says nothing about patients or treatment.
"""
import time

import numpy as np
import pandas as pd
from mlxtend.frequent_patterns import apriori, association_rules

from .. import config as C
from ..features.build_features import load_baskets


def _names(itemset, labels):
    return " + ".join(sorted(labels[i] for i in itemset))


def _to_frame(X, columns):
    """Boolean sparse DataFrame accepted by mlxtend's Apriori."""
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")          # pandas FutureWarning about the sparse fill value
        return pd.DataFrame.sparse.from_spmatrix(X, columns=columns)


def frequent_itemsets(X, min_support, max_len):
    """mlxtend Apriori with exact supports over ALL transactions, made tractable for 613k baskets.

    mlxtend densifies the candidate matrix (about 20 GB at this size). A basket with one medicine cannot support any itemset of
    two or more medicines, so Apriori (low_memory mode) runs on the multi-medicine baskets only, with the support threshold converted to
    an absolute transaction count. Counts of itemsets of size >= 2 are identical to counts over all transactions. Singleton supports
    (needed for confidence and lift) are taken from the full data, so every metric is exact.
    """
    n_tx = X.shape[0]
    threshold = int(np.ceil(min_support * n_tx - 1e-9))
    full_counts = np.asarray(X.sum(axis=0)).ravel()
    sizes = np.asarray(X.sum(axis=1)).ravel()
    Xm = X[sizes > 1]
    fi = apriori(_to_frame(Xm, list(range(X.shape[1]))), min_support=max(threshold / Xm.shape[0] - 1e-12, 1e-12),
                 use_colnames=True, max_len=max_len, low_memory=True)
    fi["support_count"] = np.rint(fi["support"] * Xm.shape[0]).astype(int)
    multi = fi[fi["itemsets"].map(len) >= 2][["itemsets", "support_count"]]
    singles = pd.DataFrame({"itemsets": [frozenset([int(i)]) for i in np.flatnonzero(full_counts >= threshold)],
                            "support_count": full_counts[full_counts >= threshold].astype(int)})
    out = pd.concat([singles, multi], ignore_index=True)
    out["support"] = out["support_count"] / n_tx
    return out[["support", "itemsets", "support_count"]], threshold


def itemset_count_at(X, supports, max_len):
    """Sensitivity table: number of frequent itemsets (by size) for several minimum supports."""
    rows = []
    n_tx = X.shape[0]
    for s in sorted(supports, reverse=True):
        fi, thr = frequent_itemsets(X, s, max_len)
        sizes = fi["itemsets"].map(len).value_counts().to_dict()
        rr = association_rules(fi, metric="confidence", min_threshold=C.ASSOCIATION["min_confidence"])
        strong = rr[rr["lift"] > C.ASSOCIATION["min_lift"]]
        rows.append({"min_support": s, "min_transactions": thr, "frequent_itemsets": len(fi), "size_1": int(sizes.get(1, 0)),
                     "size_2": int(sizes.get(2, 0)), "size_3": int(sizes.get(3, 0)), "useful_rules": int(len(strong)),
                     "rules_with_lift_over_5": int((strong["lift"] > 5).sum())})
    return rows


def mine(conn, sensitivity=True):
    cfg = C.ASSOCIATION
    X, meds, tx_ids = load_baskets(conn)
    n_tx = X.shape[0]
    labels = [f"{n} [{i}]" for i, n in zip(meds["medicine_id"], meds["medicine_name"])]   # human-readable, unique
    sensitivity_rows = itemset_count_at(X, cfg["sensitivity_supports"], cfg["max_itemset_len"]) if sensitivity else []

    fi, _ = frequent_itemsets(X, cfg["min_support"], cfg["max_itemset_len"])
    fi = fi.assign(itemset_size=fi["itemsets"].map(len))
    fi_out = pd.DataFrame({
        "itemset": fi["itemsets"].map(lambda s: _names(s, labels)),
        "itemset_size": fi["itemset_size"], "support": fi["support"].round(6), "support_count": fi["support_count"],
    }).sort_values(["itemset_size", "support_count", "itemset"], ascending=[True, False, True]).reset_index(drop=True)

    raw_rules = association_rules(fi, metric="confidence", min_threshold=cfg["min_confidence"])
    n_generated = len(raw_rules)
    r = raw_rules.copy()
    r["antecedent_ids"] = r["antecedents"].map(lambda s: tuple(sorted(s)))
    r["consequent_ids"] = r["consequents"].map(lambda s: tuple(sorted(s)))
    # useful = real association (lift above 1), no overlap between sides (no A -> A style rule), finite metrics
    useful = r[(r["lift"] > cfg["min_lift"]) & r.apply(lambda x: not (set(x["antecedents"]) & set(x["consequents"])), axis=1)
               & np.isfinite(r["lift"]) & np.isfinite(r["leverage"])].copy()
    useful["support_count"] = np.rint(useful["support"] * n_tx).astype(int)
    useful["antecedent_support_count"] = np.rint(useful["antecedent support"] * n_tx).astype(int)
    useful["consequent_support_count"] = np.rint(useful["consequent support"] * n_tx).astype(int)
    useful["antecedent"] = useful["antecedents"].map(lambda s: _names(s, labels))
    useful["consequent"] = useful["consequents"].map(lambda s: _names(s, labels))
    useful["itemset_key"] = useful.apply(lambda x: " + ".join(sorted([*x["antecedent"].split(" + "), *x["consequent"].split(" + ")])), axis=1)
    pair_keys = set(zip(useful["antecedent"], useful["consequent"]))
    useful["reverse_rule_present"] = [(c, a) in pair_keys for a, c in zip(useful["antecedent"], useful["consequent"])]
    useful["conviction"] = useful["conviction"].replace([np.inf], np.nan)     # conviction is infinite when confidence = 1
    useful = useful.sort_values(["lift", "confidence", "support"], ascending=False, kind="mergesort").reset_index(drop=True)

    rules_out = useful[["antecedent", "consequent", "support", "support_count", "confidence", "lift", "leverage", "conviction",
                        "antecedent_support_count", "consequent_support_count", "reverse_rule_present"]].copy()
    rules_out["antecedent_size"] = useful["antecedents"].map(len)
    rules_out["consequent_size"] = useful["consequents"].map(len)
    for col in ("support", "confidence", "lift", "leverage"):
        rules_out[col] = rules_out[col].round(6)
    rules_out["conviction"] = rules_out["conviction"].round(6)

    # top rules for the summary: one direction per itemset (the higher-confidence one), pairs only for readability
    dedup = useful.sort_values(["itemset_key", "confidence"], ascending=[True, False], kind="mergesort").drop_duplicates("itemset_key")
    top = dedup.sort_values(["lift", "confidence", "support"], ascending=False, kind="mergesort").head(cfg["top_rules_in_summary"])
    top_rules = [{"antecedent": a, "consequent": c, "support": round(float(s), 6), "support_count": int(n), "confidence": round(float(cf), 4),
                  "lift": round(float(l), 2)} for a, c, s, n, cf, l in zip(top["antecedent"], top["consequent"], top["support"],
                                                                         top["support_count"], top["confidence"], top["lift"])]
    summary = {
        "transactions": int(n_tx), "unique_medicines": int(X.shape[1]), "medicines_appearing_in_a_basket": int((X.sum(axis=0) > 0).sum()),
        "multi_item_transactions": int((np.asarray(X.sum(axis=1)).ravel() > 1).sum()),
        "min_support": cfg["min_support"], "min_support_transactions": int(np.ceil(cfg["min_support"] * n_tx)),
        "min_confidence": cfg["min_confidence"], "min_lift": cfg["min_lift"], "max_itemset_len": cfg["max_itemset_len"],
        "frequent_itemsets": int(len(fi_out)), "frequent_itemsets_by_size": {int(k): int(v) for k, v in fi_out["itemset_size"].value_counts().sort_index().items()},
        "rules_generated_before_filter": int(n_generated), "useful_rules_after_filter": int(len(rules_out)),
        "unique_rule_itemsets": int(useful["itemset_key"].nunique()),
        "rules_with_reverse_direction": int(useful["reverse_rule_present"].sum()),
        "support_sensitivity": sensitivity_rows,
        "top_rules_one_direction_per_itemset": top_rules,
        "interpretation": "A -> B: transactions containing A were more likely to also contain B (transaction-level co-occurrence, not causation).",
    }
    return {"frequent_itemsets": fi_out, "rules": rules_out, "summary": summary, "n_transactions": int(n_tx), "labels": labels}
