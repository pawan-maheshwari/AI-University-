"""
Synthetic retail "world" used to generate sample data and to score policies.

Holds the TRUE demand function. Because the data is synthetic, policies (markdown plans,
allocations, trials) can be scored against ground truth; on real data that role is played
by a test-vs-control store trial.

Version 2 adds: department configs (Kidswear, Babywear), external drivers (weather, local
events, competitor promotions, consumer confidence), new-style launches (cold start),
fit-dependent size curves and stores whose customer mix changes between seasons.
"""
import os
import numpy as np

SEED = 42
N_WEEKS = 52
REGIONS = ["Gauteng", "Western Cape", "KZN", "Eastern Cape"]
FABRICS = ["Cotton", "Cotton-blend", "Polyester", "Fleece", "Denim"]
FITS = ["Regular", "Slim", "Relaxed"]
FIT_TILT = {"Regular": 0.0, "Slim": -0.12, "Relaxed": 0.12}     # slim cuts sell in younger sizes
SUPPLIERS = ["SUP-CPT-01", "SUP-DBN-02", "SUP-CN-03", "SUP-BD-04", "SUP-MU-05"]
QUALITY_ISSUES = ["fit", "fabric", "durability"]
COST_RATIO = 0.45            # unit cost as share of full price
SALVAGE_RATIO = 0.25         # leftover stock sold to a jobber at 25% of cost

DEPARTMENTS = {
    "kidswear": dict(
        name="Kidswear", prefix="KW", n_styles=60, n_new=12, new_launch_fw=40,
        sizes=["2-3Y", "3-4Y", "5-6Y", "7-8Y", "9-10Y", "11-12Y"],
        chain_curve=[0.14, 0.17, 0.19, 0.19, 0.17, 0.14],
        clusters={"A_young_families": [0.24, 0.24, 0.20, 0.14, 0.10, 0.08],
                  "B_balanced": [0.15, 0.17, 0.19, 0.18, 0.17, 0.14],
                  "C_older_kids": [0.07, 0.10, 0.15, 0.20, 0.24, 0.24]},
        drift={"from": "A_young_families", "to": "C_older_kids", "stores": [3, 9, 15]},
        categories={
            "T-shirts": dict(price=(99, 179), elast=2.2, base=9.0, season="summer", tilt=0.0),
            "Dresses": dict(price=(199, 349), elast=2.0, base=4.0, season="summer", tilt=0.0),
            "Schoolwear": dict(price=(149, 299), elast=1.2, base=5.0, season="school", tilt=0.12),
            "Jackets": dict(price=(299, 499), elast=1.6, base=3.0, season="winter", tilt=0.0),
            "Sleepwear": dict(price=(149, 249), elast=1.8, base=4.5, season="steady", tilt=0.0)}),
    "babywear": dict(
        name="Babywear", prefix="BW", n_styles=40, n_new=8, new_launch_fw=40,
        sizes=["0-3M", "3-6M", "6-12M", "12-18M", "18-24M"],
        chain_curve=[0.18, 0.22, 0.24, 0.20, 0.16],
        clusters={"A_new_parents": [0.30, 0.27, 0.22, 0.13, 0.08],
                  "B_balanced": [0.18, 0.22, 0.24, 0.20, 0.16],
                  "C_toddlers": [0.07, 0.13, 0.24, 0.29, 0.27]},
        drift={"from": "B_balanced", "to": "A_new_parents", "stores": [4, 13]},
        categories={
            "Bodysuits": dict(price=(79, 149), elast=1.8, base=7.0, season="steady", tilt=0.0),
            "Sleepsuits": dict(price=(99, 199), elast=1.6, base=5.0, season="steady", tilt=0.0),
            "Knitwear": dict(price=(149, 299), elast=1.7, base=3.0, season="winter", tilt=0.0),
            "Outerwear": dict(price=(199, 399), elast=1.5, base=2.5, season="winter", tilt=0.05),
            "Sets": dict(price=(129, 249), elast=2.0, base=4.0, season="summer", tilt=0.0)}),
}

CFG = None
SIZES = CHAIN_CURVE = CLUSTERS = CATEGORIES = None


def configure(dept):
    global CFG, SIZES, CHAIN_CURVE, CLUSTERS, CATEGORIES
    CFG = DEPARTMENTS[dept]
    SIZES = CFG["sizes"]
    CHAIN_CURVE = np.array(CFG["chain_curve"])
    CLUSTERS = {k: np.array(v) for k, v in CFG["clusters"].items()}
    CATEGORIES = CFG["categories"]


configure(os.environ.get("DEPT", "kidswear"))


# ------------------------------------------------------------------ calendar
def fy_week(week_index):
    return (np.asarray(week_index) - 1) % 52 + 1


def season_curve(category, fw):
    """Seasonal index by FY week (1..52). SA: winter Jun-Aug (week 1 = early July),
    summer Nov-Feb, back-to-school January (~FY wk 27-30), festive December (~wk 23-26)."""
    w = np.asarray(fw, dtype=float)
    winter = 0.5 + 0.5 * np.cos(2 * np.pi * (w - 2) / 52)
    summer = 1 - winter
    kind = CATEGORIES[category]["season"]
    if kind == "winter":
        idx = 0.35 + 1.3 * winter
    elif kind == "summer":
        idx = 0.45 + 1.1 * summer
    elif kind == "school":
        idx = 0.6 + 2.2 * np.exp(-0.5 * ((w - 28) / 1.6) ** 2) + 0.6 * np.exp(-0.5 * ((w - 41) / 1.2) ** 2)
    else:
        idx = 0.8 + 0.4 * winter
    festive = 1 + 0.45 * np.exp(-0.5 * ((w - 25) / 1.3) ** 2)
    return idx * festive


def payday_flag(fw):
    w = np.asarray(fw)
    return ((w * 12 / 52) % 1 > 0.77).astype(int)


def holiday_flag(fw):
    w = np.asarray(fw)
    return (((w >= 12) & (w <= 13)) | ((w >= 23) & (w <= 27)) | ((w >= 39) & (w <= 40))).astype(int)


def back_to_school_flag(fw):
    w = np.asarray(fw)
    return ((w >= 26) & (w <= 29)).astype(int)


# ------------------------------------------------------------------ world
def build_world(seed=SEED, n_stores=24):
    rng = np.random.default_rng(seed)
    cats = list(CATEGORIES)
    styles = []
    n_total = CFG["n_styles"] + CFG["n_new"]
    for i in range(n_total):
        c = cats[i % len(cats)]
        p = CATEGORIES[c]
        full_price = float(np.round(rng.uniform(*p["price"]) / 10) * 10 - 1)
        is_new = i >= CFG["n_styles"]
        styles.append(dict(
            style_id=f"{CFG['prefix']}{1000 + i}", category=c,
            fabric=str(rng.choice(FABRICS)), fit=str(rng.choice(FITS)), supplier=str(rng.choice(SUPPLIERS)),
            colour=str(rng.choice(["Navy", "Pink", "Grey", "Green", "Yellow", "Red", "White"])),
            full_price=full_price, unit_cost=round(full_price * COST_RATIO, 2),
            appeal=float(rng.lognormal(0, 0.35)), elasticity=float(p["elast"] * rng.uniform(0.85, 1.15)),
            quality_issue=str(rng.choice(QUALITY_ISSUES)) if rng.random() < 0.2 else "none",
            size_tilt=float(rng.normal(0, 0.15)), base_return=float(rng.uniform(0.03, 0.11)),
            launch_wi=int(52 + CFG["new_launch_fw"]) if is_new else 1, is_new=bool(is_new),
        ))
    names = list(CLUSTERS)
    stores = []
    for j in range(n_stores):
        c = names[j % len(names)]
        c26 = CFG["drift"]["to"] if j in CFG["drift"]["stores"] else c
        stores.append(dict(store_id=f"S{101 + j}", cluster=c, cluster_fy2026=c26,
                           traffic=float(rng.lognormal(0, 0.3)), region=str(rng.choice(REGIONS))))
    return dict(styles=styles, stores=stores)


def build_external(stores, n_weeks=104, seed=SEED + 7):
    """External drivers by week_index (1..n_weeks)."""
    rng = np.random.default_rng(seed)
    R, cats = len(REGIONS), list(CATEGORIES)
    anom = np.zeros((R, n_weeks))
    for r in range(R):
        a = 0.0
        for t in range(n_weeks):
            a = 0.6 * a + rng.normal(0, 2.2)
            anom[r, t] = a
    fw = fy_week(np.arange(1, n_weeks + 1))
    base = np.array([16.5, 17.0, 21.0, 18.0])[:, None]
    temp = base - 6.0 * np.cos(2 * np.pi * (fw - 2) / 52)[None, :] + anom
    temp_fc = anom + rng.normal(0, 1.0, anom.shape)                 # what a 1-week-ahead forecast would say
    event = (rng.random((len(stores), n_weeks)) < 0.03).astype(int)
    comp = np.zeros((R, len(cats), n_weeks))
    for r in range(R):
        for c in range(len(cats)):
            t = 0
            while t < n_weeks:
                if rng.random() < 0.06:
                    d = rng.uniform(0.15, 0.4)
                    comp[r, c, t:t + 3] = d
                    t += 3
                else:
                    t += 1
            comp[r, c, (fw >= 46)] = np.maximum(comp[r, c, (fw >= 46)], 0.25)   # competitors clear winter too
    cci = np.cumsum(rng.normal(0, 0.8, n_weeks))
    cci = np.clip(cci - cci.mean(), -8, 8)
    return dict(anom=anom, temp=temp, temp_fc=temp_fc, event=event, comp=comp, cci=cci)


EXT = None


def load_external(path):
    global EXT
    z = np.load(path)
    EXT = {k: z[k] for k in z.files}
    return EXT


def ext_multiplier(style, store, store_idx, wi, ext):
    wi = np.asarray(wi)
    t = wi - 1
    r = REGIONS.index(store["region"])
    c = list(CATEGORIES).index(style["category"])
    kind = CATEGORIES[style["category"]]["season"]
    k = {"winter": -0.045, "summer": 0.035, "steady": -0.015, "school": 0.0}[kind]
    m = np.exp(k * ext["anom"][r, t])
    m = m * (1 + 0.35 * ext["event"][store_idx, t])
    m = m * np.exp(-0.7 * ext["comp"][r, c, t])
    m = m * np.exp(0.015 * ext["cci"][t])
    return m


def size_share(style, store, cluster=None):
    base = CLUSTERS[cluster or store["cluster"]].copy()
    tilt = style["size_tilt"] + CATEGORIES[style["category"]]["tilt"] + FIT_TILT[style["fit"]]
    w = base * np.exp(tilt * np.linspace(-1, 1, len(SIZES)))
    return w / w.sum()


def true_mean_demand(style, store, week_index, discount, size_idx=None, store_idx=0, ext=None):
    """Expected unit demand for one style-store(-size) over week_index (1..104)."""
    ext = EXT if ext is None else ext
    wi = np.asarray(week_index)
    fw = fy_week(wi)
    cat = CATEGORIES[style["category"]]
    mu = cat["base"] * style["appeal"] * store["traffic"] * season_curve(style["category"], fw)
    mu = mu * (1 + 0.2 * payday_flag(fw)) * (1 + 0.25 * holiday_flag(fw))
    mu = mu * np.power(1 - np.asarray(discount, dtype=float), -style["elasticity"])
    if ext:
        mu = mu * ext_multiplier(style, store, store_idx, wi, ext)
    if style["quality_issue"] != "none":
        mu = mu * np.exp(-0.9 * (fw - 1) / 52)
    mu = mu * (wi >= style.get("launch_wi", 1))
    if size_idx is not None:
        s25 = size_share(style, store, store["cluster"])[size_idx]
        s26 = size_share(style, store, store.get("cluster_fy2026", store["cluster"]))[size_idx]
        mu = mu * np.where(wi > 52, s26, s25)
    return mu


def return_rate(style):
    return style["base_return"] + (0.05 if style["quality_issue"] != "none" else 0.0)
