"""
Step 6 - Foundation-model ensemble and cold-start handling.

1. Try to load a foundation model (Chronos). If it loads, it forecasts every series zero-shot.
   If it cannot load here, the reason is recorded and two zero-shot fallbacks stand in:
   seasonal_trend for established styles and an attribute-similarity analog model for new styles.
2. Stack each with LightGBM: non-negative weights learned on validation weeks, separately for
   new (cold-start) and established styles, then scored once on the test weeks.
3. The stacked forecast becomes the pipeline's final forecast (pred_final).
"""
import json, os
import numpy as np
import pandas as pd
import paths, foundation
from governance_lib import write_json, audit_log

lead = 8
spl = lambda n: pd.read_csv(os.path.join(paths.SPL, f"{paths.DEPT}_{n}.csv"), usecols=["style_id", "store_id", "week_index", "demand_est"])
panel_df = pd.concat([spl("train"), spl("validation"), spl("test")])
panel = dict(zip(zip(panel_df.style_id, panel_df.store_id, panel_df.week_index), panel_df.demand_est))
styles = pd.read_csv(os.path.join(paths.RAW, "style_master.csv")).set_index("style_id")
styles["launch_wi"] = ((pd.to_datetime(styles.launch_week_start) - pd.Timestamp("2024-07-01")).dt.days // 7 + 1)
va = pd.read_csv(paths.res("forecast_validation_predictions.csv"))
te = pd.read_csv(paths.res("forecast_test_predictions.csv"))
va["is_new"] = va.style_id.map(styles.launch_wi > 1).astype(int)

status = {}
try:
    pipe = foundation.load_chronos()
    status["chronos"] = "loaded"
except foundation.FoundationModelUnavailable as e:
    pipe = None
    status["chronos"] = f"unavailable here ({e}); zero-shot fallbacks used"
try:
    foundation.load_timesfm()
except foundation.FoundationModelUnavailable as e:
    status["timesfm"] = f"unavailable here ({e})"


def zero_shot(d):
    out = np.full(len(d), np.nan)
    if pipe is not None:      # foundation model: forecast from history up to (target week - lead)
        for i, (s, st, w) in enumerate(d[["style_id", "store_id", "week_index"]].itertuples(index=False)):
            h = [panel.get((s, st, k), 0.0) for k in range(max(1, w - lead - 103), w - lead + 1)]
            if sum(h) > 0:
                out[i] = foundation.chronos_forecast(pipe, [h], lead)[0, -1, 1]
    new = d.is_new.values == 1
    fill = np.isnan(out)
    out[fill & ~new] = foundation.seasonal_trend(panel, d[fill & ~new], lead)
    out[fill & new] = foundation.analog(panel, styles, d[fill & new], lead=lead)
    return out


va["pred_zero_shot"] = zero_shot(va)
te["pred_zero_shot"] = zero_shot(te)


def wape(a, p):
    return float(np.abs(np.asarray(a) - np.asarray(p)).sum() / max(np.sum(a), 1e-9))


weights = {}
te["pred_final"] = te.pred_model
# convex blend (weights sum to 1) chosen on validation, then a damped level correction:
# robust when validation weeks look different from the weeks being forecast
for seg, flag in (("new_styles", 1), ("established", 0)):
    v = va[(va.is_new == flag)]
    vz = v.pred_zero_shot.where(v.pred_zero_shot.notna(), v.pred_model)
    grid = [(round(w, 2), wape(v.true_demand_units, w * v.pred_model + (1 - w) * vz)) for w in np.arange(0, 1.0001, 0.05)]
    w = min(grid, key=lambda g: g[1])[0]
    blend_v = w * v.pred_model + (1 - w) * vz
    k = float(np.clip(1 + 0.5 * (v.true_demand_units.sum() / blend_v.sum() - 1), 0.85, 1.2))
    nnls = foundation.nnls_weights(np.c_[v.pred_model, vz], v.true_demand_units)
    weights[seg] = dict(lightgbm=w, zero_shot=round(1 - w, 2), level_correction=round(k, 3), fitted_on_rows=len(v),
                        unconstrained_nnls_for_reference=[round(float(x), 3) for x in nnls])
    m = (te.is_new == flag).values
    zs = te.pred_zero_shot.where(te.pred_zero_shot.notna(), te.pred_model)
    te.loc[m, "pred_final"] = k * (w * te.pred_model[m] + (1 - w) * zs[m])
res = dict(status=status, stacking_weights=weights, segments={})
for seg, m in (("all", np.ones(len(te), bool)), ("new_styles", te.is_new.values == 1), ("established", te.is_new.values == 0)):
    d = te[m]
    zs = d.pred_zero_shot.where(d.pred_zero_shot.notna(), d.pred_model)
    res["segments"][seg] = dict(rows=int(m.sum()), lightgbm=round(wape(d.true_demand_units, d.pred_model), 4),
                                zero_shot=round(wape(d.true_demand_units, zs), 4),
                                stacked=round(wape(d.true_demand_units, d.pred_final), 4),
                                planner_rule=round(wape(d.true_demand_units, d.pred_rule), 4))
res["final_forecast"] = "pred_final = level_correction x (w x LightGBM + (1 - w) x zero-shot), by segment"
write_json("foundation_ensemble.json", res)
te.round(3).to_csv(paths.res("forecast_test_predictions.csv"), index=False)
audit_log("ensemble_published", weights=weights, chronos=status["chronos"][:40])
print(json.dumps(res, indent=2))
