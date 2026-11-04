"""
Integration adapters: turn source-system extracts into the pipeline's contract tables.

    pos_daily      -> sales_weekly (sales and returns)        POS: one row per store, SKU, day
    inventory      -> stock_on_hand_start                     inventory snapshots: store, SKU, date, on hand
    erp_items      -> style_master                            ERP item master: SKU, style, attributes, cost, price
    erp_prices     -> discount / selling_price                ERP price events: style, effective date, price

Column names differ between systems, so every adapter takes a mapping (config/source_mappings.json).
The outputs are validated with the same data contracts as the sample data.
"""
import json, os
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
MAPPINGS = json.load(open(os.path.join(HERE, "config", "source_mappings.json")))


def _rename(df, system):
    m = MAPPINGS[system]["columns"]
    missing = [src for src in m.values() if src not in df.columns]
    if missing:
        raise ValueError(f"{system}: source columns missing {missing}")
    return df.rename(columns={src: dst for dst, src in m.items()})


def week_start(dates, fy_start="2024-07-01"):
    d = pd.to_datetime(dates)
    k = (d - pd.Timestamp(fy_start)).dt.days // 7
    return pd.Timestamp(fy_start) + pd.to_timedelta(k * 7, unit="D"), k + 1


def erp_items(df):
    x = _rename(df, "erp_items")
    st = x.groupby("style_id").agg(category=("category", "first"), fabric=("fabric", "first"), fit=("fit", "first"),
                                   supplier=("supplier", "first"), colour=("colour", "first"), full_price=("full_price", "first"),
                                   unit_cost=("unit_cost", "first"), launch_week_start=("launch_date", "min")).reset_index()
    st["launch_week_start"] = week_start(st.launch_week_start)[0].dt.date.astype(str)
    sku = x[["sku", "style_id", "size"]].drop_duplicates()
    return st, sku


def pos_daily(df, sku_map):
    x = _rename(df, "pos_daily").merge(sku_map, on="sku", how="left")
    if x.style_id.isna().any():
        raise ValueError(f"pos_daily: {int(x.style_id.isna().sum())} rows with SKUs not in the item master")
    x["week_start"], x["week_index"] = week_start(x.date)
    x["sales_units"] = x.qty.clip(lower=0)
    x["return_units"] = (-x.qty).clip(lower=0)
    return x.groupby(["week_index", "week_start", "store_id", "style_id", "size"], as_index=False)[["sales_units", "return_units"]].sum()


def inventory(df, sku_map):
    x = _rename(df, "inventory").merge(sku_map, on="sku", how="left")
    x["week_start"], x["week_index"] = week_start(x.snapshot_date)
    x = x.sort_values("snapshot_date").groupby(["week_index", "store_id", "style_id", "size"], as_index=False).on_hand.first()
    return x.rename(columns={"on_hand": "stock_on_hand_start"})


def erp_prices(df, items):
    x = _rename(df, "erp_prices")
    x["week_start"], x["week_index"] = week_start(x.effective_date)
    x = x.sort_values("effective_date").groupby(["style_id", "week_index"], as_index=False).price.last()
    x = x.merge(items[["style_id", "full_price"]], on="style_id")
    x["discount"] = (1 - x.price / x.full_price).round(4).clip(0, 0.9)
    return x.rename(columns={"price": "selling_price"})[["style_id", "week_index", "selling_price", "discount"]]


def build_sales_weekly(pos, inv, prices, items):
    s = inv.merge(pos.drop(columns="week_start"), on=["week_index", "store_id", "style_id", "size"], how="left").fillna({"sales_units": 0, "return_units": 0})
    s = s.merge(prices, on=["style_id", "week_index"], how="left").merge(items[["style_id", "full_price"]], on="style_id")
    s["discount"] = s.discount.fillna(0.0); s["selling_price"] = s.selling_price.fillna(s.full_price)
    s["week_start"] = (pd.Timestamp("2024-07-01") + pd.to_timedelta((s.week_index - 1) * 7, unit="D")).dt.date.astype(str)
    s["fy_week"] = (s.week_index - 1) % 52 + 1
    s["season"] = np.where(s.week_index <= 52, "FY2025", np.where(s.week_index <= 104, "FY2026", "FY2027"))
    for c in ("sales_units", "return_units", "stock_on_hand_start"):
        s[c] = s[c].astype(int)
    cols = ["season", "week_index", "week_start", "fy_week", "store_id", "style_id", "size", "full_price", "selling_price", "discount",
            "stock_on_hand_start", "sales_units", "return_units"]
    return s[cols].sort_values(["week_index", "store_id", "style_id", "size"]).reset_index(drop=True)
