"""
Step 8 - Size curves: dynamic store clusters, attribute-aware curves, frequent updates.

Variants scored on the test weeks against true demand by size (same total units per style-store,
split by each curve; units landing in the wrong size are counted):
  A  chain-wide flat curve (today)
  B  store-master cluster x category, estimated once at season start (FY2025 data)
  C  store-master cluster x category, estimated on all history to week 97 (v1 approach, EM-completed)
  D  dynamic clusters: stores re-clustered (k-means) on their recent size mix, trailing 26 weeks
  E  D + attribute-aware: cluster x category x fit, shrunk towards cluster x category (empirical Bayes)
Also simulates the update cadence (once a season vs every 8 weeks) over FY2026.
"""
import json, os
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from scipy.optimize import linear_sum_assignment
import paths, sim
from governance_lib import write_json, audit_log

Z = len(sim.SIZES)
sz = pd.read_csv(os.path.join(paths.SPL, "size_demand_est.csv.gz"))
styles = pd.read_csv(os.path.join(paths.RAW, "style_master.csv"))
stores = pd.read_csv(os.path.join(paths.RAW, "store_master.csv"))
sz = sz.merge(styles[["style_id", "category", "fit"]], on="style_id").merge(stores[["store_id", "cluster"]], on="store_id")
sz["z"] = sz["size"].map({s: i for i, s in enumerate(sim.SIZES)})
truth = pd.read_csv(os.path.join(paths.GT, "true_demand.csv.gz"))
truth = truth[truth.week_index >= 98].groupby(["style_id", "store_id", "size"], as_index=False).true_mean_demand.sum()
truth = truth.merge(styles[["style_id", "category", "fit"]], on="style_id")
truth["z"] = truth["size"].map({s: i for i, s in enumerate(sim.SIZES)})
PRIOR = 1500.0     # units of evidence at which a fit-specific curve gets half weight


def curves(df, keys):
    t = df.groupby(keys + ["z"]).dhat.sum().unstack(fill_value=0.0)
    return t.div(t.sum(1), axis=0), t.sum(1)


def dynamic_clusters(df, k=3):
    chain = df.groupby(["category", "z"]).dhat.sum().unstack(fill_value=0); chain = chain.div(chain.sum(1), axis=0)
    st = df.groupby(["store_id", "category", "z"]).dhat.sum().unstack(fill_value=0)
    st = st.div(st.sum(1), axis=0)
    idx = chain.reindex(st.index.get_level_values("category")).values
    rel = pd.DataFrame(st.values / idx, index=st.index).groupby(level="store_id").mean()
    km = KMeans(k, n_init=20, random_state=0).fit(np.log(rel.values))
    lab = pd.Series(km.labels_, index=rel.index)
    # name clusters after the closest store-master cluster (Hungarian match on members)
    master = stores.set_index("store_id").cluster.reindex(rel.index)
    names = sorted(master.unique())
    cost = np.array([[-((lab == i) & (master == n)).sum() for n in names] for i in range(k)])
    r, c = linear_sum_assignment(cost)
    return lab.map({i: names[j] for i, j in zip(r, c)})


def apply(curve_fn, t):
    alloc = np.zeros(len(t))
    tot = t.groupby(["style_id", "store_id"]).true_mean_demand.transform("sum").values
    for i, row in enumerate(t.itertuples(index=False)):
        alloc[i] = tot[i] * curve_fn(row)
    lost = np.maximum(t.true_mean_demand.values - alloc, 0).sum()
    return float(lost / t.true_mean_demand.sum())


def build_variants(hist_all, hist_recent, season_start, t):
    chain = sim.CHAIN_CURVE
    cB, _ = curves(season_start, ["cluster", "category"])
    cC, _ = curves(hist_all, ["cluster", "category"])
    dyn = dynamic_clusters(hist_recent)
    hr = hist_recent.assign(dcluster=hist_recent.store_id.map(dyn))
    cD, _ = curves(hr, ["dcluster", "category"])
    cE_raw, nE = curves(hr, ["dcluster", "category", "fit"])
    t = t.assign(dcluster=t.store_id.map(dyn), cluster=t.store_id.map(stores.set_index("store_id").cluster))

    def e_curve(r):
        parent = cD.loc[(r.dcluster, r.category)].values
        key = (r.dcluster, r.category, r.fit)
        if key not in cE_raw.index:
            return parent[r.z]
        w = nE[key] / (nE[key] + PRIOR)
        v = w * cE_raw.loc[key].values + (1 - w) * parent
        return (v / v.sum())[r.z]

    fns = {"A_chain_flat": lambda r: chain[r.z],
           "B_master_cluster_season_start": lambda r: cB.loc[(r.cluster, r.category)].values[r.z],
           "C_master_cluster_all_history": lambda r: cC.loc[(r.cluster, r.category)].values[r.z],
           "D_dynamic_clusters": lambda r: cD.loc[(r.dcluster, r.category)].values[r.z],
           "E_dynamic_plus_fit": e_curve}
    return fns, t, dyn, cD, cE_raw, nE


hist_all = sz[sz.week_index <= 97]
recent = sz[sz.week_index.between(72, 97)]
season_start = sz[sz.week_index <= 52]
fns, t, dyn, cD, cE, nE = build_variants(hist_all, recent, season_start, truth)
scores = {k: round(apply(f, t), 4) for k, f in fns.items()}
moved = [dict(store_id=s, master_cluster=stores.set_index("store_id").cluster[s], current_cluster=c)
         for s, c in dyn.items() if c != stores.set_index("store_id").cluster[s]]
truth_moved = pd.read_csv(os.path.join(paths.GT, "store_truth.csv"))
truth_moved = sorted(truth_moved[truth_moved.cluster != truth_moved.cluster_fy2026].store_id)

# update cadence over FY2026: once at season start vs every 8 weeks (trailing 26 weeks)
gt_all = pd.read_csv(os.path.join(paths.GT, "true_demand.csv.gz"))
cad = []
for start in range(60, 98, 8):
    blk = gt_all[gt_all.week_index.between(start, min(start + 7, 97))].groupby(["style_id", "store_id", "size"], as_index=False).true_mean_demand.sum()
    blk = blk.merge(styles[["style_id", "category", "fit"]], on="style_id"); blk["z"] = blk["size"].map({s: i for i, s in enumerate(sim.SIZES)})
    f_season, tb, *_ = build_variants(sz[sz.week_index <= 52], sz[sz.week_index.between(27, 52)], season_start, blk)
    f_roll, tb2, *_ = build_variants(sz[sz.week_index < start], sz[sz.week_index.between(start - 26, start - 1)], season_start, blk)
    cad.append(dict(weeks=f"{start}-{min(start + 7, 97)}", once_a_season=round(apply(f_season["E_dynamic_plus_fit"], tb), 4),
                    every_8_weeks=round(apply(f_roll["E_dynamic_plus_fit"], tb2), 4)))

out = dict(metric="share of units allocated to the wrong size (lower is better), test weeks 98-104",
           variants=scores, best=min(scores, key=scores.get),
           reduction_vs_chain=round(1 - min(scores.values()) / scores["A_chain_flat"], 4),
           reduction_vs_v1=round(1 - scores["E_dynamic_plus_fit"] / scores["C_master_cluster_all_history"], 4),
           stores_reassigned=moved, stores_that_truly_changed=truth_moved,
           update_cadence=dict(blocks=cad, once_a_season_mean=round(np.mean([c["once_a_season"] for c in cad]), 4),
                               every_8_weeks_mean=round(np.mean([c["every_8_weeks"] for c in cad]), 4)),
           curves={"cluster_category": {f"{a}|{b}": [round(x, 4) for x in v] for (a, b), v in cD.iterrows()},
                   "chain": [round(float(x), 4) for x in sim.CHAIN_CURVE], "sizes": sim.SIZES},
           fit_curves={f"{a}|{b}|{c}": dict(curve=[round(x, 4) for x in v], units=round(float(nE[(a, b, c)]), 0))
                       for (a, b, c), v in cE.iterrows()})
write_json("size_curves.json", out)
# lookup used by markdown, allocation and the planner: style x store -> size shares (variant E)
look = []
for s in styles.itertuples():
    for st in stores.itertuples():
        cl = dyn[st.store_id]
        parent = cD.loc[(cl, s.category)].values
        key = (cl, s.category, s.fit)
        v = parent if key not in cE.index else (nE[key] / (nE[key] + PRIOR)) * cE.loc[key].values + (PRIOR / (nE[key] + PRIOR)) * parent
        v = v / v.sum()
        look.append(dict(style_id=s.style_id, store_id=st.store_id, cluster=cl, **{z: round(float(x), 5) for z, x in zip(sim.SIZES, v)}))
pd.DataFrame(look).to_csv(paths.res("size_curve_lookup.csv"), index=False)
audit_log("size_curves_published", best=out["best"], stores_reassigned=[m["store_id"] for m in moved])
print(json.dumps({k: v for k, v in out.items() if k not in ("curves", "fit_curves")}, indent=2))
