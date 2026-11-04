"""
Step 1 - Generate realistic synthetic sample data for one department (DEPT, default kidswear).

data/<dept>/raw/
  style_master.csv, store_master.csv          masters (store cluster label is last season's, as in real life)
  sales_weekly.csv.gz                         style x store x size x week: price, discount, stock, sales, returns
  returns_comments.csv                        free-text return comments (half with a staff-verified reason)
  external/weather.csv, events.csv, competitor.csv, macro.csv, calendar.csv   external feeds
  ground_truth/                               hidden truth - scoring only, never used for training
Two seasons, FY2025 and FY2026 (week_index 1-104, week 1 = early July). New styles launch in FY2026.
"""
import json, os
import numpy as np
import pandas as pd
import paths, sim

rng = np.random.default_rng(sim.SEED + 1 + (0 if paths.DEPT == "kidswear" else 11))
world = sim.build_world()
base_styles, stores = world["styles"], world["stores"]
S, T, Z, W = len(base_styles), len(stores), len(sim.SIZES), 52
ext = sim.build_external(stores)
np.savez_compressed(os.path.join(paths.GT, "external_truth.npz"), **ext)
sim.EXT = ext
SEASONS = ["FY2025", "FY2026"]
dispersion = 3.0
frames, true_frames, season_styles, season_end = [], [], {}, {}
store_ids = np.array([s["store_id"] for s in stores])
style_ids = np.array([s["style_id"] for s in base_styles])
sizes = np.array(sim.SIZES)
launch = np.array([s["launch_wi"] for s in base_styles])

for si, season in enumerate(SEASONS):
    styles = [dict(s, appeal=s["appeal"] * float(rng.lognormal(0, 0.2)), season=season) for s in base_styles]
    season_styles[season] = styles
    wis = np.arange(1, W + 1) + si * W
    fw = np.arange(1, W + 1)

    # price plan the business actually ran
    disc = np.zeros((S, W))
    for i in range(S):
        for w in fw:
            if (6 <= w <= 23 or 27 <= w <= 45) and rng.random() < 0.08:
                disc[i, w - 1] = rng.choice([0.10, 0.15, 0.20, 0.25])
        disc[i, 23:26] = rng.choice([0.2, 0.3, 0.4])
        d1 = rng.choice([0.3, 0.4, 0.5])
        disc[i, 45:48] = d1
        disc[i, 48:52] = min(d1 + 0.1, 0.6)

    mu = np.zeros((S, T, Z, W)); mu_plan = np.zeros((S, T, W))
    for i, s in enumerate(styles):
        s_plan = dict(s, quality_issue="none")
        for j, st in enumerate(stores):
            for z in range(Z):
                mu[i, j, z] = sim.true_mean_demand(s, st, wis, disc[i], size_idx=z, store_idx=j)
            mu_plan[i, j] = sim.true_mean_demand(s_plan, st, wis, np.zeros(W), store_idx=j, ext={})  # plan ignores externals

    # inventory flow under current practice (one chain-wide flat size curve)
    buy = 1.05 * mu_plan.sum(axis=(1, 2))
    dc = buy.copy()
    soh = np.zeros((S, T, Z))
    live = launch[:, None] <= wis[None, :]                                   # S x W
    for w in fw:
        wi = w - 1
        starting = live[:, wi] & ((wi == 0) | ~live[:, max(wi - 1, 0)])
        if starting.any():                                                   # first allocation at launch
            send = np.floor(mu_plan[starting][:, :, wi:wi + 6].sum(axis=2)[:, :, None] * 1.15 * sim.CHAIN_CURVE)
            soh[starting] += send; dc[starting] -= send.sum(axis=(1, 2))
        if w in range(7, 44, 4):
            target = np.round(mu_plan[:, :, wi:wi + 4].sum(axis=2)[:, :, None] * 1.2 * sim.CHAIN_CURVE)
            need = np.maximum(target - soh, 0) * live[:, wi][:, None, None]
            ratio = np.clip(dc / np.maximum(need.sum(axis=(1, 2)), 1), 0, 1)
            send = np.floor(need * ratio[:, None, None]); soh += send; dc -= send.sum(axis=(1, 2))
        if w == 44:
            weight = mu_plan[:, :, 40:44].sum(axis=2)[:, :, None] * sim.CHAIN_CURVE + 1e-9
            weight = weight / weight.sum(axis=(1, 2), keepdims=True)
            send = np.floor(np.maximum(dc, 0)[:, None, None] * weight); soh += send; dc -= send.sum(axis=(1, 2))
        if w == 46:
            season_end[season] = dict(soh_wk46=soh.copy(), disc=disc.copy())
        m = mu[:, :, :, wi]
        demand = rng.poisson(rng.gamma(dispersion, np.maximum(m, 1e-12) / dispersion)) * (m > 0)
        soh_start = soh.copy()
        sales = np.minimum(demand, soh); soh -= sales
        rr = np.array([sim.return_rate(s) for s in styles])[:, None, None]
        returns = rng.binomial(sales.astype(int), np.broadcast_to(rr, sales.shape))
        I, J, K = np.meshgrid(np.arange(S), np.arange(T), np.arange(Z), indexing="ij")
        keep = live[I, wi].ravel()
        I, J, K = I.ravel()[keep], J.ravel()[keep], K.ravel()[keep]
        fp = np.array([s["full_price"] for s in styles])
        frames.append(pd.DataFrame(dict(
            season=season, week_index=wis[wi], fy_week=w, store_id=store_ids[J], style_id=style_ids[I], size=sizes[K],
            full_price=fp[I], selling_price=np.round(fp[I] * (1 - disc[I, wi]), 2), discount=disc[I, wi],
            stock_on_hand_start=soh_start[I, J, K].astype(int), sales_units=sales[I, J, K].astype(int),
            return_units=returns[I, J, K].astype(int),
            stockout_flag=((soh_start[I, J, K] > 0) & (sales[I, J, K] >= soh_start[I, J, K])).astype(int))))
        true_frames.append(pd.DataFrame(dict(season=season, week_index=wis[wi], store_id=store_ids[J], style_id=style_ids[I],
                                             size=sizes[K], true_demand_units=demand[I, J, K].astype(int),
                                             true_mean_demand=np.round(m[I, J, K], 4))))
    season_end[season].update(dc_left=dc.copy(), store_left=soh.copy())

sales_df = pd.concat(frames, ignore_index=True)
sales_df.insert(2, "week_start", (pd.Timestamp("2024-07-01") + pd.to_timedelta((sales_df.week_index - 1) * 7, unit="D")).dt.date)
sales_df["payday_week"] = sim.payday_flag(sales_df.fy_week)
sales_df["school_holiday"] = sim.holiday_flag(sales_df.fy_week)
sales_df.to_csv(os.path.join(paths.RAW, "sales_weekly.csv.gz"), index=False)
truth = pd.concat(true_frames, ignore_index=True)
truth.to_csv(os.path.join(paths.GT, "true_demand.csv.gz"), index=False)

# masters
sd = pd.DataFrame(base_styles)
sd["launch_week_start"] = (pd.Timestamp("2024-07-01") + pd.to_timedelta((sd.launch_wi - 1) * 7, unit="D")).dt.date
sd[["style_id", "category", "fabric", "fit", "supplier", "colour", "full_price", "unit_cost", "launch_week_start"]] \
    .to_csv(os.path.join(paths.RAW, "style_master.csv"), index=False)
for season in SEASONS:
    pd.DataFrame(season_styles[season]).to_csv(os.path.join(paths.GT, f"style_truth_{season}.csv"), index=False)
pd.DataFrame(stores)[["store_id", "cluster", "region"]].to_csv(os.path.join(paths.RAW, "store_master.csv"), index=False)
pd.DataFrame(stores).to_csv(os.path.join(paths.GT, "store_truth.csv"), index=False)
np.save(os.path.join(paths.GT, "fy2026_store_stock_at_wk46.npy"), season_end["FY2026"]["soh_wk46"])
np.save(os.path.join(paths.GT, "fy2026_actual_discounts.npy"), season_end["FY2026"]["disc"])
np.save(os.path.join(paths.GT, "fy2026_dc_left.npy"), season_end["FY2026"]["dc_left"])

# external feeds (what a retailer could buy or scrape) - true anomalies stay hidden, forecasts are published
weeks = np.arange(1, 105)
wk_start = (pd.Timestamp("2024-07-01") + pd.to_timedelta((weeks - 1) * 7, unit="D")).date
pd.DataFrame([dict(region=r, week_index=t, week_start=wk_start[t - 1], temp_c=round(float(ext["temp"][ri, t - 1]), 1),
                   temp_anomaly_forecast=round(float(ext["temp_fc"][ri, t - 1]), 2))
              for ri, r in enumerate(sim.REGIONS) for t in weeks]).to_csv(os.path.join(paths.EXT, "weather.csv"), index=False)
ev_names = ["Mall family day", "Store reopening after refurbishment", "Local school fair", "Community market"]
ev = pd.DataFrame([dict(store_id=stores[j]["store_id"], week_index=int(t + 1), event=str(rng.choice(ev_names)))
                   for j, t in zip(*np.nonzero(ext["event"]))])
listed = rng.random(len(ev)) < 0.7          # the events feed is incomplete: ~30% are known only to store teams
ev[listed].to_csv(os.path.join(paths.EXT, "events.csv"), index=False)
ev[~listed].to_csv(os.path.join(paths.GT, "events_unlisted.csv"), index=False)
cats = list(sim.CATEGORIES)
pd.DataFrame([dict(region=r, category=c, week_index=t, competitor_discount=round(float(ext["comp"][ri, ci, t - 1]), 3))
              for ri, r in enumerate(sim.REGIONS) for ci, c in enumerate(cats) for t in weeks]) \
    .to_csv(os.path.join(paths.EXT, "competitor.csv"), index=False)
pd.DataFrame(dict(week_index=weeks, consumer_confidence=np.round(ext["cci"], 2))).to_csv(os.path.join(paths.EXT, "macro.csv"), index=False)
fwk = sim.fy_week(weeks)
pd.DataFrame(dict(week_index=weeks, week_start=wk_start, fy_week=fwk, payday_week=sim.payday_flag(fwk),
                  school_holiday=sim.holiday_flag(fwk), back_to_school=sim.back_to_school_flag(fwk))) \
    .to_csv(os.path.join(paths.EXT, "calendar.csv"), index=False)

# return comments; FY2026 customers also use new phrasing (tests continuous learning of the text model)
T_ = {
 "fit": ["too tight around the arms", "body is very short, tummy shows", "neckline too narrow, cant get it over his head",
         "legs are cut way too slim", "armholes are tiny", "sleeves far too short even in the right size",
         "the cut is strange, baggy at top and tight at hips", "waist band digs in", "collar sits funny and pulls"],
 "fabric": ["shrunk after one wash", "pilled badly after two wears", "material is scratchy and itchy, she refused to wear it",
            "colour faded after first wash", "fabric feels thin and cheap", "bobbles everywhere after a week",
            "went see-through after washing", "print cracked in the wash", "lost its shape after washing"],
 "durability": ["seam split at the shoulder", "zip broke on day two", "hole in the knee after a week", "buttons fell off",
                "stitching came undone", "hem unravelled", "pocket ripped off", "the snap fasteners came loose",
                "the elastic snapped"],
 "sizing": ["bought the wrong size", "needed a bigger size", "exchanging for smaller size", "she grew out of it already",
            "size up please", "ordered the smaller age but needs the next one", "wrong age size, gift was for older cousin"],
 "colour": ["colour different from the website", "pink looked more orange in store light", "did not like the colour once home",
            "navy looks almost black", "print colour is dull compared to photo"],
 "changed_mind": ["changed my mind", "got the same one as a gift", "no longer needed", "bought two by mistake",
                  "found one cheaper", "child did not like it", "party was cancelled"],
}
T_NEW = {
 "fit": ["way too boxy on her", "crotch sits too low", "rides up at the back", "proportions are off for the age"],
 "fabric": ["lint balls all over", "colour bled onto other washing", "goes stiff after drying", "fluff comes off on everything"],
 "durability": ["seam burst at the side", "strap tore off", "velcro stopped sticking", "sole of the feet wore through"],
}
FILL = ["", "", "", "bought for my daughter.", "for my son.", "gift for my nephew.", "eish,", "very disappointed.",
        "not happy.", "please refund.", "usually love these kids clothes but", "school uniform item,", "my kid is 6."]
VAGUE = ["not happy with it", "returned", "didnt work for us", "not what i expected", "no reason given",
         "just not right", "unhappy with quality", "doesnt look good on her", "returning this", "not for us"]
BACKGROUND = {"sizing": 0.36, "changed_mind": 0.34, "colour": 0.12, "fit": 0.06, "fabric": 0.06, "durability": 0.06}


def typo(t):
    if rng.random() < 0.15 and len(t) > 6:
        k = rng.integers(1, len(t) - 1); t = t[:k] + t[k + 1:]
    return t


ret_by = sales_df.groupby(["season", "style_id"]).return_units.sum()
ret_week = sales_df.groupby(["season", "style_id", "fy_week"]).return_units.sum()
comments, cid = [], 0
for s in season_styles["FY2025"] + season_styles["FY2026"]:
    key = (s["season"], s["style_id"])
    if key not in ret_by.index:
        continue
    n = int(ret_by[key] * 0.35)
    wk = ret_week.loc[key]
    pw = (wk.values / wk.values.sum()) if wk.values.sum() > 0 else None
    for _ in range(n):
        reason = s["quality_issue"] if (s["quality_issue"] != "none" and rng.random() < 0.35) else \
            rng.choice(list(BACKGROUND), p=list(BACKGROUND.values()))
        if rng.random() < 0.18:
            text = rng.choice(VAGUE)
        else:
            pool = T_[reason]
            if s["season"] == "FY2026" and reason in T_NEW and rng.random() < 0.45:
                pool = T_NEW[reason]
            text = rng.choice(pool)
            if rng.random() < 0.30:
                other = rng.choice([r for r in T_ if r != reason])
                text = (text + " and " + rng.choice(T_[other])) if rng.random() < 0.5 else \
                       (rng.choice(T_[other]) + ", but mainly " + text)
        text = typo(typo((rng.choice(FILL) + " " + text).strip()))
        if rng.random() < 0.3:
            text = text.capitalize()
        labelled = rng.random() < 0.5
        code = str(rng.choice(list(T_))) if (labelled and rng.random() < 0.08) else reason
        fwk_c = int(rng.choice(wk.index.values, p=pw)) if pw is not None else int(rng.integers(1, 53))
        comments.append(dict(comment_id=f"R{cid:06d}", style_id=s["style_id"], season=s["season"], fy_week=fwk_c,
                             week_index=fwk_c + (52 if s["season"] == "FY2026" else 0),
                             store_id=str(rng.choice(store_ids)), comment=text,
                             verified_reason=code if labelled else "", true_reason=reason))
        cid += 1
cdf = pd.DataFrame(comments)
cdf.drop(columns="true_reason").to_csv(os.path.join(paths.RAW, "returns_comments.csv"), index=False)
cdf[["comment_id", "true_reason"]].to_csv(os.path.join(paths.GT, "returns_true_reason.csv"), index=False)

summary = dict(department=sim.CFG["name"], rows_sales=len(sales_df), seasons=SEASONS, styles=S,
               new_styles=int(sum(s["is_new"] for s in base_styles)), stores=T, sizes=Z, weeks=104,
               comments=len(cdf), labelled_comments=int((cdf.verified_reason != "").sum()),
               units_sold=int(sales_df.sales_units.sum()), true_demand=int(truth.true_demand_units.sum()),
               quality_issue_styles=int(sum(s["quality_issue"] != "none" for s in base_styles)),
               stores_changing_customer_mix=len(sim.CFG["drift"]["stores"]),
               external_feeds=["weather", "events", "competitor", "macro", "calendar"])
json.dump(summary, open(os.path.join(paths.RAW, "summary.json"), "w"), indent=2)
print(json.dumps(summary, indent=2))
