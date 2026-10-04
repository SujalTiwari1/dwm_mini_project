"""Run the whole data-mining layer:   python -m data_mining.run

Order matters for leakage control:
    association -> clustering -> anomaly detection (anomalies.csv written) -> validation -> POST-HOC evaluation (reads the hidden ground truth)
"""
import json
import sys
import time
import warnings
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from . import config as C
from .anomaly import detect
from .association import rules as assoc
from .clustering import medicine_clusters as clus
from .evaluation import evaluate as evaluation
from .features import build_features as bf
from . import validation as V

warnings.filterwarnings("ignore")
R = C.REPORT_DIR


def _json(path, obj):
    path.write_text(json.dumps(obj, indent=2, default=lambda o: o.item() if hasattr(o, "item") else str(o)), encoding="utf-8")


def _write_association(res):
    res["frequent_itemsets"].to_csv(R / "frequent_itemsets.csv", index=False)
    res["rules"].to_csv(R / "association_rules.csv", index=False)
    _json(R / "association_summary.json", res["summary"])


def _write_clusters(res):
    res["clusters"].drop(columns=["medicine_key"]).to_csv(R / "medicine_clusters.csv", index=False)
    s = res["summary"].copy()
    s["centroid_z_scores"] = s["centroid_z_scores"].map(json.dumps)
    s.to_csv(R / "cluster_summary.csv", index=False)
    res["evaluation"].assign(selected=lambda d: d["k"] == res["selected_k"]).to_csv(R / "cluster_evaluation.csv", index=False)
    res["projection"].to_csv(R / "cluster_projection.csv", index=False)
    _json(R / "cluster_preprocessing.json", {**res["preprocessing"], "selected_k": res["selected_k"],
                                              "k_selection_rule": f"smallest K >= {C.CLUSTERING['min_k_for_selection']} with silhouette within "
                                                                  f"{C.CLUSTERING['k_parsimony_tolerance']} of the best",
                                              "random_state": C.RANDOM_STATE, "n_init": C.CLUSTERING["n_init"]})


def _anomaly_summary(anoms, infos):
    sets = {"statistical": anoms[anoms["is_statistical_anomaly"]], "isolation_forest": anoms[anoms["is_isolation_anomaly"]],
            "combined_both_methods": anoms[anoms["combined_anomaly"]], "either_method": anoms}
    out = {"grains": infos, "definitions": {
        "statistical": "robust (median/MAD) z-score on sqrt-transformed 7-day and daily demand, a stockout-run rule, and prior-history purchase checks",
        "isolation_forest": f"top {C.ANOMALY['isolation_contamination']:.1%} most isolated rows at each sales grain ({C.ANOMALY['purchase_isolation_contamination']:.0%} of purchase lots)",
        "combined": "flagged by BOTH methods", "either": "flagged by at least one method (the rows of anomalies.csv)",
        "robust_z_score": "7-day level z for sales rows, per-branch lot-size z for purchase-lot rows", "episode": f"flags of one series within {C.ANOMALY['episode_gap_days']} days"},
        "parameters": C.ANOMALY, "random_state": C.RANDOM_STATE, "detector_sets": {}}
    for name, d in sets.items():
        ep = detect.build_episodes(d)
        out["detector_sets"][name] = {
            "flagged_rows": int(len(d)), "episodes": int(len(ep)), "distinct_medicines": int(d["medicine_id"].nunique()),
            "rows_by_grain_and_type": {f"{g}/{t}": int(n) for (g, t), n in d.groupby(["grain", "anomaly_type"]).size().items()},
            "episodes_by_grain_and_type": {f"{g}/{t}": int(n) for (g, t), n in ep.groupby(["grain", "anomaly_type"]).size().items()} if len(ep) else {}}
    return out


def _md(run, assoc_res, clus_res, anom_sum, ev, val):
    a, k = assoc_res["summary"], clus_res
    prep = k["preprocessing"]
    lines = ["# MedStock Data Mining Results", "",
             "> Synthetic data. Associations describe transaction-level co-occurrence, clusters describe observed business behaviour, and anomaly flags are statements about the specified detectors, not proof of anything.",
             "", "## 1. Association Rules", "", "### Method",
             "Apriori (mlxtend) over transaction baskets. A basket is the set of distinct medicines in one `transaction_id` (the item is the medicine, not the batch). "
             "Because baskets with one medicine cannot contain a pair, Apriori runs on the multi-medicine baskets with an absolute-count threshold, and singleton supports come from all transactions, so every metric is exact.",
             "", "### Parameters",
             f"- minimum support {a['min_support']} ({a['min_support_transactions']} of {a['transactions']:,} transactions), minimum confidence {a['min_confidence']}, lift > {a['min_lift']}, itemsets up to {a['max_itemset_len']} medicines",
             "- support choice (rules found at each threshold):", "", "| min support | min transactions | frequent itemsets | pairs | useful rules |", "|---|---|---|---|---|"]
    for r in a["support_sensitivity"]:
        lines.append(f"| {r['min_support']} | {r['min_transactions']} | {r['frequent_itemsets']} | {r['size_2']} | {r['useful_rules']} |")
    lines += ["", f"The useful-rule count stops growing at {a['min_support']}: lower thresholds add frequent pairs but no further rules with confidence >= {a['min_confidence']} and lift > 1, "
                 f"while a higher threshold loses rules.", "", "### Results",
              f"- {a['transactions']:,} transactions, {a['unique_medicines']} medicines ({a['multi_item_transactions']:,} transactions contain two or more medicines)",
              f"- {a['frequent_itemsets']} frequent itemsets {a['frequent_itemsets_by_size']}, {a['rules_generated_before_filter']} rules generated, {a['useful_rules_after_filter']} useful rules "
              f"covering {a['unique_rule_itemsets']} distinct medicine pairs ({a['rules_with_reverse_direction']} rules have the opposite direction as well)",
              "", "### Top Patterns (one direction per pair, ranked by lift)", "", "| antecedent | consequent | support count | confidence | lift |", "|---|---|---|---|---|"]
    for r in a["top_rules_one_direction_per_itemset"][:10]:
        lines.append(f"| {r['antecedent']} | {r['consequent']} | {r['support_count']} | {r['confidence']} | {r['lift']} |")
    lines += ["", "### Interpretation",
              "Read `A -> B` as: *transactions containing A were more likely to also contain B*. Lift is the ratio of the observed co-occurrence to the co-occurrence expected if the two medicines were independent. "
              "Reverse rules of the same pair share support and lift but have different confidence. The patterns are transaction-level co-occurrence; they are not causal and say nothing about patients.", "",
              "### Limitations",
              "- With 500 medicines the baseline co-occurrence is very low, so lifts are large (tens to hundreds); the absolute support is small (about 0.07% to 0.9% of transactions).",
              "- Only pairs reached the thresholds: no frequent itemset with three medicines exists at this support.",
              "- Confidence depends on how common the antecedent is. Rely on support count, confidence and lift together.", "",
              "## 2. Medicine Clustering", "", "### Features",
              f"{len(prep['selected'])} features describing behaviour over the 24 months: {', '.join(prep['selected'])}. All come from SQL aggregation over the warehouse and the existing analytics views.",
              "", "### Preprocessing",
              f"- candidates considered: {len(prep['candidates'])}; log1p applied to non-negative features with |skewness| > {C.CLUSTERING['skew_threshold']}: {', '.join(x['feature'] for x in prep['log1p'])}",
              f"- redundancy: a feature was dropped when |Spearman r| with an already kept feature exceeded {C.CLUSTERING['redundancy_threshold']}. Dropped: "
              + "; ".join(f"{d['feature']} (~{d['reason'].replace('redundant with ', '')})" for d in prep["dropped"]),
              "- missing values: " + (", ".join(f"{c}: {v['count']} filled with {v['filled_with']}" for c, v in prep["missing_values_filled"].items()) or "none"),
              "- StandardScaler, then K-Means (`n_init` 20, `random_state` 42). The demand CV and turnover were redundant with volume, so a volume-independent dispersion measure (std / sqrt(mean) of weekly demand) represents variability.",
              "", "### K Selection", "", "| K | inertia | silhouette | Calinski-Harabasz | Davies-Bouldin | smallest cluster |", "|---|---|---|---|---|---|"]
    for _, r in k["evaluation"].iterrows():
        lines.append(f"| {int(r['k'])}{' (selected)' if int(r['k']) == k['selected_k'] else ''} | {r['inertia']} | {r['silhouette']} | {r['calinski_harabasz']} | {r['davies_bouldin']} | {int(r['smallest_cluster'])} |")
    lines += ["", f"K = 2 has the highest silhouette but is a trivial split. The curve is flat for K >= 3, so the rule is the smallest K >= 3 within {C.CLUSTERING['k_parsimony_tolerance']} of the best silhouette: K = {k['selected_k']} "
                  f"(silhouette {k['silhouette']:.3f}).", "", "### Cluster Profiles", "",
              "| cluster | label (derived from centroid) | medicines | share of units | avg units | avg revenue | avg stockout rate | avg days of inventory |", "|---|---|---|---|---|---|---|---|"]
    for _, r in k["summary"].iterrows():
        lines.append(f"| {r['cluster_id']} | {r['label']} | {r['medicine_count']} | {r['share_of_units_pct']}% | {r['avg_units_sold']:.0f} | {r['avg_revenue']:.0f} | {r['avg_stockout_rate']:.4f} | {r['avg_days_of_inventory']:.0f} |")
    lines += ["", "### Interpretation",
              "Labels are generated from each centroid's standardised distance on the selected features (|z| >= 0.5), not assigned beforehand. Cluster 0 is always the highest-volume segment.", "",
              "### Limitations",
              f"- Silhouette is low (about 0.2): medicines form a continuum rather than well-separated groups, so boundaries are soft. PCA explains {sum(prep['explained_variance_pc1_pc2']):.0%} of the variance in two components ({prep['explained_variance_pc1_pc2']}).",
              "- The smallest cluster is defined mainly by a zero-inflated feature (projected expiry risk) and is best read as 'medicines currently holding stock expected to expire'.",
              "- Observed demand is censored by stockouts and the data is synthetic.", "", "## 3. Anomaly Detection", "", "### Methods",
              "1. **Robust statistics.** Median/MAD modified z-scores on sqrt(x + 3/8) of demand (a variance-stabilising transform for counts): the 7-day level versus the median/MAD of the prior 56 days of 7-day levels, plus single-day spikes versus the prior 28 days; "
              "a stockout of 7 or more consecutive days; and, for purchase lots, size per delivered branch, receipt gap and unit cost versus the medicine's prior lots.",
              "2. **Isolation Forest** (200 trees, `random_state` 42) on causal features: robust z (7-day and daily), ratios to rolling median/mean, rolling 7/28-day units, inventory level and its ratio to the prior mean, stockout indicator and run length.",
              "", "### Features", "All rolling quantities for day D use observations up to D only (baselines end before D). The first 70 days are a burn-in and are never flagged. Validation recomputes the features from data truncated at D and requires identical values.",
              "", "### Results", "", "| detector set | flagged rows | episodes | distinct medicines |", "|---|---|---|---|"]
    for name, s in anom_sum["detector_sets"].items():
        lines.append(f"| {name} | {s['flagged_rows']:,} | {s['episodes']:,} | {s['distinct_medicines']} |")
    lines += ["", "### Anomaly Types",
              "A type is assigned only when the observable features support it (half the detection threshold on the relevant feature); otherwise the row is `unclassified`. Types: demand_spike, demand_drop, stockout_pattern, inventory_anomaly (unusually large purchase lot), supply_delay (unusually long gap between receipts), purchase_price_anomaly.",
              "", "Rows by grain and type (either method): " + "; ".join(f"{k_}: {v}" for k_, v in anom_sum["detector_sets"]["either_method"]["rows_by_grain_and_type"].items()), "",
              "### Evaluation (post-hoc evaluation against synthetic ground truth, NOT model input)",
              f"The hidden generator ground truth ({ev['ground_truth_events']} events: {ev['ground_truth_events_by_type']}) was read only after `anomalies.csv` was written.", "",
              "| detector set | episodes | TP episodes | FP episodes | events detected (strict) | events missed | precision (episode) | recall (strict) | recall (any flag) | F1 |", "|---|---|---|---|---|---|---|---|---|---|"]
    for name, s in ev["detector_sets"].items():
        lines.append(f"| {name} | {s['episodes']} | {s['true_positive_episodes']} | {s['false_positive_episodes']} | {s['events_detected_strict']} | {s['events_missed_strict']} | "
                     f"{s['precision_episode_level']} | {s['recall_event_level_strict']} | {s['recall_event_level_any_flag']} | {s['f1']} |")
    lines += ["", "Per-type results are in `anomaly_evaluation_by_type.csv`.", "", "### Limitations"] + [f"- {n}" for n in ev["notes"]] + [
              "- A flag means the detector marks the observation as unusual under the specified method. It does not prove that the observation is abnormal.",
              "- Observed demand is censored by stockouts, small-volume medicines are inherently noisy, and the ground truth is synthetic, so the scores describe these detectors on this dataset only.",
              "", "## 4. Overall Findings", "",
              f"- Association: {a['useful_rules_after_filter']} directional rules over {a['unique_rule_itemsets']} medicine pairs; every pair is a strong, well-supported co-occurrence (lift >= {min(r['lift'] for r in a['top_rules_one_direction_per_itemset'])}).",
              f"- Clustering: K = {k['selected_k']} segments with a soft structure (silhouette {k['silhouette']:.2f}); the high-volume segment ({int(k['summary'].iloc[0]['medicine_count'])} medicines) carries {k['summary'].iloc[0]['share_of_units_pct']}% of units.",
              f"- Anomalies: {anom_sum['detector_sets']['either_method']['flagged_rows']:,} flagged rows in {anom_sum['detector_sets']['either_method']['episodes']:,} episodes; see the evaluation table for how they relate to the planted events.",
              "", "## 5. Reproducibility", "",
              f"`random_state` = {C.RANDOM_STATE} for K-Means, PCA and Isolation Forest; all orderings are explicit. Running `python -m data_mining.run` twice gives identical reports (apart from `run_timestamp` and `runtime_seconds` in `run_summary.json`).",
              "", "## 6. Data Leakage Controls", "",
              "- The hidden ground truth is read only by `data_mining/evaluation/evaluate.py`, after detection output exists. Feature, association, clustering and anomaly code never reference it (a static check enforces this).",
              "- Rolling features are causal (validated by recomputing on truncated data). Thresholds were fixed in advance and not tuned on the ground truth.",
              f"- Validation: {val['checks']} checks, {val['failures']} failures."]
    return "\n".join(lines) + "\n"


def main() -> int:
    t0 = time.time()
    R.mkdir(parents=True, exist_ok=True)
    engine, conn = bf.open_connection()
    ref = bf.dataset_reference()
    counts = bf.warehouse_counts(conn)
    print(f"MedStock data mining | dataset {ref['generator_version']} (frozen {ref['frozen_on']}) | warehouse: {counts['transactions']:,} transactions, {counts['medicines']} medicines")

    t = time.time()
    assoc_res = assoc.mine(conn)
    _write_association(assoc_res)
    a = assoc_res["summary"]
    print(f"[1/4] association: {a['frequent_itemsets']} itemsets, {a['useful_rules_after_filter']} rules ({a['unique_rule_itemsets']} pairs)  {time.time() - t:.0f}s")

    t = time.time()
    clus_res = clus.run(conn)
    _write_clusters(clus_res)
    feat_cols = clus_res["preprocessing"]["selected"]
    print(f"[2/4] clustering: K={clus_res['selected_k']} silhouette {clus_res['silhouette']:.3f}, sizes {clus_res['summary']['medicine_count'].tolist()}  {time.time() - t:.0f}s")

    t = time.time()
    cube = bf.load_daily_cube(conn)
    lots = bf.load_purchase_lots(conn)
    anoms, infos, _ = detect.detect_all(cube, lots)
    anoms.to_csv(R / "anomalies.csv", index=False)
    anom_sum = _anomaly_summary(anoms, infos)
    _json(R / "anomaly_summary.json", anom_sum)
    detection_finished_at = time.time()
    s = anom_sum["detector_sets"]
    print(f"[3/4] anomalies: {len(anoms):,} rows | statistical {s['statistical']['flagged_rows']:,}, isolation {s['isolation_forest']['flagged_rows']:,}, "
          f"both {s['combined_both_methods']['flagged_rows']:,}  {time.time() - t:.0f}s")

    # ---- validation of everything produced WITHOUT ground truth ------------------------------
    results = []
    results += V.validate_association(assoc_res["rules"], assoc_res["frequent_itemsets"], a, conn)
    results += V.validate_clusters(clus_res["clusters"], clus_res["summary"], clus_res["projection"], feat_cols, counts["medicines"])
    results += V.validate_anomalies(pd.read_csv(R / "anomalies.csv"), cube, lots, conn)
    results += V.validate_leakage_controls()

    # ---- post-hoc evaluation: the ONLY step that touches the hidden ground truth ----------------
    t = time.time()
    ev, by_type, gt_read_at = evaluation.evaluate(conn, R / "anomalies.csv", detection_finished_at)
    _json(R / "anomaly_evaluation.json", ev)
    by_type.to_csv(R / "anomaly_evaluation_by_type.csv", index=False)
    results += V.validate_evaluation(ev, by_type)
    best = ev["detector_sets"]
    print(f"[4/4] post-hoc evaluation vs synthetic ground truth ({ev['ground_truth_events']} events)  {time.time() - t:.0f}s")
    for name, m in best.items():
        print(f"      {name:<22} precision {m['precision_episode_level']:.3f} | recall strict {m['recall_event_level_strict']:.3f} (any flag {m['recall_event_level_any_flag']:.3f}) | F1 {m['f1']:.3f} | episodes {m['episodes']}")

    failures = [r for r in results if not r["passed"]]
    _json(R / "validation_results.json", {"checks": len(results), "failures": len(failures), "results": results})
    val = {"checks": len(results), "failures": len(failures)}
    print(f"Validation: {len(results)} checks, {len(failures)} failed")
    for r in failures:
        print(f"  FAIL [{r['area']}] {r['check']}: {r['detail']}")

    (R / "mining_summary.md").write_text(_md(None, assoc_res, clus_res, anom_sum, ev, val), encoding="utf-8")
    import sklearn, mlxtend
    summary = {
        "run_timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dataset_version": f"{ref['generator_version']} (frozen {ref['frozen_on']}, seed {ref['random_seed']})",
        "warehouse_reference": {"schema": "warehouse", "transactions": int(counts["transactions"]), "medicines": int(counts["medicines"]),
                                "branches": int(counts["branches"]), "date_range": [counts["first_date"], counts["last_date"]]},
        "association_rule_count": a["useful_rules_after_filter"], "frequent_itemset_count": a["frequent_itemsets"],
        "selected_cluster_count": clus_res["selected_k"], "medicine_count_clustered": int(len(clus_res["clusters"])),
        "anomaly_count": s["either_method"]["flagged_rows"], "statistical_anomaly_count": s["statistical"]["flagged_rows"],
        "isolation_anomaly_count": s["isolation_forest"]["flagged_rows"], "combined_anomaly_count": s["combined_both_methods"]["flagged_rows"],
        "anomaly_episode_counts": {k_: v["episodes"] for k_, v in s.items()},
        "evaluation_metrics": {"label": ev["label"], **{k_: {m: v[m] for m in ("precision_episode_level", "recall_event_level_strict", "recall_event_level_any_flag", "f1")}
                                                          for k_, v in ev["detector_sets"].items()}},
        "validation": val, "random_state": C.RANDOM_STATE,
        "libraries": {"scikit-learn": sklearn.__version__, "mlxtend": mlxtend.__version__, "pandas": pd.__version__, "numpy": np.__version__},
        "runtime_seconds": round(time.time() - t0, 1),
    }
    _json(R / "run_summary.json", summary)
    conn.close()
    engine.dispose()
    print(f"Done in {summary['runtime_seconds']}s. Reports in {R}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
