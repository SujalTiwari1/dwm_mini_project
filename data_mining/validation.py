"""Validation of the mining layer: association, clustering, anomaly detection, evaluation, and leakage controls.

Each check returns {"area", "check", "passed", "detail"}. Association supports are re-counted directly in the warehouse with SQL.
"""
import re

import numpy as np
import pandas as pd

from analytics.run import split_statements

from . import config as C
from .anomaly import detect

_SQL = None


def _sql(name):
    global _SQL
    if _SQL is None:
        _SQL = dict(split_statements((C.MINING_DIR / "validation.sql").read_text(encoding="utf-8")))
    return _SQL[name]


def _chk(area, check, passed, detail=""):
    return {"area": area, "check": check, "passed": bool(passed), "detail": str(detail)}


MED_ID = re.compile(r"\[(MED\d+)\]")


def validate_association(rules, itemsets, summary, conn):
    out = []
    tx = conn.exec_driver_sql(_sql("transaction_count")).fetchone()
    out.append(_chk("association", "transaction count equals the warehouse distinct transactions", summary["transactions"] == tx[0] == tx[1],
                    f"mined {summary['transactions']}, warehouse {tx[0]}"))
    n_med = len(conn.exec_driver_sql(_sql("medicine_ids")).fetchall())
    out.append(_chk("association", "unique medicines equal the warehouse medicine count", summary["unique_medicines"] == n_med, f"{summary['unique_medicines']} vs {n_med}"))
    n = summary["transactions"]
    out.append(_chk("association", "no rule has lift <= 0 (all above the configured minimum)", bool((rules["lift"] > C.ASSOCIATION["min_lift"]).all()), f"min lift {rules['lift'].min():.2f}"))
    selfrule = [(a, c) for a, c in zip(rules["antecedent"], rules["consequent"]) if set(MED_ID.findall(a)) & set(MED_ID.findall(c))]
    out.append(_chk("association", "no self-rules (antecedent and consequent share a medicine)", not selfrule, f"{len(selfrule)} found"))
    dup = rules.duplicated(["antecedent", "consequent"]).sum()
    out.append(_chk("association", "no duplicated (antecedent, consequent) rule", dup == 0, f"{dup} duplicates"))
    ok_counts = ((rules["support_count"] > 0) & (rules["support_count"] <= rules[["antecedent_support_count", "consequent_support_count"]].min(axis=1))).all()
    out.append(_chk("association", "support counts valid (0 < count <= each side's count)", ok_counts))
    out.append(_chk("association", "support = support_count / transactions", bool((np.abs(rules["support"] - rules["support_count"] / n) < 2e-6).all())))
    conf = rules["support_count"] / rules["antecedent_support_count"]
    out.append(_chk("association", "confidence = support_count / antecedent count", bool((np.abs(rules["confidence"] - conf) < 1e-5).all())))
    lift = conf / (rules["consequent_support_count"] / n)
    out.append(_chk("association", "lift = confidence / consequent support", bool((np.abs(rules["lift"] / lift - 1) < 1e-4).all())))
    out.append(_chk("association", "metrics finite (conviction may be missing only when confidence = 1)",
                    bool(np.isfinite(rules[["support", "confidence", "lift", "leverage"]].to_numpy()).all())))
    # independent recount in the warehouse for every rule
    bad = []
    for a, c, cnt, ac, cc in zip(rules["antecedent"], rules["consequent"], rules["support_count"], rules["antecedent_support_count"], rules["consequent_support_count"]):
        ids = MED_ID.findall(a) + MED_ID.findall(c)
        both = conn.exec_driver_sql(_sql("itemset_support"), (ids, len(ids))).scalar()
        a_only = conn.exec_driver_sql(_sql("itemset_support"), (MED_ID.findall(a), len(MED_ID.findall(a)))).scalar()
        c_only = conn.exec_driver_sql(_sql("itemset_support"), (MED_ID.findall(c), len(MED_ID.findall(c)))).scalar()
        if (both, a_only, c_only) != (cnt, ac, cc):
            bad.append((a, c, both, cnt))
    out.append(_chk("association", f"all {len(rules)} rules' counts re-counted in the warehouse with SQL", not bad, f"{len(bad)} mismatches"))
    fi1 = itemsets[itemsets["itemset_size"] == 1]
    out.append(_chk("association", "frequent itemsets respect the minimum support count", bool((itemsets["support_count"] >= summary["min_support_transactions"]).all()),
                    f"min count {int(itemsets['support_count'].min())}"))
    return out


def validate_clusters(clusters, summary, projection, feature_cols, n_expected):
    out = []
    out.append(_chk("clustering", f"{n_expected} medicines represented", len(clusters) == n_expected, len(clusters)))
    out.append(_chk("clustering", "every medicine assigned exactly once", clusters["medicine_id"].is_unique and clusters["cluster_id"].notna().all()))
    out.append(_chk("clustering", "cluster counts sum to the medicine count", int(summary["medicine_count"].sum()) == n_expected and
                    (clusters["cluster_id"].value_counts().sort_index().to_numpy() == summary.sort_values("cluster_id")["medicine_count"].to_numpy()).all()))
    out.append(_chk("clustering", "no NaN in the final feature matrix", not clusters[feature_cols].isna().any().any()))
    out.append(_chk("clustering", "feature matrix finite", bool(np.isfinite(clusters[feature_cols].to_numpy(dtype=float)).all())))
    out.append(_chk("clustering", "projection covers every medicine with finite coordinates", len(projection) == n_expected and bool(np.isfinite(projection[["pc1", "pc2"]].to_numpy()).all())))
    return out


def _causality(cube, lots):
    """Recompute features from data truncated at day D: the values at D must match the full-data computation."""
    rng = np.random.default_rng(C.RANDOM_STATE)
    T, B, M = cube["units"].shape
    cols = rng.choice(B * M, size=40, replace=False)
    u = cube["units"].reshape(T, B * M)[:, cols]
    inv = cube["inventory"].reshape(T, B * M)[:, cols]
    full = detect.sales_features(u, inv)
    feats = ["z7", "zd", "baseline_median_7d", "units_vs_rolling_median", "units_vs_rolling_mean", "rolling_28d_units", "inventory_vs_prior_mean", "stockout_run_days", "units_7d"]
    days = sorted(rng.choice(np.arange(C.ANOMALY["burn_in_days"], T), size=8, replace=False).tolist())
    bad = []
    for t in days:
        part = detect.sales_features(u[:t + 1], inv[:t + 1])
        for f in feats:
            if not np.allclose(part[f][t], full[f][t], equal_nan=True, rtol=1e-9, atol=1e-9):
                bad.append((f, t))
    # purchase features: the lot's features must not change when later lots are removed
    pf = detect.purchase_features(lots, {k: i for i, k in enumerate(cube["dates"]["date_key"])}).set_index("batch_key")
    multi = lots.groupby("medicine_key").size()
    pbad = 0
    checked = 0
    for med in rng.choice(multi[multi >= 15].index.to_numpy(), size=6, replace=False):
        g = lots[lots["medicine_key"] == med].sort_values(["date_key", "batch_key"]).reset_index(drop=True)
        for i in (C.ANOMALY["purchase_baseline_lots"] + 1, len(g) // 2, len(g) - 1):
            part = detect.purchase_features(g.iloc[:i + 1], {k: j for j, k in enumerate(cube["dates"]["date_key"])}).set_index("batch_key")
            b = g["batch_key"].iloc[i]
            for f in ("qty_z", "gap_z", "cost_z", "qty_ratio", "gap_ratio"):
                checked += 1
                if not np.isclose(part.loc[b, f], pf.loc[b, f], equal_nan=True):
                    pbad += 1
    return bad, len(days) * len(feats), pbad, checked


def validate_anomalies(anomalies, cube, lots, conn):
    out = []
    first, last = conn.exec_driver_sql(_sql("date_range")).fetchone()
    d = anomalies["date"].astype(str)
    out.append(_chk("anomaly", "dates within the warehouse date range", bool(((d >= first) & (d <= last)).all()), f"{first}..{last}"))
    med_ids = {r[0] for r in conn.exec_driver_sql(_sql("medicine_ids")).fetchall()}
    br_ids = {r[0] for r in conn.exec_driver_sql(_sql("branch_ids")).fetchall()} | {"ALL"}
    out.append(_chk("anomaly", "medicine ids are valid warehouse ids", set(anomalies["medicine_id"]) <= med_ids))
    out.append(_chk("anomaly", "branch ids are valid (or ALL for medicine-level and purchase-lot rows)", set(anomalies["branch_id"]) <= br_ids))
    iso, z = anomalies["isolation_score"], anomalies["robust_z_score"]
    out.append(_chk("anomaly", "isolation scores finite wherever defined; none infinite", bool(not np.isinf(iso.dropna()).any() and iso[anomalies["is_isolation_anomaly"]].notna().all())))
    out.append(_chk("anomaly", "robust z-scores finite (no inf)", bool(not np.isinf(z.dropna()).any())))
    sales = anomalies[anomalies["grain"] != "purchase_lot"]
    out.append(_chk("anomaly", "every sales-grain row has finite units, inventory and isolation score",
                    bool(np.isfinite(sales[["units_sold", "inventory_units", "isolation_score", "robust_z_score"]].to_numpy(dtype=float)).all())))
    out.append(_chk("anomaly", "combined flag = statistical AND isolation", bool((anomalies["combined_anomaly"] == (anomalies["is_statistical_anomaly"] & anomalies["is_isolation_anomaly"])).all())))
    out.append(_chk("anomaly", "every row is flagged by at least one detector", bool((anomalies["is_statistical_anomaly"] | anomalies["is_isolation_anomaly"]).all())))
    burn = pd.to_datetime(cube["dates"]["full_date"]).iloc[C.ANOMALY["burn_in_days"]].strftime("%Y-%m-%d")
    out.append(_chk("anomaly", "sales-grain flags only after the burn-in period (no baseline = no flag)", bool((sales["date"].astype(str) >= burn).all()), f"first flag allowed {burn}"))
    bad, n_feat, pbad, pchecked = _causality(cube, lots)
    out.append(_chk("anomaly", f"no future leakage in sales features ({n_feat} feature values recomputed from data truncated at day D)", not bad, f"{len(bad)} mismatches"))
    out.append(_chk("anomaly", f"no future leakage in purchase-lot features ({pchecked} values recomputed without later lots)", pbad == 0, f"{pbad} mismatches"))
    return out


def validate_leakage_controls():
    """Static check: the only module that references the ground truth is evaluation/evaluate.py (and the config constant)."""
    out = []
    offenders = []
    for pkg in ("features", "association", "clustering", "anomaly"):
        for f in (C.MINING_DIR / pkg).glob("*.py"):
            txt = f.read_text(encoding="utf-8")
            if "GROUND_TRUTH_PRIVATE" in txt or re.search(r"\bevaluation\b", txt.replace("evaluation/", "")):
                offenders.append(str(f.relative_to(C.PROJECT_ROOT)))
    out.append(_chk("leakage", "feature, association, clustering and anomaly code never references the ground-truth path or the evaluation module", not offenders, offenders))
    users = [str(f.relative_to(C.PROJECT_ROOT)) for f in C.MINING_DIR.rglob("*.py") if "GROUND_TRUTH_PRIVATE" in f.read_text(encoding="utf-8")]
    out.append(_chk("leakage", "GROUND_TRUTH_PRIVATE is used only by config and evaluation/evaluate.py",
                    set(users) <= {"data_mining/config.py", "data_mining/evaluation/evaluate.py", "data_mining/validation.py"}, users))
    return out


def validate_evaluation(ev, by_type):
    out = []
    ok_counts, ok_rng = True, True
    for name, s in ev["detector_sets"].items():
        ok_counts &= (s["events_detected_strict"] + s["events_missed_strict"] == s["events_total"] == ev["ground_truth_events"]
                      and s["true_positive_episodes"] + s["false_positive_episodes"] == s["episodes"])
        for k in ("precision_episode_level", "recall_event_level_strict", "recall_event_level_any_flag", "f1"):
            ok_rng &= 0.0 <= s[k] <= 1.0
    out.append(_chk("evaluation", "TP + FN = ground-truth events and TP + FP = episodes for every detector set", ok_counts))
    out.append(_chk("evaluation", "precision, recall and F1 between 0 and 1", ok_rng))
    out.append(_chk("evaluation", "ground truth was read only after anomalies.csv was written", ev["ground_truth_read_after_detection_files_written"]))
    if len(by_type):
        g = by_type[by_type["view"] == "ground_truth_event_recall"]
        sums = g.groupby("detector_set")["total"].sum()
        out.append(_chk("evaluation", "per-type event counts sum to the total for every detector set", bool((sums == ev["ground_truth_events"]).all())))
    return out
