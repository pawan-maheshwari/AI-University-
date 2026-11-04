"""
Step 14 - Automated retraining cadence.

Replays FY2026 in-season weeks 67-97 week by week. At each week the live model forecasts the next four
weeks (inputs at least 8 weeks old). Policies differ only in when the model is retrained on the expanding
window:
  never       train once at week 66
  quarterly   every 12 weeks
  monthly     every 4 weeks
  weekly      every week
  triggered   when the last 4 weeks' error is 15%+ worse than at training time, or a monitored input
              drifts (PSI > 0.25 against the training window), at most every 4 weeks
Scored on true demand. The chosen policy is written to config/retrain_policy.json for retrain.py.
"""
import json, os
import numpy as np
import pandas as pd
import lightgbm as lgb
import paths
from governance_lib import write_json, audit_log, registry, psi

spec = json.load(open(os.path.join(paths.SPL, "feature_spec.json")))
CAT, FULL = spec["categorical"], spec["categorical"] + spec["base"] + spec["external"]
d = pd.concat([pd.read_csv(os.path.join(paths.SPL, f"{paths.DEPT}_{n}.csv")) for n in ("train", "validation")], ignore_index=True)
truth = pd.read_csv(os.path.join(paths.GT, "true_demand.csv.gz")).groupby(["style_id", "store_id", "week_index"], as_index=False).true_demand_units.sum()
d = d.merge(truth, on=["style_id", "store_id", "week_index"], how="left")
for c in CAT:
    d[c] = d[c].astype(str).astype("category")
runs = registry("demand_forecast", paths.DEPT)
P = dict(runs[-1]["params"] if runs else dict(objective="tweedie", tweedie_variance_power=1.3, num_leaves=31, min_data_in_leaf=100),
         learning_rate=0.08, verbose=-1, num_threads=2)
ROUNDS = 250
MONITOR = ["competitor_discount", "temp_anomaly_forecast", "cci_lag4", "discount", "demand_lag8_11_mean"]
START, END, H = 66, 97, 4


def fit(upto):
    t = d[d.week_index <= upto]
    return lgb.train(P, lgb.Dataset(t[FULL], t.demand_est, weight=t.weight, categorical_feature=CAT,
                                    params=dict(feature_pre_filter=False)), ROUNDS)


def wape(a, p):
    return float(np.abs(np.asarray(a) - np.asarray(p)).sum() / max(np.sum(a), 1e-9))


cache = {}


def model_at(w):
    if w not in cache:
        cache[w] = fit(w)
    return cache[w]


def run(policy):
    trained_at, retrains, preds, log = START, [START], [], []
    ref_err = None
    for origin in range(START, END - H + 1):
        if origin > START:
            due = False
            if policy == "weekly":
                due = True
            elif policy == "monthly":
                due = (origin - trained_at) >= 4
            elif policy == "quarterly":
                due = (origin - trained_at) >= 12
            elif policy == "triggered" and origin - trained_at >= 4:
                recent = d[d.week_index.between(origin - 3, origin)]
                err = wape(recent.demand_est, model_at(trained_at).predict(recent[FULL]))
                ref = d[d.week_index.between(trained_at - 3, trained_at)]
                ref_err = wape(ref.demand_est, model_at(trained_at).predict(ref[FULL]))
                drift = max(psi(d[d.week_index <= trained_at][f].sample(20000, random_state=1, replace=True), recent[f]) for f in MONITOR)
                due = err > 1.15 * ref_err or drift > 0.25
                if due:
                    log.append(dict(week=origin, recent_error=round(err, 4), error_at_training=round(ref_err, 4), max_psi=round(drift, 3)))
            if due:
                trained_at = origin
                retrains.append(origin)
        fut = d[d.week_index.between(origin + 1, origin + H)]
        preds.append(pd.DataFrame(dict(a=fut.true_demand_units.values, p=model_at(trained_at).predict(fut[FULL]),
                                       style_id=fut.style_id.astype(str).values, store_id=fut.store_id.astype(str).values,
                                       week_index=fut.week_index.values, origin=origin)))
    allp = pd.concat(preds)
    if policy == "monthly":       # out-of-sample forecasts made 1 week ahead, reused by the override feedback loop
        oos = allp.sort_values("origin").groupby(["style_id", "store_id", "week_index"]).tail(1)
        oos.rename(columns={"p": "pred", "a": "true_demand_units"}).drop(columns="origin").round(3) \
            .to_csv(paths.res("rolling_oos_predictions.csv"), index=False)
    return dict(policy=policy, wape=round(wape(allp.a, allp.p), 4), retrains=len(retrains), retrain_weeks=retrains, trigger_log=log)


results = [run(p) for p in ("never", "quarterly", "monthly", "triggered", "weekly")]
best = min(results, key=lambda r: r["wape"] + 0.0005 * r["retrains"])      # small cost per retrain
policy = dict(policy=best["policy"], max_weeks_between_retrains=12, min_weeks_between_retrains=4,
              triggers=dict(error_worse_than_training_by=0.15, psi_above=0.25, monitored_features=MONITOR),
              expanding_window=True, chosen_by="lowest error with a small cost per retrain, FY2026 replay")
json.dump(policy, open(os.path.join(paths.ROOT, "config", "retrain_policy.json"), "w"), indent=2)
write_json("retrain_cadence.json", dict(replay_weeks=f"{START + 1}-{END}", horizon_weeks=H, policies=results, chosen=policy))
audit_log("retrain_policy_set", policy=best["policy"], wape=best["wape"])
for r in results:
    print(f"{r['policy']:<10} WAPE {r['wape']:.4f} retrains {r['retrains']:>2}")
print("chosen:", best["policy"])
