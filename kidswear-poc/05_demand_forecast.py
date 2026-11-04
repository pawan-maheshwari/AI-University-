"""
Step 5 - Demand forecast with monitoring, explainability and experiment tracking.

* LightGBM (Tweedie) on the EM-unconstrained demand target, weighted by observation quality.
* Hyper-parameter search on validation weeks (every trial recorded), refit on train + validation,
  scored once on the test weeks against true demand.
* Ablation: the same model without external features (weather, events, competitor, macro).
* P10 / P90 quantile models; coverage checked on test.
* Monitoring baseline: WAPE, bias, coverage, feature drift (PSI) train vs test and versus the previous run.
* Explainability pack: SHAP global importance, plus driver cards for every style and store
  (top three drivers pushing the forecast up and down).
* Experiment tracking: data, feature and model versions, all trials and metrics in the model registry.
"""
import json, os
import numpy as np
import pandas as pd
import lightgbm as lgb
import paths
from governance_lib import register_run, write_json, file_hash, psi, psi_bins, registry, audit_log

rng = np.random.default_rng(7)
spec = json.load(open(os.path.join(paths.SPL, "feature_spec.json")))
CAT, BASE, EXTF = spec["categorical"], spec["base"], spec["external"]
FULL = CAT + BASE + EXTF
NOEXT = CAT + BASE
load = lambda n: pd.read_csv(os.path.join(paths.SPL, f"{paths.DEPT}_{n}.csv"))
tr_all, va, te = load("train"), load("validation"), load("test")
truth = pd.read_csv(os.path.join(paths.GT, "true_demand.csv.gz")).groupby(["style_id", "store_id", "week_index"], as_index=False).true_demand_units.sum()
te = te.merge(truth, on=["style_id", "store_id", "week_index"], how="left")
va = va.merge(truth, on=["style_id", "store_id", "week_index"], how="left")
cats = {c: pd.CategoricalDtype(sorted(pd.concat([tr_all[c], va[c], te[c]]).astype(str).unique())) for c in CAT}
for d in (tr_all, va, te):
    for c in CAT:
        d[c] = d[c].astype(str).astype(cats[c])
tr = tr_all


def wape(a, p):
    a, p = np.asarray(a, float), np.asarray(p, float)
    return float(np.abs(a - p).sum() / max(a.sum(), 1e-9))


def bias(a, p):
    return float((np.sum(p) - np.sum(a)) / max(np.sum(a), 1e-9))


def ds(d, feats, ref=None):
    return lgb.Dataset(d[feats], d.demand_est, weight=d.weight, categorical_feature=[c for c in CAT if c in feats],
                       reference=ref, free_raw_data=False, params=dict(feature_pre_filter=False))


def planner_rule(hist, fut, origin):
    h = hist[(hist.week_index > origin - 4) & (hist.week_index <= origin)].copy()
    h["base"] = h.sales_units / (1 + 2 * h.discount)
    ros = h.groupby(["style_id", "store_id"], observed=True).base.mean().rename("ros").reset_index()
    ros["style_id"] = ros.style_id.astype(str); ros["store_id"] = ros.store_id.astype(str)
    f = fut[["style_id", "store_id", "discount"]].astype({"style_id": str, "store_id": str}).merge(ros, on=["style_id", "store_id"], how="left")
    return (f.ros.fillna(0) * (1 + 2 * f.discount)).values


# ---------------- search
dtr, dva = ds(tr, FULL), None
dva = ds(va, FULL, dtr)
trials = []
for k in range(8):
    params = dict(objective="tweedie", tweedie_variance_power=float(rng.uniform(1.1, 1.5)),
                  learning_rate=float(rng.choice([0.03, 0.05])), num_leaves=int(rng.choice([15, 31, 63])),
                  min_data_in_leaf=int(rng.choice([50, 100, 200])), feature_fraction=float(rng.uniform(0.6, 0.95)),
                  bagging_fraction=0.8, bagging_freq=1, lambda_l2=float(rng.choice([1, 5, 10])),
                  feature_pre_filter=False, verbose=-1, seed=k, num_threads=2)
    m = lgb.train(params, dtr, 3000, valid_sets=[dva], callbacks=[lgb.early_stopping(100, verbose=False)])
    p = m.predict(va[FULL], num_iteration=m.best_iteration)
    trials.append(dict(trial=k, params={kk: v for kk, v in params.items() if kk not in ("verbose", "num_threads")},
                       best_iter=m.best_iteration, val_wape_vs_demand_est=wape(va.demand_est, p), val_wape_vs_true=wape(va.true_demand_units, p)))
    print(f"trial {k} iters {m.best_iteration:4d} val WAPE {trials[-1]['val_wape_vs_true']:.4f}")
best = min(trials, key=lambda t: t["val_wape_vs_demand_est"])
P = dict(best["params"], verbose=-1, num_threads=2)
n_iter = int(best["best_iter"] * 1.1)

# validation predictions from train-only models (used later for stacking and conformal checks)
m_tr = lgb.train(P, dtr, best["best_iter"])
va["pred_model"] = m_tr.predict(va[FULL])
m_tr_noext = lgb.train(P, ds(tr, NOEXT), best["best_iter"])
va["pred_noext"] = m_tr_noext.predict(va[NOEXT])
va["pred_rule"] = planner_rule(tr, va, 90)

# ---------------- refit on train + validation, score test once
trva = pd.concat([tr, va.drop(columns=["true_demand_units", "pred_model", "pred_noext", "pred_rule"])], ignore_index=True)
for c in CAT:
    trva[c] = trva[c].astype(str).astype(cats[c])
model = lgb.train(P, ds(trva, FULL), n_iter)
model.save_model(os.path.join(paths.MOD, "demand_lgbm.txt"))
model_noext = lgb.train(P, ds(trva, NOEXT), n_iter)
q = {}
for a in (0.1, 0.9):
    qp = dict(P, objective="quantile", alpha=a); qp.pop("tweedie_variance_power", None)
    q[a] = lgb.train(qp, ds(trva, FULL), n_iter)
    q[a].save_model(os.path.join(paths.MOD, f"demand_lgbm_p{int(a * 100)}.txt"))
te["pred_model"] = model.predict(te[FULL])
te["pred_noext"] = model_noext.predict(te[NOEXT])
te["pred_p10"] = np.clip(q[0.1].predict(te[FULL]), 0, None)
te["pred_p90"] = np.maximum(q[0.9].predict(te[FULL]), te.pred_p10)
te["pred_rule"] = planner_rule(trva, te, 97)
A = te.true_demand_units.values
sw = lambda col: wape(*[te.groupby(["style_id", "week_index"], observed=True)[c].sum().values for c in ("true_demand_units", col)])
new = te.is_new.values == 1
metrics = dict(
    split=dict(train="week_index 1-90", validation="91-97", test="98-104"),
    rows=dict(train=len(tr), validation=len(va), test=len(te)),
    search=dict(trials=len(trials), best_trial=best["trial"], best_val_wape=round(best["val_wape_vs_true"], 4), iterations=n_iter),
    test=dict(
        model_wape=round(wape(A, te.pred_model), 4), model_without_external_wape=round(wape(A, te.pred_noext), 4),
        planner_rule_wape=round(wape(A, te.pred_rule), 4),
        model_bias=round(bias(A, te.pred_model), 4), planner_rule_bias=round(bias(A, te.pred_rule), 4),
        style_week_model_wape=round(sw("pred_model"), 4), style_week_rule_wape=round(sw("pred_rule"), 4),
        p10_p90_coverage=round(float(((A >= np.floor(te.pred_p10)) & (A <= np.ceil(te.pred_p90))).mean()), 4),
        new_styles_model_wape=round(wape(A[new], te.pred_model[new]), 4),
        established_model_wape=round(wape(A[~new], te.pred_model[~new]), 4)),
)
t = metrics["test"]
t["external_features_gain_pts"] = round((t["model_without_external_wape"] - t["model_wape"]) * 100, 2)
t["improvement_vs_rule_rel"] = round(1 - t["model_wape"] / t["planner_rule_wape"], 4)
metrics["by_category"] = te.groupby("category", observed=True).apply(lambda d: pd.Series(dict(
    model_wape=wape(d.true_demand_units, d.pred_model), rule_wape=wape(d.true_demand_units, d.pred_rule),
    without_external_wape=wape(d.true_demand_units, d.pred_noext)))).round(4).reset_index().to_dict("records")

# ---------------- monitoring: drift
num = [f for f in BASE + EXTF if f in te.columns]
baseline = {f: dict(edges=psi_bins(trva[f]).tolist()) for f in num if psi_bins(trva[f]) is not None}
drift = []
prev = [r for r in registry("demand_forecast", paths.DEPT) if r.get("feature_baseline_file")]
prev_base = None
if prev and os.path.exists(prev[-1]["feature_baseline_file"]):
    prev_base = json.load(open(prev[-1]["feature_baseline_file"]))
CALENDAR = {"fy_week", "week_sin", "week_cos", "is_clearance", "school_holiday", "payday_week", "back_to_school", "weeks_since_launch", "is_new"}
same_weeks = trva[trva.fy_week.isin(te.fy_week.unique())]            # same weeks last year: a seasonally fair baseline
for f in num:
    if f not in baseline:
        continue
    row = dict(feature=f, calendar=f in CALENDAR, psi_train_vs_test=round(psi(trva[f], te[f], baseline[f]["edges"]), 4),
               psi_same_weeks_last_year=round(psi(same_weeks[f], te[f]), 4))
    if prev_base and f in prev_base:
        row["psi_vs_previous_run"] = round(psi(np.array(prev_base[f]["sample"]), trva[f], prev_base[f]["edges"]), 4)
    drift.append(row)
for f in baseline:
    baseline[f]["sample"] = trva[f].dropna().sample(min(5000, trva[f].notna().sum()), random_state=1).round(4).tolist()
bfile = paths.res("feature_baseline.json")
json.dump(baseline, open(bfile, "w"))
drift = sorted(drift, key=lambda r: -r["psi_same_weeks_last_year"])
metrics["drift"] = dict(rule="PSI < 0.1 stable, 0.1-0.25 watch, > 0.25 shifted. Alerts use the same weeks last year as the baseline "
                             "and ignore calendar features, which move every season by design.",
                        shifted=[d["feature"] for d in drift if not d["calendar"] and d["psi_same_weeks_last_year"] > 0.25],
                        watch=[d["feature"] for d in drift if not d["calendar"] and 0.1 < d["psi_same_weeks_last_year"] <= 0.25],
                        features=drift)

# ---------------- explainability pack
NAMES = {"discount": "Discount depth", "log_price_index": "Price index", "style_id": "Style identity", "store_id": "Store",
         "category": "Category", "fabric": "Fabric", "fit": "Fit", "supplier": "Supplier", "cluster": "Store cluster", "region": "Region",
         "fy_week": "Week of year", "week_sin": "Season (week of year)", "week_cos": "Season (week of year)", "full_price": "Full price",
         "payday_week": "Payday week", "school_holiday": "School holiday", "is_clearance": "Clearance period",
         "sales_lag8": "Sales 8 weeks ago", "demand_lag8_11_mean": "Demand 8-11 weeks ago", "sales_lag8_11_mean": "Sales 8-11 weeks ago",
         "censored_lag8_11": "Stock-outs 8-11 weeks ago", "demand_ly": "Demand same week last year",
         "demand_ly_next7_mean": "Last year, coming weeks", "demand_ly_4wk_mean": "Last year, nearby weeks", "chain_lag8": "Chain demand 8 weeks ago",
         "chain_ly": "Chain demand last year", "cat_lag8": "Category demand 8 weeks ago", "cat_ly": "Category demand last year",
         "yoy_trend_lag8": "Year-on-year trend", "early_ros": "Launch rate of sale", "is_new": "New style",
         "weeks_since_launch": "Weeks since launch", "return_rate_lag8": "Return rate to date", "quality_share_lag8": "Quality complaints to date",
         "temp_anomaly_forecast": "Weather (temperature)", "temp_x_winter": "Weather x winter lines", "temp_x_summer": "Weather x summer lines",
         "local_event": "Local event", "competitor_discount": "Competitor promotion", "price_gap_vs_competitor": "Price gap to competitor",
         "cci_lag4": "Consumer confidence", "back_to_school": "Back to school"}
contrib = model.predict(te[FULL], pred_contrib=True)
C = pd.DataFrame(contrib[:, :-1], columns=FULL)
grouped = C.T.groupby(lambda f: NAMES.get(f, f)).sum().T          # merge features that share a plain-English name
imp = grouped.abs().mean().sort_values(ascending=False)
glob = [dict(driver=k, mean_abs_shap=round(float(v), 4)) for k, v in imp.items()]


def cards(by):
    out = {}
    gsum = grouped.groupby(te[by].astype(str).values).mean()
    for k, row in gsum.iterrows():
        r = row.drop(labels=[x for x in ("Style identity", "Store") if x in row.index])
        out[k] = dict(up=[dict(driver=d, effect=round(float(v), 4)) for d, v in r.sort_values(ascending=False).head(3).items() if v > 0],
                      down=[dict(driver=d, effect=round(float(v), 4)) for d, v in r.sort_values().head(3).items() if v < 0])
    return out


driver_cards = dict(note="SHAP values in the model's log scale: +0.1 lifts the forecast by about 10%.",
                    global_importance=glob, styles=cards("style_id"), stores=cards("store_id"))
write_json("driver_cards.json", driver_cards)

# ---------------- save + register
keep = ["style_id", "store_id", "week_index", "fy_week", "category", "is_new", "discount", "competitor_discount", "stock_on_hand_start",
        "sales_units", "censored", "true_demand_units", "pred_model", "pred_noext", "pred_p10", "pred_p90", "pred_rule"]
te[keep].round(3).to_csv(paths.res("forecast_test_predictions.csv"), index=False)
va[["style_id", "store_id", "week_index", "is_new", "demand_est", "true_demand_units", "pred_model", "pred_noext", "pred_rule"]] \
    .round(3).to_csv(paths.res("forecast_validation_predictions.csv"), index=False)
weekly = te.groupby("week_index").agg(true_demand=("true_demand_units", "sum"), sales=("sales_units", "sum"),
                                      model=("pred_model", "sum"), p10=("pred_p10", "sum"), p90=("pred_p90", "sum"),
                                      without_external=("pred_noext", "sum"), planner_rule=("pred_rule", "sum")).reset_index()
weekly.round(1).to_csv(paths.res("forecast_weekly_test.csv"), index=False)
pd.DataFrame([dict(trial=t_["trial"], best_iter=t_["best_iter"], val_wape=round(t_["val_wape_vs_true"], 4), **{k: t_["params"][k] for k in
              ("learning_rate", "num_leaves", "min_data_in_leaf", "feature_fraction", "lambda_l2", "tweedie_variance_power")}) for t_ in trials]) \
    .to_csv(paths.res("hyperparameter_trials.csv"), index=False)
dv = json.load(open(paths.res("data_validation.json")))["data_version"]
rec = register_run("demand_forecast", model_version=file_hash(os.path.join(paths.MOD, "demand_lgbm.txt")), data_version=dv,
                   feature_version=spec["version"], params=best["params"], iterations=n_iter,
                   training_window="week_index 1-97 (train + validation)", trials=trials, metrics=metrics["test"],
                   feature_baseline_file=bfile)
metrics["run_id"] = rec["run_id"]
write_json("forecast_metrics.json", metrics)
audit_log("forecast_published", run_id=rec["run_id"], test_wape=metrics["test"]["model_wape"])
print(json.dumps(metrics["test"], indent=2)); print("shifted:", metrics["drift"]["shifted"], "watch:", metrics["drift"]["watch"]); print(glob[:8])
