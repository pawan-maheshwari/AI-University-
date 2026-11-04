"""
Step 15 - Integration adapters round trip.

Writes two weeks of the sample data out as source-system extracts (POS daily sales with returns as
negative quantities, inventory snapshots, ERP item master by SKU, ERP price events), using the column
names in config/source_mappings.json. The adapters rebuild the contract tables from those extracts; the
result must pass the data contracts and match the original rows exactly.
"""
import json, os
import numpy as np
import pandas as pd
import paths, adapters, contracts
from governance_lib import write_json, audit_log

rng = np.random.default_rng(5)
WEEKS = [97, 98]
sales = pd.read_csv(os.path.join(paths.RAW, "sales_weekly.csv.gz"))
styles = pd.read_csv(os.path.join(paths.RAW, "style_master.csv"))
sub = sales[sales.week_index.isin(WEEKS)].copy()
sub["sku"] = sub.style_id + "-" + sub["size"]
M = adapters.MAPPINGS
inv_m = {v: k for k, v in M["inventory"]["columns"].items()}

# POS: spread each week's sales and returns over days (returns as negative quantity lines)
pos = []
for r in sub.itertuples(index=False):
    d0 = pd.Timestamp(r.week_start)
    if r.sales_units:
        for day, q in zip(*np.unique(rng.integers(0, 7, r.sales_units), return_counts=True)):
            pos.append((r.store_id, r.sku, (d0 + pd.Timedelta(days=int(day))).date(), int(q)))
    if r.return_units:
        for day, q in zip(*np.unique(rng.integers(0, 7, r.return_units), return_counts=True)):
            pos.append((r.store_id, r.sku, (d0 + pd.Timedelta(days=int(day))).date(), -int(q)))
pm = M["pos_daily"]["columns"]
pos = pd.DataFrame(pos, columns=[pm["store_id"], pm["sku"], pm["date"], pm["qty"]])
im = M["inventory"]["columns"]
inv = pd.DataFrame({im["store_id"]: sub.store_id, im["sku"]: sub.sku, im["snapshot_date"]: sub.week_start, im["on_hand"]: sub.stock_on_hand_start})
em = M["erp_items"]["columns"]
items = sub[["sku", "style_id", "size"]].drop_duplicates().merge(styles, on="style_id")
erp = pd.DataFrame({em[k]: items[k if k != "launch_date" else "launch_week_start"] for k in em})
xm = M["erp_prices"]["columns"]
pr = sub.groupby(["style_id", "week_start"]).selling_price.first().reset_index()
prices = pd.DataFrame({xm["style_id"]: pr.style_id, xm["effective_date"]: pr.week_start, xm["price"]: pr.selling_price})
for name, df in (("pos_daily", pos), ("inventory_snapshots", inv), ("erp_items", erp), ("erp_prices", prices)):
    df.to_csv(os.path.join(paths.SRC, f"{name}.csv.gz"), index=False)

# adapters -> contract tables
st, sku_map = adapters.erp_items(pd.read_csv(os.path.join(paths.SRC, "erp_items.csv.gz")))
p = adapters.pos_daily(pd.read_csv(os.path.join(paths.SRC, "pos_daily.csv.gz")), sku_map)
i = adapters.inventory(pd.read_csv(os.path.join(paths.SRC, "inventory_snapshots.csv.gz")), sku_map)
x = adapters.erp_prices(pd.read_csv(os.path.join(paths.SRC, "erp_prices.csv.gz")), st)
rebuilt = adapters.build_sales_weekly(p, i, x, st)
stores = pd.read_csv(os.path.join(paths.RAW, "store_master.csv"))
findings = contracts.validate_table(rebuilt, "sales_weekly", {"store_master": stores, "style_master": st}) + \
    contracts.validate_table(st, "style_master")
key = ["week_index", "store_id", "style_id", "size"]
orig = sub.sort_values(key).reset_index(drop=True)
reb = rebuilt.sort_values(key).reset_index(drop=True)
cmp_cols = ["sales_units", "return_units", "stock_on_hand_start"]
match = {c: bool((orig[c].values == reb[c].values).all()) for c in cmp_cols}
match["discount"] = bool(np.allclose(orig.discount.values, reb.discount.values, atol=0.001))
out = dict(weeks=WEEKS, source_rows={"pos_daily": len(pos), "inventory_snapshots": len(inv), "erp_items": len(erp), "erp_prices": len(prices)},
           rebuilt_rows=len(rebuilt), original_rows=len(orig), contract_errors=[f for f in findings if f["severity"] == "error"],
           exact_match=match, passed=all(match.values()) and len(rebuilt) == len(orig) and not any(f["severity"] == "error" for f in findings),
           mappings="config/source_mappings.json")
write_json("adapter_roundtrip.json", out)
audit_log("adapters_verified", passed=out["passed"], source_rows=out["source_rows"])
print(json.dumps(out, indent=2))
