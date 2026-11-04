"""
Step 9 - Business-metric evaluation of each forecast.

WAPE says how close a forecast is; buyers care what it does to stock and money. Each forecast drives a
weekly replenishment decision for every style-store and is scored against true demand: margin, stock-out
rate, lost sales, leftover units and sell-through.

Replenishment happens in the full-price season, so this is scored on the in-season weeks 91-97, with
forecasts from models trained only on weeks 1-90. (Clearance weeks are a sell-down of stock already
bought; they are scored by the markdown optimiser in step 10.)

Newsvendor buffer: with price p, cost c and salvage s, the margin-optimal service level is
(p - c) / (p - s). Buffers are tested for the model to show the trade-off.
"""
import os
import numpy as np
import pandas as pd
import paths, sim
from governance_lib import write_json

va = pd.read_csv(paths.res("forecast_validation_predictions.csv"))
sp = pd.read_csv(os.path.join(paths.SPL, f"{paths.DEPT}_validation.csv"), usecols=["style_id", "store_id", "week_index", "discount"])
va = va.merge(sp, on=["style_id", "store_id", "week_index"]).merge(
    pd.read_csv(os.path.join(paths.RAW, "style_master.csv"))[["style_id", "full_price", "unit_cost"]], on="style_id")
price = va.full_price * (1 - va.discount)
salvage = va.unit_cost * sim.SALVAGE_RATIO
D = va.true_demand_units.values


def score(stock, name):
    stock = np.round(np.clip(stock, 0, None))
    sold = np.minimum(D, stock)
    left = stock - sold
    margin = (sold * price - stock * va.unit_cost + left * salvage).sum()
    return dict(policy=name, margin_rand=round(float(margin), 0), stockout_rate=round(float((D > stock).mean()), 4),
                lost_sales_pct=round(float((D - sold).sum() / D.sum()), 4), leftover_units=int(left.sum()),
                leftover_pct_of_stock=round(float(left.sum() / max(stock.sum(), 1)), 4),
                sell_through=round(float(sold.sum() / max(stock.sum(), 1)), 4), units_stocked=int(stock.sum()),
                wape=round(float(np.abs(D - va[name_col[name]] if name in name_col else 0).sum() / D.sum()), 4) if name in name_col else None)


name_col = {"Planner rule": "pred_rule", "LightGBM forecast": "pred_model", "LightGBM without external feeds": "pred_noext"}
rows = [score(va[c], n) for n, c in name_col.items()]
sweep = []
for b in (0.9, 1.0, 1.1, 1.2, 1.3, 1.5):
    r = score(va.pred_model * b, f"LightGBM x {b:.1f}")
    r["buffer"] = b
    sweep.append(r)
best_buf = max(sweep, key=lambda r: r["margin_rand"])
rule_buf = max([dict(score(va.pred_rule * b, f"Rule x {b:.1f}"), buffer=b) for b in (0.9, 1.0, 1.1, 1.2, 1.3, 1.5, 1.7, 2.0, 2.5)], key=lambda r: r["margin_rand"])
cr = float(((price - va.unit_cost) / (price - salvage)).clip(0, 1).mean())
out = dict(note="Weekly replenishment decisions in the full-price weeks 91-97 (models trained on weeks 1-90), scored against true demand. "
                "Margin = sales - cost of stock + salvage of leftovers.",
           policies=rows, buffer_sweep=sweep, best_model_buffer=best_buf["buffer"],
           best_rule_buffer=rule_buf["buffer"], critical_ratio_service_level=round(cr, 3),
           margin_uplift_best_model_vs_best_rule_rand=round(best_buf["margin_rand"] - rule_buf["margin_rand"], 0),
           margin_uplift_best_model_vs_best_rule_pct=round(best_buf["margin_rand"] / rule_buf["margin_rand"] - 1, 4),
           stockout_rate_best_model=best_buf["stockout_rate"], stockout_rate_best_rule=rule_buf["stockout_rate"])
write_json("business_metrics.json", out)
print(pd.DataFrame(rows + sweep + [rule_buf]).drop(columns=["wape"]).to_string(index=False))
print({k: v for k, v in out.items() if k not in ("policies", "buffer_sweep", "note")})
