"""
Step 17 - Multi-department summary.

The pipeline is department-agnostic: sizes, size curves, categories, seasonality profiles and price
ranges come from the department config in sim.DEPARTMENTS (Kidswear and Babywear here). Run any step
with DEPT=<name>. This step collects the headline results of every department that has been run.
"""
import json, os
import paths, sim
from governance_lib import write_json

rows = []
for dept, cfg in sim.DEPARTMENTS.items():
    base = os.path.join(paths.ROOT, "results", dept)
    f = os.path.join(base, "forecast_metrics.json")
    if not os.path.exists(f):
        continue
    fm = json.load(open(f))
    sc = json.load(open(os.path.join(base, "size_curves.json"))) if os.path.exists(os.path.join(base, "size_curves.json")) else {}
    un = json.load(open(os.path.join(base, "unconstraining_diagnostics.json")))
    rows.append(dict(department=cfg["name"], sizes=cfg["sizes"], categories={k: v["season"] for k, v in cfg["categories"].items()},
                     styles=cfg["n_styles"] + cfg["n_new"], model_wape=fm["test"]["model_wape"], planner_rule_wape=fm["test"]["planner_rule_wape"],
                     improvement_vs_rule=fm["test"]["improvement_vs_rule_rel"], coverage=fm["test"]["p10_p90_coverage"],
                     unconstraining_wape_em=un["wape_vs_true_em_same_rows"], unconstraining_wape_v1=un["wape_vs_true_v1_share_scaling"],
                     wrong_size_chain=sc.get("variants", {}).get("A_chain_flat"), wrong_size_best=min(sc["variants"].values()) if sc else None,
                     stores_reassigned=[m["store_id"] for m in sc.get("stores_reassigned", [])]))
os.makedirs(os.path.join(paths.ROOT, "results"), exist_ok=True)
json.dump(dict(departments=rows), open(os.path.join(paths.ROOT, "results", "departments.json"), "w"), indent=2)
print(json.dumps(rows, indent=2))
