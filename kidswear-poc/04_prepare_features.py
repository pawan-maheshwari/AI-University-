"""
Step 4 - Probabilistic demand unconstraining, external features and the train / validation / test split.

Unconstraining (EM, negative binomial):
  A size that sold out hides its demand: we only know demand >= stock. The E-step replaces each
  censored size-week with its expected demand given that lower bound, under a negative-binomial
  demand model; the M-step re-estimates the style-store-week level and the size shares. The
  dispersion is estimated from fully observed sizes. Each style-store-week gets an observation
  quality score: the share of its estimated demand that was directly observed.
  Diagnostics compare raw sales, the v1 share-scaling method and EM against true demand.

Features: calendar, price, lagged demand (>= 8 weeks old), last year, launch rate of sale,
quality signals from return comments, and external feeds (weather forecast, local events,
competitor promotions, consumer confidence) with interactions.

Split by time: train week_index 1-90, validation 91-97, test 98-104 (FY2026 winter clearance).
"""
import json, os
import numpy as np
import pandas as pd
from scipy.stats import nbinom
import paths, sim
from governance_lib import audit_log, write_json, text_hash

sales = pd.read_csv(os.path.join(paths.RAW, "sales_weekly.csv.gz"))
styles = pd.read_csv(os.path.join(paths.RAW, "style_master.csv"))
stores = pd.read_csv(os.path.join(paths.RAW, "store_master.csv"))
Z = len(sim.SIZES)
size_order = {s: i for i, s in enumerate(sim.SIZES)}
sales["z"] = sales["size"].map(size_order)
sales = sales.sort_values(["style_id", "store_id", "week_index", "z"]).reset_index(drop=True)
assert len(sales) % Z == 0
y = sales.sales_units.values.reshape(-1, Z).astype(float)
stock = sales.stock_on_hand_start.values.reshape(-1, Z).astype(float)
ssw = sales.iloc[::Z][["season", "style_id", "store_id", "week_index", "fy_week", "discount", "full_price",
                        "payday_week", "school_holiday"]].reset_index(drop=True)
ssw = ssw.merge(styles[["style_id", "category"]], on="style_id", how="left").merge(stores[["store_id", "cluster"]], on="store_id", how="left")
N = len(ssw)
cens = y >= stock                       # sold out (or nothing on the shelf): demand only known to be >= stock
obs = ~cens
train_rows = (ssw.week_index <= 90).values
grp = (ssw.cluster + "|" + ssw.category).values
groups = np.unique(grp)
gidx = np.searchsorted(groups, grp)

# ---- v1 initial shares: mean of fully observed sizes (training weeks)
P = np.zeros((len(groups), Z))
for g in range(len(groups)):
    m = (gidx == g) & train_rows
    num = (y[m] * obs[m]).sum(0); den = obs[m].sum(0)
    P[g] = num / np.maximum(den, 1)
P = P / P.sum(1, keepdims=True)
p = P[gidx]
obs_share = (p * obs).sum(1)
v1 = np.where(obs_share >= 0.3, (y * obs).sum(1) / np.maximum(obs_share, 1e-9), np.nan)

# ---- EM
partial = obs_share > 0
L = np.where(partial, (y * obs).sum(1) / np.maximum(obs_share, 1e-9), y.sum(1))
r = 3.0
hist = []
for it in range(60):
    mu = np.maximum(L[:, None] * p, 1e-6)
    # dispersion from fully observed sizes: Var = mu + mu^2 / r
    mo = mu[obs]; yo = y[obs]
    r = float(np.clip((mo ** 2).sum() / max(((yo - mo) ** 2 - mo).sum(), 1e-6), 0.3, 50))
    pr = r / (r + mu)
    c = stock
    tail = nbinom.sf(c - 1, r, pr)                                   # P(D >= c)
    tail_shift = nbinom.sf(c - 2, r + 1, pr)                         # P(Y >= c-1), Y ~ NB(r+1, p)
    e_cens = np.where(c <= 0, mu, np.where(tail > 1e-12, mu * tail_shift / np.maximum(tail, 1e-300), c))
    e_cens = np.maximum(e_cens, c)
    D = np.where(cens, e_cens, y)
    L_new = np.where(partial, D.sum(1), L)
    P_new = np.zeros_like(P)
    for g in range(len(groups)):
        m = (gidx == g) & train_rows & partial
        P_new[g] = D[m].sum(0) / max(D[m].sum(), 1e-9)
    change = float(np.abs(P_new - P).max())
    relv = np.abs(L_new - L) / np.maximum(L, 1)
    rel, rel_mean = float(np.nanmax(relv)), float(np.nanmean(relv))
    P, L = P_new, L_new
    p = P[gidx]
    hist.append(dict(iteration=it + 1, max_share_change=round(change, 6), max_level_change=round(rel, 6), mean_level_change=round(rel_mean, 7), dispersion_r=round(r, 3)))
    if change < 1e-4 and rel_mean < 1e-4 and rel < 0.01:
        break

# fully censored rows: no size was observed - borrow the level from neighbouring observed weeks (same style-store)
ssw["L"] = np.where(partial, L, np.nan)
ssw["obs_quality"] = np.where(partial, (np.where(obs, y, 0)).sum(1) / np.maximum(D.sum(1), 1e-9), 0.0)
good = ssw.L.where(ssw.obs_quality >= 0.5)
prior = good.groupby([ssw.style_id, ssw.store_id]).transform(lambda s: s.rolling(9, center=True, min_periods=2).mean())
fully = ~partial
ssw.loc[fully, "L"] = np.maximum(y[fully].sum(1), prior[fully].fillna(pd.Series(y.sum(1))[fully]).values)
mu_f = np.maximum(ssw.L.values[fully][:, None] * p[fully], 1e-6)
D[fully] = np.maximum(mu_f, stock[fully])
ssw.loc[fully, "L"] = D[fully].sum(1)
ssw["obs_quality"] = np.where(fully, 0.1, ssw.obs_quality)
ssw["demand_est"] = ssw.L
ssw["demand_est_v1"] = v1
ssw["sales_units"] = y.sum(1)
ssw["stock_on_hand_start"] = stock.sum(1)
ssw["return_units"] = sales.return_units.values.reshape(-1, Z).sum(1)
ssw["sizes_censored"] = cens.sum(1)
ssw["censored"] = (ssw.sizes_censored > 0).astype(int)

# ---- diagnostics against true demand (realised), training + validation weeks only
truth = pd.read_csv(os.path.join(paths.GT, "true_demand.csv.gz"))
truth = truth.groupby(["style_id", "store_id", "week_index"], as_index=False).true_demand_units.sum()
dg = ssw.merge(truth, on=["style_id", "store_id", "week_index"])
dg = dg[(dg.week_index <= 97) & (dg.true_demand_units > 0)]


def wape(a, b):
    return float(np.abs(a - b).sum() / a.sum())


both = dg.demand_est_v1.notna()
diag = dict(
    method="EM with negative-binomial demand; E-step = expected demand given demand >= stock",
    iterations=len(hist), converged=bool(hist[-1]["max_share_change"] < 1e-4 and hist[-1]["mean_level_change"] < 1e-4), dispersion_r=hist[-1]["dispersion_r"],
    rows=int(N), rows_with_any_censored_size=int((cens.any(1)).sum()), rows_fully_censored=int(fully.sum()),
    uplift_total_demand_vs_sales=round(float(ssw.demand_est.sum() / ssw.sales_units.sum()), 4),
    true_demand_vs_sales=round(float(dg.true_demand_units.sum() / dg.sales_units.sum()), 4),
    wape_vs_true_raw_sales=round(wape(dg.true_demand_units, dg.sales_units), 4),
    wape_vs_true_v1_share_scaling=round(wape(dg.true_demand_units[both], dg.demand_est_v1[both]), 4),
    wape_vs_true_em_same_rows=round(wape(dg.true_demand_units[both], dg.demand_est[both]), 4),
    wape_vs_true_em_all_rows=round(wape(dg.true_demand_units, dg.demand_est), 4),
    v1_rows_usable=round(float(both.mean()), 4),
    bias_v1=round(float(dg.demand_est_v1[both].sum() / dg.true_demand_units[both].sum() - 1), 4),
    bias_em=round(float(dg.demand_est.sum() / dg.true_demand_units.sum() - 1), 4),
    observation_quality=dict(mean=round(float(ssw.obs_quality.mean()), 3),
                             share_below_0_5=round(float((ssw.obs_quality < 0.5).mean()), 3)),
    history=hist,
)
write_json("unconstraining_diagnostics.json", diag)
sz = sales[["style_id", "store_id", "week_index", "size"]].copy()
sz["dhat"] = D.ravel().round(3); sz["censored"] = cens.ravel().astype(int); sz["sales"] = y.ravel().astype(int)
sz.to_csv(os.path.join(paths.SPL, "size_demand_est.csv.gz"), index=False)

# ---- features
g = ssw.merge(styles.drop(columns=["category", "full_price"]), on="style_id").merge(stores[["store_id", "region"]], on="store_id")
g = g.sort_values(["style_id", "store_id", "week_index"]).reset_index(drop=True)
g["launch_wi"] = g.groupby("style_id").week_index.transform("min")
g["is_new"] = (g.launch_wi > 1).astype(int)
g["weeks_since_launch"] = g.week_index - g.launch_wi
g["week_sin"] = np.sin(2 * np.pi * g.fy_week / 52); g["week_cos"] = np.cos(2 * np.pi * g.fy_week / 52)
g["log_price_index"] = np.log(1 - g.discount)
g["is_clearance"] = (g.fy_week >= 46).astype(int)
g["back_to_school"] = sim.back_to_school_flag(g.fy_week)
key = ["style_id", "store_id"]
gs = g.groupby(key)
g["sales_lag8"] = gs.sales_units.shift(8)
g["demand_lag8_11_mean"] = gs.demand_est.transform(lambda s: s.shift(8).rolling(4, min_periods=1).mean())
g["sales_lag8_11_mean"] = gs.sales_units.transform(lambda s: s.shift(8).rolling(4, min_periods=1).mean())
g["censored_lag8_11"] = gs.censored.transform(lambda s: s.shift(8).rolling(4, min_periods=1).mean())
# last year: align on week_index - 52 (works for styles with partial history)
ly = g[["style_id", "store_id", "week_index", "demand_est"]].copy(); ly["week_index"] += 52
g = g.merge(ly.rename(columns={"demand_est": "demand_ly"}), on=["style_id", "store_id", "week_index"], how="left")
for k, sh in (("demand_ly_next7_mean", (46, 7)), ("demand_ly_4wk_mean", (50, 5))):
    tmp = g[["style_id", "store_id", "week_index", "demand_est"]].copy()
    tmp[k] = tmp.groupby(key).demand_est.transform(lambda s, a=sh[0], n=sh[1]: s.shift(a).rolling(n, min_periods=1).mean())
    g = g.merge(tmp[["style_id", "store_id", "week_index", k]], on=["style_id", "store_id", "week_index"], how="left")
chain = g.groupby(["style_id", "week_index"]).demand_est.mean().rename("chain").reset_index()
chain["chain_lag8"] = chain.groupby("style_id").chain.shift(8)
chain["chain_ly"] = chain.groupby("style_id").chain.shift(52)
g = g.merge(chain[["style_id", "week_index", "chain_lag8", "chain_ly"]], on=["style_id", "week_index"], how="left")
cat = g.groupby(["category", "week_index"]).demand_est.mean().rename("cat").reset_index()
cat["cat_lag8"] = cat.groupby("category").cat.shift(8)
cat["cat_ly"] = cat.groupby("category").cat.shift(52)
g = g.merge(cat[["category", "week_index", "cat_lag8", "cat_ly"]], on=["category", "week_index"], how="left")
g["yoy_trend_lag8"] = g.demand_lag8_11_mean / gs.demand_est.transform(lambda s: s.shift(60).rolling(4, min_periods=1).mean()).reindex(g.index).replace(0, np.nan)
first6 = g[g.weeks_since_launch.between(0, 5) | ((g.is_new == 0) & (g.fy_week <= 6))]
early = first6.groupby(["season"] + key).demand_est.mean().rename("early_ros").reset_index()
g = g.merge(early, on=["season"] + key, how="left")
known = np.where(g.is_new == 1, g.weeks_since_launch >= 14, g.fy_week > 14)   # launch weeks must be 8+ weeks old, like every lag
g.loc[~known, "early_ros"] = np.nan

# quality signals (returns and return comments), 8+ weeks old
st = g.groupby(["style_id", "week_index"])[["sales_units", "return_units"]].sum().reset_index()
st[["cs", "cr"]] = st.groupby("style_id")[["sales_units", "return_units"]].cumsum()
st["return_rate_lag8"] = st.groupby("style_id").cr.shift(8) / st.groupby("style_id").cs.shift(8).replace(0, np.nan)
cr = pd.read_csv(os.path.join(paths.SPL, "comment_reasons.csv"))
cw = cr.groupby(["style_id", "week_index"]).agg(n=("is_quality", "size"), q=("is_quality", "sum")).reset_index()
st = st.merge(cw, on=["style_id", "week_index"], how="left").fillna({"n": 0, "q": 0})
st[["cn", "cq"]] = st.groupby("style_id")[["n", "q"]].cumsum()
st["quality_share_lag8"] = st.groupby("style_id").cq.shift(8) / st.groupby("style_id").cn.shift(8).replace(0, np.nan)
g = g.merge(st[["style_id", "week_index", "return_rate_lag8", "quality_share_lag8"]], on=["style_id", "week_index"], how="left")

# external feeds
wx = pd.read_csv(os.path.join(paths.EXT, "weather.csv"))[["region", "week_index", "temp_anomaly_forecast"]]
ev = pd.read_csv(os.path.join(paths.EXT, "events.csv"))
cp = pd.read_csv(os.path.join(paths.EXT, "competitor.csv"))
mc = pd.read_csv(os.path.join(paths.EXT, "macro.csv"))
mc["cci_lag4"] = mc.consumer_confidence.shift(4)
g = g.merge(wx, on=["region", "week_index"], how="left")
g = g.merge(ev.assign(local_event=1)[["store_id", "week_index", "local_event"]].drop_duplicates(["store_id", "week_index"]),
            on=["store_id", "week_index"], how="left").fillna({"local_event": 0})
g = g.merge(cp, on=["region", "category", "week_index"], how="left")
g = g.merge(mc[["week_index", "cci_lag4"]], on="week_index", how="left")
kind = g.category.map({c: v["season"] for c, v in sim.CATEGORIES.items()})
g["temp_x_winter"] = g.temp_anomaly_forecast * (kind == "winter")
g["temp_x_summer"] = g.temp_anomaly_forecast * (kind == "summer")
g["price_gap_vs_competitor"] = g.discount - g.competitor_discount
g["weight"] = g.obs_quality.clip(0.15, 1.0)

g["split"] = np.where(g.week_index <= 90, "train", np.where(g.week_index <= 97, "validation", "test"))
FEATURES = dict(
    categorical=["style_id", "store_id", "category", "fabric", "fit", "supplier", "cluster", "region"],
    base=["fy_week", "week_sin", "week_cos", "discount", "log_price_index", "full_price", "payday_week", "school_holiday",
          "is_clearance", "sales_lag8", "demand_lag8_11_mean", "sales_lag8_11_mean", "censored_lag8_11", "demand_ly",
          "demand_ly_next7_mean", "demand_ly_4wk_mean", "chain_lag8", "chain_ly", "cat_lag8", "cat_ly", "yoy_trend_lag8",
          "early_ros", "is_new", "weeks_since_launch", "return_rate_lag8", "quality_share_lag8"],
    external=["temp_anomaly_forecast", "temp_x_winter", "temp_x_summer", "local_event", "competitor_discount",
              "price_gap_vs_competitor", "cci_lag4", "back_to_school"],
)
FEATURES["version"] = text_hash(json.dumps(FEATURES, sort_keys=True) + open(__file__).read())
json.dump(FEATURES, open(os.path.join(paths.SPL, "feature_spec.json"), "w"), indent=2)
for name, part in g.groupby("split"):
    part.to_csv(os.path.join(paths.SPL, f"{paths.DEPT}_{name}.csv"), index=False)
    print(f"{name:<11} weeks {part.week_index.min()}-{part.week_index.max()} rows {len(part):>7,} censored {part.censored.mean():.0%}")
audit_log("features_built", feature_version=FEATURES["version"], unconstraining="EM-NB", rows=int(len(g)))
print(json.dumps({k: v for k, v in diag.items() if k != "history"}, indent=2))
