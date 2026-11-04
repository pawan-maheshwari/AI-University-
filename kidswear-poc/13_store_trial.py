"""
Step 13 - Store test-vs-control trial: design, pre-registration, simulated run and closed-loop analysis.

Design: stores are paired on pre-period behaviour (sales level, clearance profit, size mix, region);
one store in each pair is randomly assigned to the model-driven clearance (treatment), the other keeps
today's rules (control). Success metrics and the analysis are pre-registered (hashed into the audit trail)
before any outcome exists. A power calculation gives the minimum detectable effect.

Run (simulated next season, FY2027 clearance): appeal and stock drift; outcomes drawn from the demand
simulator with noise. Analysis: paired differences, bootstrap 95% CI, sign-flip permutation test and a
difference-in-differences against last season. Closed loop: realised vs predicted cash is recorded and the
outcomes are written in the sales-extract contract format so the next retraining includes them.
"""
import json, os
import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment
from scipy.stats import norm
import paths, sim
from governance_lib import write_json, audit_log, text_hash

rng = np.random.default_rng(2027)
sim.load_external(os.path.join(paths.GT, "external_truth.npz"))
sales = pd.read_csv(os.path.join(paths.RAW, "sales_weekly.csv.gz"))
stores = pd.read_csv(os.path.join(paths.RAW, "store_master.csv"))
sm = pd.read_csv(os.path.join(paths.RAW, "style_master.csv")).set_index("style_id")
look = pd.read_csv(paths.res("size_curve_lookup.csv"))
pack = {p["style_id"]: p for p in json.load(open(paths.res("markdown_pack.json")))["styles"]}
st_truth = pd.read_csv(os.path.join(paths.GT, "store_truth.csv")).to_dict("records")
sty26 = {s["style_id"]: s for s in pd.read_csv(os.path.join(paths.GT, "style_truth_FY2026.csv")).to_dict("records")}
store_ids = [s["store_id"] for s in st_truth]
Z = len(sim.SIZES)

# ---------------- design: matched pairs on pre-period behaviour
sales["cogs"] = sales.sales_units * sales.style_id.map(sm.unit_cost)
sales["rev"] = sales.sales_units * sales.selling_price
pre = sales[sales.week_index.between(72, 97)].groupby("store_id").sales_units.sum().rename("units_pre")
clr = sales[sales.week_index.between(98, 104)].groupby("store_id").apply(lambda d: (d.rev - d.cogs).sum()).rename("clearance_gp_last")
mix = look.groupby("store_id")[sim.SIZES[: Z // 2]].mean().sum(1).rename("young_size_share")
feat = pd.concat([pre, clr, mix], axis=1).reindex(store_ids)
zf = (feat - feat.mean()) / feat.std()
region = np.asarray(stores.set_index("store_id").region.reindex(store_ids), dtype=object)
dist = np.sqrt(((zf.values[:, None, :] - zf.values[None, :, :]) ** 2).sum(-1)) + 0.75 * (region[:, None] != region[None, :])
np.fill_diagonal(dist, 1e9)
pairs, used = [], set()
for i, j in sorted(((i, j) for i in range(len(store_ids)) for j in range(i + 1, len(store_ids))), key=lambda p: dist[p]):
    if i not in used and j not in used:
        pairs.append((store_ids[i], store_ids[j])); used |= {i, j}
assign = {}
for a, b in pairs:
    t = rng.random() < 0.5
    assign[a], assign[b] = ("treatment", "control") if t else ("control", "treatment")
diffs_pre = np.array([feat.loc[a, "clearance_gp_last"] - feat.loc[b, "clearance_gp_last"] for a, b in pairs])
sd_pair = float(np.std(diffs_pre, ddof=1))
mde = float((norm.ppf(0.95) + norm.ppf(0.8)) * sd_pair / np.sqrt(len(pairs)))
base_gp = float(feat.clearance_gp_last.mean())
md = json.load(open(paths.res("markdown_metrics.json")))
exp_effect = md["matched_sell_through"]["uplift_vs_actual"]["v2_quality_linked"] / len(store_ids)     # expected R per store
pairs_needed = int(np.ceil(((norm.ppf(0.95) + norm.ppf(0.8)) * sd_pair / max(exp_effect, 1)) ** 2))
prereg = dict(
    title="Model-driven clearance vs today's rules", unit="store", pairs=[dict(a=a, b=b, a_arm=assign[a], b_arm=assign[b]) for a, b in pairs],
    treatment="markdown path from the recommendation pack (quality-linked multi-step optimiser); transfers and size curves are left for a later trial so this one isolates pricing",
    control="today's rule-based clearance path",
    primary_metric="clearance gross profit per store (weeks 46-52)", secondary_metrics=["sell-through", "leftover units", "revenue"],
    hypothesis="treatment gross profit per store > control (one-sided, alpha 0.05)",
    analysis="paired difference; bootstrap 95% CI; sign-flip permutation p-value; difference-in-differences vs last season",
    power=dict(pairs=len(pairs), sd_of_pair_differences=round(sd_pair, 0), power=0.8, alpha=0.05,
               minimum_detectable_effect_rand_per_store=round(mde, 0),
               minimum_detectable_effect_pct=round(mde / base_gp, 4),
               expected_effect_rand_per_store=round(exp_effect, 0),
               pairs_needed_for_expected_effect=pairs_needed,
               note=(f"{len(pairs)} pairs detect effects of {mde / base_gp:.0%} or more; the expected effect needs {pairs_needed} pairs. "
                     + ("The trial is adequately powered." if pairs_needed <= len(pairs) else
                        "Options: more stores, two clearance windows, or analyse at style x store level with pre-period adjustment."))),
    stop_rules=["stop if treatment sell-through falls 5 points below control by week 49", "stop on any data-contract failure"],
)
prereg["registration_hash"] = text_hash(json.dumps(prereg, sort_keys=True))
write_json("trial_preregistration.json", prereg)
audit_log("trial_registered", registration_hash=prereg["registration_hash"], pairs=len(pairs), mde=round(mde, 0))

# ---------------- run: simulated FY2027 clearance
start = sales[sales.week_index == 98]
stock26 = {(r.style_id, r.store_id, r.size): r.stock_on_hand_start for r in start.itertuples(index=False)}
rule_path = sales[sales.week_index.between(98, 104)].groupby(["style_id", "week_index"]).discount.first().unstack()
out_rows, extract = [], []
for sid in sorted(pack):
    s = dict(sty26[sid], appeal=sty26[sid]["appeal"] * float(rng.lognormal(0, 0.2)))
    for j, st in enumerate(st_truth):
        arm = assign[st["store_id"]]
        path = np.array(pack[sid]["recommended_path"]) if arm == "treatment" else rule_path.loc[sid].values
        drift = float(rng.lognormal(0, 0.15))
        for z, size in enumerate(sim.SIZES):
            left = np.floor(stock26[(sid, st["store_id"], size)] * drift)
            stock0 = left
            mu = sim.true_mean_demand(s, st, np.arange(98, 105), path, size_idx=z, store_idx=j)
            dem = rng.poisson(rng.gamma(3.0, np.maximum(mu, 1e-12) / 3.0)) * (mu > 0)
            for k in range(7):
                u = min(dem[k], left)
                out_rows.append((st["store_id"], arm, sid, k, u, u * s["full_price"] * (1 - path[k]), u * s["unit_cost"]))
                extract.append(dict(season="FY2027", week_index=150 + k, fy_week=46 + k, store_id=st["store_id"], style_id=sid, size=size,
                                    full_price=s["full_price"], selling_price=round(s["full_price"] * (1 - path[k]), 2), discount=path[k],
                                    stock_on_hand_start=int(left), sales_units=int(u), return_units=0, trial_arm=arm))
                left -= u
            out_rows.append((st["store_id"], arm, sid, "end", 0, left * s["unit_cost"] * sim.SALVAGE_RATIO, 0.0))
o = pd.DataFrame(out_rows, columns=["store_id", "arm", "style_id", "week", "units", "revenue", "cogs"])
per = o.groupby(["store_id", "arm"]).agg(units=("units", "sum"), revenue=("revenue", "sum"), cogs=("cogs", "sum")).reset_index()
per["gross_profit"] = per.revenue - per.cogs
per = per.set_index("store_id")
d = np.array([(per.loc[a, "gross_profit"] - per.loc[b, "gross_profit"]) * (1 if assign[a] == "treatment" else -1) for a, b in pairs])
pre_d = np.array([(feat.loc[a, "clearance_gp_last"] - feat.loc[b, "clearance_gp_last"]) * (1 if assign[a] == "treatment" else -1) for a, b in pairs])
boot = [rng.choice(d, len(d)).mean() for _ in range(5000)]
flips = [np.mean(d * rng.choice([-1, 1], len(d))) for _ in range(20000)]
did = d - pre_d
boot_did = [rng.choice(did, len(did)).mean() for _ in range(5000)]
ctrl = per[per.arm == "control"].gross_profit.mean()
res = dict(
    simulated_season="FY2027 clearance (weeks 46-52)",
    mean_gp_per_store=dict(treatment=round(float(per[per.arm == "treatment"].gross_profit.mean()), 0), control=round(float(ctrl), 0)),
    effect_per_store_rand=round(float(d.mean()), 0), effect_pct_of_control=round(float(d.mean() / ctrl), 4),
    ci95_rand=[round(float(np.percentile(boot, 2.5)), 0), round(float(np.percentile(boot, 97.5)), 0)],
    permutation_p_one_sided=round(float(np.mean(np.array(flips) >= d.mean())), 4),
    did_effect_rand=round(float(did.mean()), 0),
    did_ci95_rand=[round(float(np.percentile(boot_did, 2.5)), 0), round(float(np.percentile(boot_did, 97.5)), 0)],
    pairs_treatment_won=int((d > 0).sum()), pairs=len(pairs),
    exceeds_mde=bool(d.mean() > mde),
)
res["decision"] = "Roll out: effect is positive and significant" if (res["permutation_p_one_sided"] < 0.05 and res["ci95_rand"][0] > 0) \
    else "Do not roll out yet: effect not significant"
# closed loop: predicted vs realised for treatment stores (chain-level pack prediction, scaled to treated share)
treated_share = sum(1 for v in assign.values() if v == "treatment") / len(assign)
pred_cash = sum(p["expected_cash"] for p in pack.values()) * treated_share
real_cash = float(o[o.arm == "treatment"].revenue.sum())
res["closed_loop"] = dict(predicted_cash_treatment=round(pred_cash, 0), realised_cash_treatment=round(real_cash, 0),
                          calibration_ratio=round(real_cash / pred_cash, 3),
                          outcomes_extract="trial_outcomes_extract.csv.gz (sales-extract contract) - appended at next retraining")
pd.DataFrame(extract).to_csv(os.path.join(paths.RES, "trial_outcomes_extract.csv.gz"), index=False)
per.reset_index().round(0).to_csv(paths.res("trial_store_outcomes.csv"), index=False)
write_json("trial_results.json", dict(preregistration_hash=prereg["registration_hash"], **res))
audit_log("trial_outcome_recorded", registration_hash=prereg["registration_hash"], effect=res["effect_per_store_rand"],
          p=res["permutation_p_one_sided"], decision=res["decision"])
print(json.dumps(prereg["power"], indent=1)); print(json.dumps(res, indent=1))
