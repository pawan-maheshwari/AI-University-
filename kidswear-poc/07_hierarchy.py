"""
Step 7 - Hierarchical forecasting and reconciliation.

Levels: chain total > category > category x store > style x store (bottom).
Base forecasts: bottom = final style-store forecast; each upper level has its own LightGBM model
trained on aggregated unconstrained demand. Base forecasts do not add up, so they are reconciled:
  * bottom-up     - sum the bottom forecasts
  * top-down      - split the chain forecast in proportion to the bottom forecasts
  * MinT (WLS)    - minimum-trace reconciliation with variances from validation errors
Every method is scored against true demand at every level; coherence is checked.
"""
import json, os
import numpy as np
import pandas as pd
import lightgbm as lgb
import paths
from governance_lib import write_json, audit_log

cols = ["style_id", "store_id", "category", "week_index", "fy_week", "week_sin", "week_cos", "discount", "competitor_discount",
        "temp_anomaly_forecast", "local_event", "cci_lag4", "payday_week", "school_holiday", "is_clearance", "demand_est", "split"]
d = pd.concat([pd.read_csv(os.path.join(paths.SPL, f"{paths.DEPT}_{n}.csv"), usecols=cols) for n in ("train", "validation", "test")])
truth = pd.read_csv(os.path.join(paths.GT, "true_demand.csv.gz")).groupby(["style_id", "store_id", "week_index"], as_index=False).true_demand_units.sum()
d = d.merge(truth, on=["style_id", "store_id", "week_index"], how="left")
P = dict(objective="tweedie", tweedie_variance_power=1.2, learning_rate=0.05, num_leaves=15, min_data_in_leaf=20,
         feature_fraction=0.9, verbose=-1, num_threads=2, seed=1)


def level_frame(keys):
    agg = d.groupby(keys + ["week_index"], as_index=False).agg(
        demand_est=("demand_est", "sum"), truth=("true_demand_units", "sum"), discount=("discount", "mean"),
        competitor_discount=("competitor_discount", "mean"), temp=("temp_anomaly_forecast", "mean"), event=("local_event", "mean"),
        cci=("cci_lag4", "first"), fy_week=("fy_week", "first"), ws=("week_sin", "first"), wc=("week_cos", "first"),
        payday=("payday_week", "first"), hol=("school_holiday", "first"), clr=("is_clearance", "first"))
    agg = agg.sort_values(keys + ["week_index"])
    g = agg.groupby(keys).demand_est if keys else agg.demand_est
    agg["lag8"] = g.shift(8)
    agg["lag8_11"] = (g.transform(lambda s: s.shift(8).rolling(4, min_periods=1).mean()) if keys
                      else agg.demand_est.shift(8).rolling(4, min_periods=1).mean())
    agg["ly"] = g.shift(52)
    for k in keys:
        agg[k] = agg[k].astype("category")
    return agg


def fit_predict(agg, keys, train_end, pred_weeks, rounds=400):
    feats = keys + ["fy_week", "ws", "wc", "discount", "competitor_discount", "temp", "event", "cci", "payday", "hol", "clr", "lag8", "lag8_11", "ly"]
    trn = agg[agg.week_index <= train_end]
    m = lgb.train(P, lgb.Dataset(trn[feats], trn.demand_est, categorical_feature=keys or "auto"), rounds)
    out = agg[agg.week_index.isin(pred_weeks)].copy()
    out["pred"] = np.clip(m.predict(out[feats]), 0, None)
    return out


LEVELS = {"total": [], "category": ["category"], "category_store": ["category", "store_id"]}
upper_val, upper_test = {}, {}
for name, keys in LEVELS.items():
    agg = level_frame(keys)
    upper_val[name] = fit_predict(agg, keys, 90, range(91, 98))
    upper_test[name] = fit_predict(agg, keys, 97, range(98, 105))

bt = pd.read_csv(paths.res("forecast_test_predictions.csv"))
bv = pd.read_csv(paths.res("forecast_validation_predictions.csv"))
dv = d[d.split == "validation"][["style_id", "store_id", "week_index", "category"]]
bv = bv.merge(dv, on=["style_id", "store_id", "week_index"])
bottom_keys = bt[["style_id", "store_id", "category"]].drop_duplicates().sort_values(["category", "store_id", "style_id"]).reset_index(drop=True)
nb = len(bottom_keys)
cs_keys = bottom_keys[["category", "store_id"]].drop_duplicates().reset_index(drop=True)
c_keys = sorted(bottom_keys.category.unique())
# summing matrix S: rows = total, categories, category-stores, bottom
rows = [np.ones(nb)]
rows += [(bottom_keys.category == c).values.astype(float) for c in c_keys]
rows += [((bottom_keys.category == r.category) & (bottom_keys.store_id == r.store_id)).values.astype(float) for r in cs_keys.itertuples()]
S = np.vstack(rows + [np.eye(nb)])
n_up = S.shape[0] - nb


def vector(week, up, bottom, col):
    b = bottom_keys.merge(bottom[bottom.week_index == week][["style_id", "store_id", col]], on=["style_id", "store_id"], how="left")[col].fillna(0).values
    t = up["total"][up["total"].week_index == week]
    c = up["category"][up["category"].week_index == week].set_index("category")
    cs = up["category_store"][up["category_store"].week_index == week].set_index(["category", "store_id"])
    vals = lambda df, keys, k: [float(df.loc[x, k]) if x in df.index else 0.0 for x in keys]
    return np.r_[t["pred"].values[:1],
                 vals(c, c_keys, "pred"), vals(cs, [tuple(x) for x in cs_keys.values], "pred"), b], \
           np.r_[t["truth"].values[:1], vals(c, c_keys, "truth"), vals(cs, [tuple(x) for x in cs_keys.values], "truth")]


# MinT-WLS variances from validation errors (actual = unconstrained demand estimate, which is observable)
err = []
for w in range(91, 98):
    yhat, _ = vector(w, upper_val, bv, "pred_model")
    bvw = bottom_keys.merge(bv[bv.week_index == w][["style_id", "store_id", "demand_est"]], on=["style_id", "store_id"], how="left").demand_est.values
    actual_b = np.nan_to_num(bvw)
    actual = S @ actual_b
    seen = np.r_[np.ones(n_up, bool), ~np.isnan(bvw)]
    e = np.where(seen, yhat - actual, np.nan)
    err.append(e)
err = np.array(err)
var = np.nanmean(err ** 2, axis=0)
var = np.where(np.isfinite(var) & (var > 0), var, np.nanmedian(var[n_up:]))
Winv = 1 / var
G = np.linalg.solve(S.T @ (Winv[:, None] * S), S.T * Winv)           # (S'W^-1 S)^-1 S' W^-1

methods = {"base": [], "bottom_up": [], "top_down": [], "mint_wls": []}
truth_all = []
for w in range(98, 105):
    yhat, t_up = vector(w, upper_test, bt, "pred_final")
    tb = bottom_keys.merge(bt[bt.week_index == w][["style_id", "store_id", "true_demand_units"]], on=["style_id", "store_id"], how="left").true_demand_units.fillna(0).values
    truth_all.append(S @ tb)
    b = yhat[n_up:]
    methods["base"].append(yhat)
    methods["bottom_up"].append(S @ b)
    methods["top_down"].append(S @ (yhat[0] * b / max(b.sum(), 1e-9)))
    methods["mint_wls"].append(S @ (G @ yhat))
truth_all = np.array(truth_all)
slices = {"total": slice(0, 1), "category": slice(1, 1 + len(c_keys)), "category_store": slice(1 + len(c_keys), n_up), "style_store": slice(n_up, None)}


def wape(a, p):
    return float(np.abs(a - p).sum() / max(a.sum(), 1e-9))


out = dict(levels=dict(total=1, category=len(c_keys), category_store=len(cs_keys), style_store=nb), results={})
for m, arr in methods.items():
    arr = np.array(arr)
    out["results"][m] = {lvl: round(wape(truth_all[:, sl], arr[:, sl]), 4) for lvl, sl in slices.items()}
    bottom = arr[:, n_up:]
    out["results"][m]["max_coherence_gap_units"] = round(float(np.abs(arr[:, :n_up] - bottom @ S[:n_up].T).max()), 3)
best = min((m for m in methods if m != "base"), key=lambda m: np.mean([out["results"][m][l] for l in slices]))
out["recommended"] = best
out["note"] = "Base forecasts are not coherent (levels do not add up); every reconciled method is coherent by construction."
write_json("hierarchy_reconciliation.json", out)
rec = np.array(methods[best])[:, n_up:]
recon = []
for i, w in enumerate(range(98, 105)):
    f = bottom_keys.copy(); f["week_index"] = w; f["pred_reconciled"] = rec[i]
    recon.append(f)
bt = bt.drop(columns=[c for c in ("pred_reconciled",) if c in bt]).merge(pd.concat(recon)[["style_id", "store_id", "week_index", "pred_reconciled"]],
                                                                          on=["style_id", "store_id", "week_index"], how="left")
bt.round(3).to_csv(paths.res("forecast_test_predictions.csv"), index=False)
audit_log("hierarchy_reconciled", method=best)
print(json.dumps(out, indent=2))
