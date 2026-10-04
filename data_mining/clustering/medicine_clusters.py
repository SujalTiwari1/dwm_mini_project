"""Medicine clustering: K-Means on standardised behaviour features, with documented preprocessing and a K-selection table."""
import numpy as np
import pandas as pd
from scipy.stats import skew, spearmanr
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import calinski_harabasz_score, davies_bouldin_score, silhouette_score
from sklearn.preprocessing import StandardScaler

from .. import config as C
from ..features.build_features import load_medicine_features

ID_COLS = ["medicine_key", "medicine_id", "medicine_name", "category"]


def prepare_features(df: pd.DataFrame):
    """Return (X_raw selected, transformed frame, preprocessing report)."""
    cfg = C.CLUSTERING
    cand = [c for c in cfg["candidate_features"] if c in df.columns]
    raw = df[cand].copy()
    report = {"candidates": cand, "missing_values_filled": {}, "log1p": [], "dropped": []}

    for c in cand:
        n_missing = int(raw[c].isna().sum())
        if n_missing:
            # days_of_inventory is NULL when there was no recent demand: treat as "a year or more of cover", capped
            fill = cfg["days_of_inventory_cap"] if c == "days_of_inventory" else 0.0
            raw[c] = raw[c].fillna(fill)
            report["missing_values_filled"][c] = {"count": n_missing, "filled_with": fill}
    raw["days_of_inventory"] = raw["days_of_inventory"].clip(upper=cfg["days_of_inventory_cap"]) if "days_of_inventory" in raw else None

    trans = raw.copy()
    for c in cand:
        nonneg = (raw[c] >= 0).all()
        sk = float(skew(raw[c])) if raw[c].std() > 0 else 0.0
        if nonneg and abs(sk) > cfg["skew_threshold"]:
            trans[c] = np.log1p(raw[c])
            report["log1p"].append({"feature": c, "skewness_before": round(sk, 2), "skewness_after": round(float(skew(trans[c])), 2)})

    # drop constant features, then redundant ones (|Spearman| above threshold with an already kept feature; priority = config order)
    kept = []
    for c in cand:
        if trans[c].std() == 0:
            report["dropped"].append({"feature": c, "reason": "constant"})
            continue
        partner, rho = None, 0.0
        for k in kept:
            r = abs(spearmanr(trans[c], trans[k]).statistic)
            if r > cfg["redundancy_threshold"] and r > rho:
                partner, rho = k, r
        if partner:
            report["dropped"].append({"feature": c, "reason": f"redundant with {partner}", "abs_spearman": round(float(rho), 3)})
        else:
            kept.append(c)
    report["selected"] = kept
    corr = pd.DataFrame(spearmanr(trans[kept]).statistic, index=kept, columns=kept) if len(kept) > 2 else pd.DataFrame()
    report["max_abs_correlation_among_selected"] = round(float(np.abs(corr.values[~np.eye(len(kept), dtype=bool)]).max()), 3) if len(kept) > 2 else None
    return raw[kept], trans[kept], report


def evaluate_k(Z):
    cfg = C.CLUSTERING
    rows = []
    for k in cfg["k_range"]:
        km = KMeans(n_clusters=k, n_init=cfg["n_init"], random_state=C.RANDOM_STATE).fit(Z)
        sizes = np.bincount(km.labels_, minlength=k)
        rows.append({"k": k, "inertia": round(float(km.inertia_), 3), "silhouette": round(float(silhouette_score(Z, km.labels_)), 4),
                     "calinski_harabasz": round(float(calinski_harabasz_score(Z, km.labels_)), 2),
                     "davies_bouldin": round(float(davies_bouldin_score(Z, km.labels_)), 4),
                     "smallest_cluster": int(sizes.min()), "largest_cluster": int(sizes.max())})
    return pd.DataFrame(rows)


def choose_k(ev: pd.DataFrame):
    """Parsimonious K. K = 2 is reported but is a trivial high/low split, so selection is over K >= min_k_for_selection.
    The silhouette curve is flat, so rather than the arbitrary maximum we take the smallest K whose silhouette is within
    k_parsimony_tolerance of the best one (fewer, more interpretable segments)."""
    cfg = C.CLUSTERING
    pool = ev[ev["k"] >= cfg["min_k_for_selection"]]
    best = pool["silhouette"].max()
    return int(pool[pool["silhouette"] >= best - cfg["k_parsimony_tolerance"]]["k"].min())


def describe_clusters(centroid_z: pd.DataFrame) -> dict:
    """Derive a plain-language label per cluster from its standardised centroid (no pre-assigned labels)."""
    def tier(v, hi, lo, hi_txt, lo_txt):
        return hi_txt if v >= hi else lo_txt if v <= lo else None
    labels = {}
    for cid, z in centroid_z.iterrows():
        parts = []
        for feat, hi_txt, lo_txt in (("total_units_sold", "high-volume", "low-volume"), ("total_revenue", "high-revenue", "low-revenue"),
                                     ("inventory_turnover", "fast-turnover", "slow-turnover"), ("weekly_demand_cv", "variable demand", "stable demand"),
                                     ("stockout_rate", "frequent stockouts", "rare stockouts"), ("days_of_inventory", "long stock cover", "short stock cover"),
                                     ("avg_selling_price", "high-price", "low-price"), ("expired_value", "expiry write-offs", None),
                                     ("expiry_risk_value", "expiry risk", None), ("avg_purchase_cost", "high unit cost", "low unit cost")):
            if feat in z.index:
                t = tier(z[feat], 0.5, -0.5, hi_txt, lo_txt)
                if t:
                    parts.append((abs(z[feat]), t))
        parts.sort(reverse=True)
        labels[int(cid)] = ", ".join(t for _, t in parts[:4]) if parts else "average on all selected features"
    return labels


def run(conn):
    df = load_medicine_features(conn)
    raw_sel, trans_sel, prep = prepare_features(df)
    scaler = StandardScaler()
    Z = scaler.fit_transform(trans_sel)
    if not np.isfinite(Z).all():
        raise ValueError("non-finite values in the standardised feature matrix")
    ev = evaluate_k(Z)
    k = choose_k(ev)
    km = KMeans(n_clusters=k, n_init=C.CLUSTERING["n_init"], random_state=C.RANDOM_STATE).fit(Z)
    # stable cluster ids: order clusters by descending mean total_units_sold so id 0 is always the highest-volume segment
    order = pd.Series(raw_sel["total_units_sold"].groupby(km.labels_).mean()).sort_values(ascending=False).index
    remap = {old: new for new, old in enumerate(order)}
    labels = np.array([remap[l] for l in km.labels_])
    centroid_z = pd.DataFrame(km.cluster_centers_, columns=trans_sel.columns).iloc[order].reset_index(drop=True)
    names = describe_clusters(centroid_z)

    pca = PCA(n_components=2, random_state=C.RANDOM_STATE).fit(Z)
    proj = pca.transform(Z)
    clusters = df[ID_COLS[1:]].copy()
    clusters.insert(0, "medicine_key", df["medicine_key"])
    clusters["cluster_id"] = labels
    clusters["cluster_label"] = clusters["cluster_id"].map(names)
    clusters = pd.concat([clusters, raw_sel.round(4).reset_index(drop=True)], axis=1).rename(columns={"category": "category"})
    projection = pd.DataFrame({"medicine_id": df["medicine_id"], "medicine_name": df["medicine_name"], "cluster_id": labels,
                               "pc1": proj[:, 0].round(5), "pc2": proj[:, 1].round(5)})

    full = df.assign(cluster_id=labels)
    summary = full.groupby("cluster_id").agg(
        medicine_count=("medicine_id", "size"), avg_units_sold=("total_units_sold", "mean"), avg_revenue=("total_revenue", "mean"),
        avg_inventory=("avg_inventory_units", "mean"), avg_turnover=("inventory_turnover", "mean"), avg_stockout_rate=("stockout_rate", "mean"),
        avg_expiry_risk=("expiry_risk_value", "mean"), avg_demand_cv=("weekly_demand_cv", "mean"),
        avg_expired_value=("expired_value", "mean"), avg_days_of_inventory=("days_of_inventory", "mean"), avg_price=("avg_selling_price", "mean"),
    ).round(4).reset_index()
    summary["label"] = summary["cluster_id"].map(names)
    summary["share_of_units_pct"] = (full.groupby("cluster_id")["total_units_sold"].sum() / full["total_units_sold"].sum() * 100).round(2).values
    top_cat = full.groupby(["cluster_id", "category"]).size().reset_index(name="n").sort_values(["cluster_id", "n", "category"], ascending=[True, False, True]).groupby("cluster_id").head(3)
    summary["top_categories"] = summary["cluster_id"].map(top_cat.groupby("cluster_id").apply(lambda g: "; ".join(f"{c} ({n})" for c, n in zip(g["category"], g["n"]))))
    summary["centroid_z_scores"] = summary["cluster_id"].map(lambda c: {f: round(float(v), 2) for f, v in centroid_z.loc[c].items()})
    prep.update({"scaler": "StandardScaler", "explained_variance_pc1_pc2": [round(float(v), 4) for v in pca.explained_variance_ratio_]})
    return {"clusters": clusters, "summary": summary, "evaluation": ev, "projection": projection, "selected_k": k, "preprocessing": prep,
            "labels": names, "silhouette": float(ev.loc[ev["k"] == k, "silhouette"].iloc[0]), "features_frame": df}
