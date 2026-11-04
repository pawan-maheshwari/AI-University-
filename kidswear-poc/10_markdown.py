"""
Step 10 - Markdown optimisation and the recommendation pack.

Inputs: the demand model's price response (including competitor promotions), store stock by size at the
start of clearance (observed data), learned size curves, and the quality ranking.

Optimisers compared (all must clear the same planned sell-through target):
  v1  grid search over two-step paths (weeks 46-48, then 49-52)
  v2  constrained multi-step optimiser: a weekly discount path over the remaining season, never decreasing,
      at most 60% off, solved by coordinate ascent with a sell-through penalty (Lagrangian style)
  v2+ the same, linked to quality signals: lines with a confirmed quality problem exit earlier
      (deeper first step) and their leftovers are valued at zero (they will not be carried or jobbed)
Every plan is replayed against TRUE demand at size level with real store stock.

Outputs: markdown_metrics.json, markdown_pack.json (per-style recommendation with confidence band and
constraint status), markdown_scenarios.json (data the planner app uses for what-if simulation).
"""
import json, os
import numpy as np
import pandas as pd
import lightgbm as lgb
import paths, sim
from governance_lib import write_json, audit_log, text_hash

HORIZON = 7                    # remaining clearance weeks
TARGET = 0.75                  # planned sell-through (style level)
MAXD = 0.6
LEVELS = np.round(np.arange(0, MAXD + 1e-9, 0.05), 2)
spec = json.load(open(os.path.join(paths.SPL, "feature_spec.json")))
FULL = spec["categorical"] + spec["base"] + spec["external"]
model = lgb.Booster(model_file=os.path.join(paths.MOD, "demand_lgbm.txt"))
q10 = lgb.Booster(model_file=os.path.join(paths.MOD, "demand_lgbm_p10.txt"))
q90 = lgb.Booster(model_file=os.path.join(paths.MOD, "demand_lgbm_p90.txt"))
te = pd.read_csv(os.path.join(paths.SPL, f"{paths.DEPT}_test.csv"))
for c, cats in zip(spec["categorical"], model.pandas_categorical):
    te[c] = pd.Categorical(te[c].astype(str), categories=cats)
te = te.sort_values(["style_id", "store_id", "week_index"]).reset_index(drop=True)
styles_t = pd.read_csv(os.path.join(paths.GT, "style_truth_FY2026.csv")).to_dict("records")
stores_t = pd.read_csv(os.path.join(paths.GT, "store_truth.csv")).to_dict("records")
sim.load_external(os.path.join(paths.GT, "external_truth.npz"))
sm = pd.read_csv(os.path.join(paths.RAW, "style_master.csv")).set_index("style_id")
store_ids = [s["store_id"] for s in stores_t]
style_ids = sorted(te.style_id.astype(str).unique())
T, Z, W = len(store_ids), len(sim.SIZES), HORIZON
s_idx = {s: i for i, s in enumerate(store_ids)}

# observed stock by size at the start of clearance (week 98)
sales = pd.read_csv(os.path.join(paths.RAW, "sales_weekly.csv.gz"), usecols=["week_index", "store_id", "style_id", "size", "stock_on_hand_start", "discount"])
start = sales[sales.week_index == 98]
stock = {sid: np.zeros((T, Z)) for sid in style_ids}
zi = {z: i for i, z in enumerate(sim.SIZES)}
for r in start.itertuples(index=False):
    stock[r.style_id][s_idx[r.store_id], zi[r.size]] = r.stock_on_hand_start
actual = sales[sales.week_index.between(98, 104)].groupby(["style_id", "week_index"]).discount.first().unstack().reindex(style_ids).values
look = pd.read_csv(paths.res("size_curve_lookup.csv")).set_index(["style_id", "store_id"])
share = {sid: look.loc[[(sid, st) for st in store_ids], sim.SIZES].values for sid in style_ids}
qrank = pd.DataFrame(json.load(open(paths.res("quality_dashboard.json"))))
QUALITY_FLAG = 0.35          # share of returns about fit, fabric or durability that flags a line (from the text model)
flagged = set(qrank[qrank.quality_share >= QUALITY_FLAG].style_id)

# price-response surface: predicted demand for every style-store-week at every discount level
X = te[FULL].copy()
surf = {k: np.zeros((len(LEVELS), len(te))) for k in ("p50", "p10", "p90")}
for li, d in enumerate(LEVELS):
    X["discount"] = d; X["log_price_index"] = np.log(1 - d); X["price_gap_vs_competitor"] = d - te.competitor_discount
    surf["p50"][li] = model.predict(X); surf["p10"][li] = np.clip(q10.predict(X), 0, None); surf["p90"][li] = q90.predict(X)
Q = {}
for k in surf:
    arr = surf[k].reshape(len(LEVELS), len(style_ids), T, W)        # rows sorted style, store, week
    Q[k] = {sid: arr[:, i] for i, sid in enumerate(style_ids)}


def simulate(sid, path_idx, which="p50", stock_override=None, share_override=None):
    st = (stock[sid] if stock_override is None else stock_override).copy()
    sh = share[sid] if share_override is None else share_override
    fp, cost = sm.loc[sid, "full_price"], sm.loc[sid, "unit_cost"]
    rev = sold_u = 0.0
    for k in range(W):
        dem = Q[which][sid][path_idx[k], :, k][:, None] * sh
        sold = np.minimum(dem, st); st -= sold
        rev += sold.sum() * fp * (1 - LEVELS[path_idx[k]]); sold_u += sold.sum()
    total = stock[sid].sum() if stock_override is None else stock_override.sum()
    return dict(revenue=rev, sold=sold_u, leftover=st.sum(), salvage=st.sum() * cost * sim.SALVAGE_RATIO,
                sell_through=sold_u / max(total, 1e-9))


def objective(sid, path, quality_link=False):
    r = simulate(sid, path)
    salv = 0.0 if (quality_link and sid in flagged) else r["salvage"]
    short = max(0.0, TARGET - r["sell_through"])
    return r["revenue"] + salv - 1e7 * short, r


def grid_v1(sid):
    best = None
    for a in (0.2, 0.3, 0.4, 0.5):
        for b in (0.0, 0.1, 0.2):
            path = [int(round(a / 0.05))] * 3 + [int(round(min(a + b, MAXD) / 0.05))] * 4
            val, _ = objective(sid, path)
            if best is None or val > best[0]:
                best = (val, path)
    return best[1]


def multistep_v2(sid, init, quality_link=False):
    path = list(init)
    if quality_link and sid in flagged:
        path = [max(p, int(0.3 / 0.05)) for p in path]       # exit early: start at 30% or deeper
    best, _ = objective(sid, path, quality_link)
    for _ in range(12):
        improved = False
        for k in range(W):
            lo = path[k - 1] if k > 0 else (int(0.3 / 0.05) if (quality_link and sid in flagged) else 0)
            hi = path[k + 1] if k < W - 1 else len(LEVELS) - 1
            for lv in range(lo, hi + 1):
                if lv == path[k]:
                    continue
                cand = path[:k] + [lv] + path[k + 1:]
                v, _ = objective(sid, cand, quality_link)
                if v > best + 1e-6:
                    best, path, improved = v, cand, True
        # also try shifting the whole tail one level (escapes coordinate-wise local optima)
        for k in range(W):
            for dlt in (-1, 1):
                cand = path[:k] + [int(np.clip(p + dlt, 0, len(LEVELS) - 1)) for p in path[k:]]
                if all(cand[i] <= cand[i + 1] for i in range(W - 1)):
                    v, _ = objective(sid, cand, quality_link)
                    if v > best + 1e-6:
                        best, path, improved = v, cand, True
        if not improved:
            break
    return path


def optimise_all():
    plans = {"actual": {}, "v1_grid": {}, "v2_multistep": {}, "v2_quality_linked": {}}
    for i, sid in enumerate(style_ids):
        plans["actual"][sid] = [int(np.argmin(np.abs(LEVELS - d))) for d in actual[i]]
        g = grid_v1(sid)
        plans["v1_grid"][sid] = g
        plans["v2_multistep"][sid] = multistep_v2(sid, g)
        plans["v2_quality_linked"][sid] = multistep_v2(sid, plans["v2_multistep"][sid], quality_link=True)
    return plans


def replay(plan):
    out = dict(revenue=0.0, units=0.0, leftover=0.0, salvage=0.0, stock=0.0, cogs=0.0, leftover_flagged=0.0)
    st_by = {s["style_id"]: s for s in styles_t}
    for sid in style_ids:
        s = st_by[sid]
        d = LEVELS[plan[sid]]
        for j, st in enumerate(stores_t):
            for z in range(Z):
                left = stock[sid][j, z]; out["stock"] += left
                mu = sim.true_mean_demand(s, st, np.arange(98, 98 + W), d, size_idx=z, store_idx=j)
                for k in range(W):
                    u = min(mu[k], left); left -= u
                    out["revenue"] += u * s["full_price"] * (1 - d[k]); out["units"] += u; out["cogs"] += u * s["unit_cost"]
                out["leftover"] += left; out["salvage"] += left * s["unit_cost"] * sim.SALVAGE_RATIO
                if sid in flagged:
                    out["leftover_flagged"] += left
    out["cash_recovered"] = out["revenue"] + out["salvage"]
    out["gross_profit"] = out["revenue"] - out["cogs"]
    out["sell_through"] = out["units"] / out["stock"]
    return {k: round(v, 3 if k == "sell_through" else 0) for k, v in out.items()}


# trace the profit / clearance frontier, then compare at the same sell-through as today's plan
frontier, runs = [], {}
for t in (0.75, 0.8, 0.85, 0.9):
    TARGET = t
    plans = optimise_all()
    res = {k: replay(v) for k, v in plans.items()}
    runs[t] = (plans, res)
    frontier.append(dict(target=t, **{k: dict(sell_through=res[k]["sell_through"], gross_profit=res[k]["gross_profit"],
                                             cash=res[k]["cash_recovered"]) for k in res}))
a_st = runs[0.75][1]["actual"]["sell_through"]
ok = [t for t in runs if runs[t][1]["v2_quality_linked"]["sell_through"] >= a_st]
TARGET = min(ok) if ok else max(runs)
plans, res = runs[TARGET]
a = res["actual"]
metrics = dict(scope=f"{len(style_ids)} styles x {T} stores x {Z} sizes, clearance weeks 98-104, replayed on true demand",
               planned_sell_through_target=TARGET, headline_rule="lowest planning target whose realised sell-through matches today's plan",
               max_discount=MAXD, horizon_weeks=W, plans=res, frontier=frontier,
               uplift_vs_actual={k: dict(gross_profit_rand=res[k]["gross_profit"] - a["gross_profit"],
                                         cash_rand=res[k]["cash_recovered"] - a["cash_recovered"],
                                         sell_through_pts=round((res[k]["sell_through"] - a["sell_through"]) * 100, 1))
                                 for k in res if k != "actual"},
               quality_flagged_styles=sorted(flagged),
               flagged_leftover_units=dict(actual=a["leftover_flagged"], v2_quality_linked=res["v2_quality_linked"]["leftover_flagged"]))
metrics["v2_vs_v1_gross_profit_rand"] = res["v2_multistep"]["gross_profit"] - res["v1_grid"]["gross_profit"]


def at_sell_through(method, st):
    pts = sorted((f[method]["sell_through"], f[method]["gross_profit"]) for f in frontier)
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return float(np.interp(st, xs, ys))


metrics["matched_sell_through"] = dict(
    sell_through=a_st, note="Each optimiser's profit / clearance frontier interpolated at today's realised sell-through.",
    gross_profit={m: round(at_sell_through(m, a_st), 0) for m in ("v1_grid", "v2_multistep", "v2_quality_linked")},
    actual_gross_profit=a["gross_profit"])
metrics["matched_sell_through"]["uplift_vs_actual"] = {m: round(v - a["gross_profit"], 0) for m, v in metrics["matched_sell_through"]["gross_profit"].items()}
write_json("markdown_metrics.json", metrics)

# recommendation pack + scenario data
pack, scen = [], {}
for i, sid in enumerate(style_ids):
    rec = plans["v2_quality_linked"][sid]
    p50, p10, p90 = simulate(sid, rec), simulate(sid, rec, "p10"), simulate(sid, rec, "p90")
    cur = simulate(sid, plans["actual"][sid])
    cash = lambda r: r["revenue"] + r["salvage"]
    pack.append(dict(style_id=sid, category=sm.loc[sid, "category"], stock_units=int(stock[sid].sum()),
                     recommended_path=[float(LEVELS[x]) for x in rec], current_path=[float(LEVELS[x]) for x in plans["actual"][sid]],
                     expected_cash=round(cash(p50), 0), cash_p10=round(cash(p10), 0), cash_p90=round(cash(p90), 0),
                     current_plan_cash=round(cash(cur), 0), expected_sell_through=round(p50["sell_through"], 3),
                     current_sell_through=round(cur["sell_through"], 3), expected_leftover=int(round(p50["leftover"])),
                     constraints=dict(sell_through_target_met=bool(p50["sell_through"] >= TARGET - 1e-9),
                                      never_decreases=bool(all(rec[k] <= rec[k + 1] for k in range(W - 1))),
                                      max_depth_ok=bool(max(LEVELS[rec]) <= MAXD), quality_exit_early=sid in flagged)))
    scen[sid] = dict(full_price=float(sm.loc[sid, "full_price"]), unit_cost=float(sm.loc[sid, "unit_cost"]),
                     stock_by_size=[int(x) for x in stock[sid].sum(0)],
                     size_share=[round(float(x), 4) for x in (share[sid] * Q["p50"][sid][0].sum(1)[:, None]).sum(0) / max(Q["p50"][sid][0].sum(), 1e-9)],
                     demand=[[round(float(x), 2) for x in Q["p50"][sid][l].sum(0)] for l in range(len(LEVELS))],
                     recommended=[int(x) for x in rec], current=[int(x) for x in plans["actual"][sid]])
write_json("markdown_pack.json", dict(target=TARGET, levels=LEVELS.tolist(), weeks=list(range(98, 98 + W)), styles=pack))
write_json("markdown_scenarios.json", dict(levels=LEVELS.tolist(), sizes=sim.SIZES, salvage_ratio=sim.SALVAGE_RATIO,
                                           note="Chain-level approximation for what-if analysis: demand by week at each discount level, stock and size mix by size.",
                                           styles=scen))
audit_log("markdown_recommended", pack_version=text_hash(json.dumps(pack, default=str)), styles=len(pack),
          expected_cash=float(sum(p["expected_cash"] for p in pack)))
print(json.dumps({k: res[k] for k in res}, indent=1)); print(json.dumps(metrics["uplift_vs_actual"], indent=1))
