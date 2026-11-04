"""
Step 11 - Allocation and inter-store transfer recommendations.

A. Allocation split: a fixed number of units per style for the next four weeks (98-101) is split across
   stores and sizes by (i) today's practice - each store's recent sales share x the chain size curve -
   or (ii) the forecast x the learned size curves. Same total units; scored on fill rate against true demand.
B. Inter-store transfers at the start of clearance: stores with more stock than forecast demand send units
   (within the same region, at least 3 units, R6 per unit) to stores that will run short. Scored by replaying
   the actual markdown path on true demand with and without transfers.
"""
import json, os
import numpy as np
import pandas as pd
import paths, sim
from governance_lib import write_json, audit_log

TRANSFER_COST, MIN_LOT = 6.0, 3
sim.load_external(os.path.join(paths.GT, "external_truth.npz"))
te = pd.read_csv(paths.res("forecast_test_predictions.csv"))
look = pd.read_csv(paths.res("size_curve_lookup.csv")).set_index(["style_id", "store_id"])
stores = pd.read_csv(os.path.join(paths.RAW, "store_master.csv")).set_index("store_id")
st_truth = pd.read_csv(os.path.join(paths.GT, "store_truth.csv")).to_dict("records")
sty_truth = {s["style_id"]: s for s in pd.read_csv(os.path.join(paths.GT, "style_truth_FY2026.csv")).to_dict("records")}
sales = pd.read_csv(os.path.join(paths.RAW, "sales_weekly.csv.gz"), usecols=["week_index", "store_id", "style_id", "size", "sales_units", "stock_on_hand_start", "discount"])
truth = pd.read_csv(os.path.join(paths.GT, "true_demand.csv.gz"))
Z, sizes = len(sim.SIZES), sim.SIZES
store_ids = [s["store_id"] for s in st_truth]

# ---------------- A. allocation split for weeks 98-101
win = truth[truth.week_index.between(98, 101)].groupby(["style_id", "store_id", "size"]).true_mean_demand.sum()
fc = te[te.week_index.between(98, 101)].groupby(["style_id", "store_id"]).pred_final.sum()
recent = sales[sales.week_index.between(94, 97)].groupby(["style_id", "store_id"]).sales_units.sum()
fill = {"current_practice": [0.0, 0.0], "forecast_and_size_curves": [0.0, 0.0]}
for sid in te.style_id.unique():
    total = fc.loc[sid].sum()
    rs = recent.reindex(pd.MultiIndex.from_product([[sid], store_ids])).fillna(0).values
    rs = rs / rs.sum() if rs.sum() > 0 else np.full(len(store_ids), 1 / len(store_ids))
    fs = fc.reindex(pd.MultiIndex.from_product([[sid], store_ids])).fillna(0).values; fs = fs / max(fs.sum(), 1e-9)
    dem = win.reindex(pd.MultiIndex.from_product([[sid], store_ids, sizes])).fillna(0).values.reshape(len(store_ids), Z)
    alloc_cur = total * rs[:, None] * sim.CHAIN_CURVE[None, :]
    alloc_new = total * fs[:, None] * look.loc[[(sid, s) for s in store_ids], sizes].values
    for k, al in (("current_practice", alloc_cur), ("forecast_and_size_curves", alloc_new)):
        fill[k][0] += np.minimum(np.round(al), dem).sum(); fill[k][1] += dem.sum()
alloc = {k: round(v[0] / v[1], 4) for k, v in fill.items()}

# ---------------- B. transfers at clearance start
start = sales[sales.week_index == 98]
path = sales[sales.week_index.between(98, 104)].groupby(["style_id", "week_index"]).discount.first().unstack()
fc_cl = te.groupby(["style_id", "store_id"]).pred_final.sum()
moves, before, after = [], dict(units=0.0, revenue=0.0), dict(units=0.0, revenue=0.0, cost=0.0)
for sid, grp in start.groupby("style_id"):
    stock = grp.pivot(index="store_id", columns="size", values="stock_on_hand_start").reindex(index=store_ids, columns=sizes).fillna(0).values
    need = fc_cl.reindex(pd.MultiIndex.from_product([[sid], store_ids])).fillna(0).values[:, None] * look.loc[[(sid, s) for s in store_ids], sizes].values
    new = stock.copy()
    for region in stores.region.unique():
        idx = [i for i, s in enumerate(store_ids) if stores.loc[s, "region"] == region]
        for z in range(Z):
            excess = {i: new[i, z] - np.ceil(need[i, z] * 1.1) for i in idx}
            short = {i: np.floor(need[i, z] * 0.9) - new[i, z] for i in idx}
            givers = sorted([i for i in idx if excess[i] >= MIN_LOT], key=lambda i: -excess[i])
            takers = sorted([i for i in idx if short[i] >= MIN_LOT], key=lambda i: -short[i])
            for tk in takers:
                for gv in givers:
                    q = int(min(excess[gv], short[tk]))
                    if q >= MIN_LOT:
                        new[gv, z] -= q; new[tk, z] += q; excess[gv] -= q; short[tk] -= q
                        moves.append(dict(style_id=sid, size=sizes[z], from_store=store_ids[gv], to_store=store_ids[tk], units=q, region=region))
    s = sty_truth[sid]
    d = path.loc[sid].values
    for j, st in enumerate(st_truth):
        for z in range(Z):
            mu = sim.true_mean_demand(s, st, np.arange(98, 105), d, size_idx=z, store_idx=j)
            for res_, stk in ((before, stock[j, z]), (after, new[j, z])):
                left = stk
                for k in range(7):
                    u = min(mu[k], left); left -= u
                    res_["units"] += u; res_["revenue"] += u * s["full_price"] * (1 - d[k])
after["cost"] = sum(m["units"] for m in moves) * TRANSFER_COST
mv = pd.DataFrame(moves)
out = dict(allocation_split=dict(weeks="98-101", metric="fill rate (share of true demand met) with the same total units",
                                 **alloc, gain_pts=round((alloc["forecast_and_size_curves"] - alloc["current_practice"]) * 100, 1)),
           transfers=dict(moves=len(moves), units_moved=int(mv.units.sum()) if len(mv) else 0, cost_rand=after["cost"],
                          extra_units_sold=round(after["units"] - before["units"], 0),
                          extra_revenue_rand=round(after["revenue"] - before["revenue"], 0),
                          net_benefit_rand=round(after["revenue"] - before["revenue"] - after["cost"], 0),
                          rule=f"same region only, lots of {MIN_LOT}+ units, R{TRANSFER_COST:.0f} per unit; keep 110% of forecast at the sender"))
write_json("allocation.json", out)
if len(mv):
    mv.to_csv(paths.res("transfer_recommendations.csv"), index=False)
audit_log("allocation_published", transfers=len(moves), net_benefit=out["transfers"]["net_benefit_rand"])
print(json.dumps(out, indent=2))
