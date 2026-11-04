"""
Step 12 - Planner override and feedback loop.

Planners change forecasts and pick a reason (the planner app exports these as CSV). The loop learns, per
reason, how much of an override to trust: final = model + beta x (override - model), with beta fitted on
past overrides against what actually sold (the unconstrained demand estimate). Reasons that add information
keep a high beta; reasons that double-count what the model already knows are damped automatically.

This run simulates a season of realistic overrides (validation weeks to learn, test weeks to evaluate),
ingests them through the same CSV contract the app uses, and logs every accepted change in the audit trail.
"""
import json, os
import numpy as np
import pandas as pd
import paths
from governance_lib import write_json, audit_log

REASONS = {
    "Local event not in feed": "store team knows an event the events feed does not list",
    "Local event planned": "an event that is already in the events feed",
    "Stock-out last year": "last year's sales were capped by stock",
    "Competitor promotion": "a competitor is on promotion",
    "Gut feel": "planner judgement, no specific evidence",
}
COLUMNS = ["style_id", "store_id", "week_index", "model_forecast", "override_value", "reason", "planner", "timestamp"]
rng = np.random.default_rng(11)


def ingest(path):
    """Validate an overrides CSV exported from the planner app."""
    o = pd.read_csv(path)
    missing = [c for c in COLUMNS if c not in o.columns]
    if missing:
        raise ValueError(f"overrides file is missing columns: {missing}")
    bad = ~o.reason.isin(REASONS) | (o.override_value < 0) | o.override_value.isna()
    return o[~bad].copy(), int(bad.sum())


unlisted = pd.read_csv(os.path.join(paths.GT, "events_unlisted.csv"))   # what store teams know (simulation only)
unlisted_set = set(zip(unlisted.store_id, unlisted.week_index))


def simulate(d, weeks):
    d = d[d.week_index.isin(weeks)].copy()
    rows = []
    for r in d.itertuples(index=False):
        u, g = rng.random(), rng.random()
        if (r.store_id, r.week_index) in unlisted_set and u < 0.8:
            rows.append((r, "Local event not in feed", 1.3))
        elif g < 0.03:
            rows.append((r, "Gut feel", float(rng.choice([0.75, 1.3]))))
        elif r.local_event == 1 and u < 0.8:
            rows.append((r, "Local event planned", 1.3))
        elif r.censored_lag8_11 > 0.6 and u < 0.15:
            rows.append((r, "Stock-out last year", 1.2))
        elif r.competitor_discount >= 0.2 and u < 0.1:
            rows.append((r, "Competitor promotion", 0.8))
    return pd.DataFrame([dict(style_id=r.style_id, store_id=r.store_id, week_index=r.week_index, model_forecast=round(r.pred, 2),
                              override_value=round(r.pred * f * rng.lognormal(0, 0.08), 2), reason=reason,
                              planner=str(rng.choice(["planner.a", "planner.b", "planner.c"])), timestamp=f"2026-W{r.week_index - 52}")
                         for r, reason, f in rows])


feat_cols = ["style_id", "store_id", "week_index", "local_event", "censored_lag8_11", "competitor_discount", "demand_est"]
feats = pd.concat([pd.read_csv(os.path.join(paths.SPL, f"{paths.DEPT}_{n}.csv"), usecols=feat_cols) for n in ("train", "validation", "test")])
oos = pd.read_csv(paths.res("rolling_oos_predictions.csv"))                       # weeks 67-97, made by models that had not seen them
tp = pd.read_csv(paths.res("forecast_test_predictions.csv"))[["style_id", "store_id", "week_index", "pred_final", "true_demand_units"]]
panel = pd.concat([oos[["style_id", "store_id", "week_index", "pred", "true_demand_units"]],
                   tp.rename(columns={"pred_final": "pred"})]).merge(feats, on=["style_id", "store_id", "week_index"])
ov = simulate(panel, range(67, 105))
f_all = paths.res("overrides_sample.csv")
ov.to_csv(f_all, index=False)
ov, rejected = ingest(f_all)
ov = ov.merge(panel[["style_id", "store_id", "week_index", "demand_est", "true_demand_units"]], on=["style_id", "store_id", "week_index"])


def wape(a, p):
    return float(np.abs(np.asarray(a) - np.asarray(p)).sum() / max(np.sum(a), 1e-9))


def learn(hist):
    betas = {}
    for reason, g in hist.groupby("reason"):
        grid = [(b, wape(g.demand_est, g.model_forecast + b * (g.override_value - g.model_forecast))) for b in np.linspace(0, 1, 21)]
        b = min(grid, key=lambda x: x[1])[0]
        shrink = len(g) / (len(g) + 30)                # few examples -> stay close to a neutral 0.5
        betas[reason] = round(float(shrink * b + (1 - shrink) * 0.5), 2)
    return betas


# forward chaining: each 6-week block is scored with trust learned only from earlier weeks
evals = []
for start in range(79, 105, 6):
    betas_b = learn(ov[ov.week_index < start])
    blk = ov[ov.week_index.between(start, start + 5)].copy()
    blk["beta"] = blk.reason.map(betas_b).fillna(0.5)
    evals.append(blk)
evals = pd.concat(evals)
evals["final"] = evals.model_forecast + evals.beta * (evals.override_value - evals.model_forecast)
betas = learn(ov)                                       # current trust, used by the planner app
learn_rows = ov[ov.week_index < 79]
by = []
for reason, g in evals.groupby("reason"):
    by.append(dict(reason=reason, overrides=len(g), learned_trust=betas.get(reason),
                   model_only_wape=round(wape(g.true_demand_units, g.model_forecast), 4),
                   accept_all_wape=round(wape(g.true_demand_units, g.override_value), 4),
                   learned_wape=round(wape(g.true_demand_units, g.final), 4)))
out = dict(reasons=REASONS, learned_trust=betas, learning_overrides=len(learn_rows), evaluation_overrides=len(evals),
           rejected_rows=rejected, method="forward chaining over weeks 79-104 in 6-week blocks; trust learned only from earlier overrides",
           overall=dict(model_only_wape=round(wape(evals.true_demand_units, evals.model_forecast), 4),
                        accept_all_wape=round(wape(evals.true_demand_units, evals.override_value), 4),
                        learned_wape=round(wape(evals.true_demand_units, evals.final), 4)),
           by_reason=by, csv_contract=COLUMNS)
write_json("override_feedback.json", out)
audit_log("overrides_ingested", rows=len(ov), learned_trust=betas, planners=sorted(set(ov.planner)))
print(json.dumps({k: v for k, v in out.items() if k not in ("reasons", "csv_contract")}, indent=2))
