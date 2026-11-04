"""
Step 18 - Build the planner app (../kidswear-planner.html) and the roadmap status from pipeline results.

Everything the app shows comes from results/ and governance/. The bundle can also be exported as JSON and
uploaded into the app to review another run.
"""
import datetime, json, os
import numpy as np
import pandas as pd
import paths, sim

R = lambda n: json.load(open(paths.res(n)))
fm, ens, hier, biz = R("forecast_metrics.json"), R("foundation_ensemble.json"), R("hierarchy_reconciliation.json"), R("business_metrics.json")
un, val, qn, sc = R("unconstraining_diagnostics.json"), R("data_validation.json"), R("quality_nlp_metrics.json"), R("size_curves.json")
md, pack, scen = R("markdown_metrics.json"), R("markdown_pack.json"), R("markdown_scenarios.json")
alloc, ovr, trial, prereg = R("allocation.json"), R("override_feedback.json"), R("trial_results.json"), R("trial_preregistration.json")
cad, adp, gov, cards = R("retrain_cadence.json"), R("adapter_roundtrip.json"), R("governance_report.json"), R("driver_cards.json")
qd = R("quality_dashboard.json")
deps = json.load(open(os.path.join(paths.ROOT, "results", "departments.json"))) if os.path.exists(os.path.join(paths.ROOT, "results", "departments.json")) else {"departments": []}
sm = pd.read_csv(os.path.join(paths.RAW, "style_master.csv"))
n_new = int((pd.to_datetime(sm.launch_week_start) > pd.Timestamp("2024-07-01")).sum())
pct = lambda v, d=1: f"{v * 100:.{d}f}%"
rand = lambda v: f"R{v / 1e6:.2f}m" if abs(v) >= 1e6 else f"R{v / 1e3:.0f}k"
mt = md["matched_sell_through"]

ROADMAP = [
    dict(iteration=0, title="Foundation stabilisation", features=[
        dict(name="Data contracts & validation", file="contracts.py, 02_validate_data.py, config/data_contracts.json",
             result=f"{val['errors']} errors on {sum(t['rows'] for t in val['tables'].values()):,} rows; self-test caught {len(val['self_test']['defects_caught'])}/{len(val['self_test']['defects_injected'])} injected defects; pipeline stops on any error"),
        dict(name="Enhanced demand unconstraining", file="04_prepare_features.py",
             result=f"EM negative-binomial: demand-estimate error {pct(un['wape_vs_true_em_same_rows'])} vs {pct(un['wape_vs_true_v1_share_scaling'])} (v1); bias {pct(un['bias_em'])} vs {pct(un['bias_v1'])}; quality score per row"),
        dict(name="Model monitoring baseline", file="05_demand_forecast.py, governance_lib.py",
             result=f"WAPE, bias, P10-P90 coverage ({pct(fm['test']['p10_p90_coverage'])}) and PSI drift vs same weeks last year; shifted: {', '.join(fm['drift']['shifted'][:3]) or 'none'}"),
        dict(name="Explainability pack", file="05_demand_forecast.py -> driver_cards.json",
             result=f"SHAP global ranking plus driver cards for {len(cards['styles'])} styles and {len(cards['stores'])} stores (top drivers up and down)"),
        dict(name="Reproducible experiment tracking", file="governance_lib.py -> governance/model_registry.jsonl",
             result=f"data, feature and model versions plus all {fm['search']['trials']} trials recorded for every run ({len(gov['registry'])} registered runs)"),
    ]),
    dict(iteration=1, title="Accuracy & robustness uplift", features=[
        dict(name="Hierarchical reconciliation", file="07_hierarchy.py",
             result=f"bottom-up, top-down and MinT tested on 4 levels; {hier['recommended'].replace('_', '-')} best; chain-total error {pct(hier['results'][hier['recommended']]['total'])} vs {pct(hier['results']['base']['total'])} unreconciled; coherent by construction"),
        dict(name="Richer external features", file="01_generate_data.py (feeds), 04_prepare_features.py",
             result=f"weather, events, competitor promotions, consumer confidence, school calendar, payday + interactions: {fm['test']['external_features_gain_pts']:+.1f} pts accuracy"),
        dict(name="Foundation-model ensemble", file="foundation.py, 06_foundation_ensemble.py",
             result=f"Chronos/TimesFM adapters ready; weights unavailable here so zero-shot fallbacks used; stacked forecast {pct(ens['segments']['all']['stacked'])} vs LightGBM {pct(ens['segments']['all']['lightgbm'])}"),
        dict(name="Improved size-curve modelling", file="08_size_curves.py",
             result=f"dynamic clusters + fit-aware curves: wrong-size units {pct(sc['variants']['E_dynamic_plus_fit'])} vs {pct(sc['variants']['A_chain_flat'])} chain; found all {len(sc['stores_that_truly_changed'])} stores whose mix changed; 8-weekly updates {pct(sc['update_cadence']['every_8_weeks_mean'])} vs {pct(sc['update_cadence']['once_a_season_mean'])} once a season"),
        dict(name="Business-metric evaluation", file="09_business_metrics.py",
             result=f"replenishment margin {biz['margin_uplift_best_model_vs_best_rule_pct']:+.0%} vs best planner rule; stock-out rate {pct(biz['stockout_rate_best_model'], 0)} vs {pct(biz['stockout_rate_best_rule'], 0)}; newsvendor service level {pct(biz['critical_ratio_service_level'], 0)}"),
    ]),
    dict(iteration=2, title="Planner experience & decision support", features=[
        dict(name="Interactive planning UI", file="kidswear-planner.html (18_build_planner.py)", result="this app: forecasts, size curves, markdown pack, quality, trial, operations; upload another run's bundle to review it"),
        dict(name="Override & feedback loop", file="12_overrides.py + Forecasts tab",
             result=f"overrides captured with reasons and exported in the ingest format; trust learned per reason: error on overridden forecasts {pct(ovr['overall']['learned_wape'])} vs {pct(ovr['overall']['accept_all_wape'])} accepting all and {pct(ovr['overall']['model_only_wape'])} ignoring all"),
        dict(name="Scenario simulation", file="Markdown tab (markdown_scenarios.json)", result="change weekly discounts, stock level or size mix and see cash, sell-through and leftovers instantly"),
        dict(name="Markdown recommendation pack", file="10_markdown.py -> markdown_pack.json",
             result=f"{len(pack['styles'])} styles with multi-step paths, P10-P90 cash range, current-plan comparison and constraint checks"),
        dict(name="Quality-gap dashboard", file="03_quality_nlp.py -> quality_dashboard.json",
             result=f"ranked by quality return value with themes and actions; found {pct(qn['recall_at_n'], 0)} of defective lines vs {pct(qn['baseline_return_rate_only_recall_at_n'], 0)} by return rate"),
    ]),
    dict(iteration=3, title="Real-world validation & operationalisation", features=[
        dict(name="Store test-vs-control trial design", file="13_store_trial.py",
             result=f"{prereg['power']['pairs']} matched pairs, randomised; pre-registered and hashed; MDE {pct(prereg['power']['minimum_detectable_effect_pct'], 0)}; {prereg['power']['pairs_needed_for_expected_effect']} pairs needed for the expected effect"),
        dict(name="Closed-loop outcome tracking", file="13_store_trial.py",
             result=f"simulated FY2027 trial: {trial['effect_pct_of_control']:+.1%} gross profit per store (p = {trial['permutation_p_one_sided']}); prediction calibration {trial['closed_loop']['calibration_ratio']}; outcomes saved for retraining"),
        dict(name="Automated retraining cadence", file="14_retrain_cadence.py, retrain.py, .github/workflows/kidswear-retrain.yml",
             result=f"{cad['chosen']['policy']} retraining chosen: error {pct([p for p in cad['policies'] if p['policy'] == cad['chosen']['policy']][0]['wape'])} vs {pct([p for p in cad['policies'] if p['policy'] == 'never'][0]['wape'])} never retrained; drift + error triggers"),
        dict(name="Integration adapters", file="adapters.py, 15_adapters.py, config/source_mappings.json",
             result=f"POS, inventory and ERP extracts rebuilt into contract tables: exact match {'yes' if adp['passed'] else 'no'} on {adp['rebuilt_rows']:,} rows"),
        dict(name="Governance & audit", file="governance_lib.py, 16_governance_report.py",
             result=f"hash-chained audit trail ({gov['audit_chain']['entries']} entries, {'intact' if gov['audit_chain']['ok'] else 'BROKEN'}); edited entry {'caught' if gov['tamper_test']['detected'] else 'missed'} by the tamper test; full model lineage"),
    ]),
    dict(iteration=4, title="Scale & differentiation", features=[
        dict(name="Multi-department support", file="sim.py DEPARTMENTS, DEPT=babywear", result=f"{len(deps['departments'])} departments run through the same pipeline: " + ", ".join(d["department"] for d in deps["departments"])),
        dict(name="Allocation & replenishment", file="11_allocation.py",
             result=f"forecast + size-curve allocation fill rate {pct(alloc['allocation_split']['forecast_and_size_curves'])} vs {pct(alloc['allocation_split']['current_practice'])}; {alloc['transfers']['moves']} transfers worth {rand(alloc['transfers']['net_benefit_rand'])} net"),
        dict(name="Cold-start & new styles", file="foundation.py (analog), 06_foundation_ensemble.py",
             result=f"attribute-similarity analog + stacking for {n_new} new styles: {pct(ens['segments']['new_styles']['stacked'])} vs LightGBM {pct(ens['segments']['new_styles']['lightgbm'])}"),
        dict(name="Advanced markdown optimiser", file="10_markdown.py",
             result=f"constrained multi-step optimiser with competitor prices and season length: {rand(mt['uplift_vs_actual']['v2_quality_linked'])} gross profit vs today at matched sell-through (two-step grid {rand(mt['uplift_vs_actual']['v1_grid'])})"),
        dict(name="Continuous learning from returns", file="03_quality_nlp.py, 04 + 10 links",
             result=f"text model refreshed with new-season comments: {qn['continuous_learning']['refresh_gain_pts']:+.1f} pts F1 ({qn['continuous_learning']['frozen']['test_macro_f1_new_phrasing']:.2f} -> {qn['continuous_learning']['refreshed']['test_macro_f1_new_phrasing']:.2f} on new phrasing); quality signal feeds the forecast and quality-linked markdowns"),
    ]),
]

# forecast data
spl = lambda n: pd.read_csv(os.path.join(paths.SPL, f"{paths.DEPT}_{n}.csv"), usecols=["style_id", "store_id", "week_index", "demand_est", "sales_units"])
hist = pd.concat([spl("train"), spl("validation")])
te = pd.read_csv(paths.res("forecast_test_predictions.csv"))
series = {}
for sid, g in hist.groupby("style_id"):
    w = g.groupby("week_index")[["demand_est", "sales_units"]].sum()
    t = te[te.style_id == sid].groupby("week_index")[["pred_final", "pred_p10", "pred_p90", "pred_rule", "true_demand_units", "sales_units"]].sum()
    series[sid] = dict(hist_weeks=[int(x) for x in w.index], demand=[round(float(x), 1) for x in w.demand_est], sales=[int(x) for x in w.sales_units],
                       test_weeks=[int(x) for x in t.index], forecast=[round(float(x), 1) for x in t.pred_final], p10=[round(float(x), 1) for x in t.pred_p10],
                       p90=[round(float(x), 1) for x in t.pred_p90], rule=[round(float(x), 1) for x in t.pred_rule],
                       actual=[int(x) for x in t.true_demand_units], test_sales=[int(x) for x in t.sales_units])
store_fc = {sid: {st: [round(float(x), 1) for x in g2.sort_values("week_index").pred_final] for st, g2 in g.groupby("store_id")}
            for sid, g in te.groupby("style_id")}
audit_lines = open(os.path.join(paths.GOV, "audit_log.jsonl")).read().splitlines()

bundle = dict(
    meta=dict(department=sim.CFG["name"], generated=datetime.date.today().isoformat(), data_version=val["data_version"],
              model_run=fm["run_id"], test_weeks="98-104 (FY2026 weeks 46-52, winter clearance)", sizes=sim.SIZES,
              note="Sample data: synthetic retail data built to behave like real data. Results show the methods work; they are not any retailer's figures."),
    roadmap=ROADMAP,
    headline=dict(forecast_wape=ens["segments"]["all"]["stacked"], rule_wape=fm["test"]["planner_rule_wape"], coverage=fm["test"]["p10_p90_coverage"],
                  wrong_size=sc["variants"]["E_dynamic_plus_fit"], wrong_size_chain=sc["variants"]["A_chain_flat"],
                  markdown_gp_uplift=mt["uplift_vs_actual"]["v2_quality_linked"], markdown_gp_actual=mt["actual_gross_profit"],
                  margin_uplift=biz["margin_uplift_best_model_vs_best_rule_pct"], defects_found=qn["recall_at_n"],
                  transfers_net=alloc["transfers"]["net_benefit_rand"], unconstraining_em=un["wape_vs_true_em_same_rows"], unconstraining_v1=un["wape_vs_true_v1_share_scaling"]),
    forecast=dict(metrics=fm["test"], by_category=fm["by_category"], ensemble=ens, hierarchy=hier, business=biz, series=series, store_forecast=store_fc,
                  styles=sm[["style_id", "category", "fabric", "fit", "supplier", "full_price"]].to_dict("records"),
                  stores=pd.read_csv(os.path.join(paths.RAW, "store_master.csv")).to_dict("records"),
                  override_reasons=ovr["reasons"], override_learned_trust=ovr["learned_trust"], override_columns=ovr["csv_contract"], override_results=ovr),
    drivers=cards, unconstraining={k: v for k, v in un.items() if k != "history"},
    sizes={k: v for k, v in sc.items()}, markdown=dict(metrics=md, pack=pack, scenarios=scen), allocation=alloc, quality=dict(metrics=qn, dashboard=qd),
    trial=dict(prereg=prereg, results=trial, stores=pd.read_csv(paths.res("trial_store_outcomes.csv")).to_dict("records")),
    operations=dict(validation={k: v for k, v in val.items() if k != "tables"}, validation_tables={k: dict(rows=v["rows"], findings=len(v["findings"])) for k, v in val["tables"].items()},
                    drift=fm["drift"], retrain=cad, adapters=adp, governance={k: v for k, v in gov.items() if k != "recent_events"},
                    audit_lines=audit_lines[-120:], retrain_policy=json.load(open(os.path.join(paths.ROOT, "config", "retrain_policy.json")))),
    departments=deps["departments"],
)


def clean(o):
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, list):
        return [clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        return None if not np.isfinite(o) else float(o)
    return o


payload = json.dumps(clean(bundle), separators=(",", ":"), allow_nan=False)
json.dump(clean(dict(roadmap=ROADMAP)), open(paths.res("roadmap_status.json"), "w"), indent=2)
tpl = open(os.path.join(paths.ROOT, "planner", "template.html"), encoding="utf-8").read()
js = open(os.path.join(paths.ROOT, "planner", "planner.js"), encoding="utf-8").read()
assert "</script" not in payload.lower() and "</script" not in js.lower()
out = tpl.replace("__BUNDLE__", payload).replace("__APP__", js)
target = os.path.join(paths.ROOT, "..", "kidswear-planner.html")
open(target, "w", encoding="utf-8").write(out)
open(paths.res("planner_bundle.json"), "w").write(payload)
print("wrote", os.path.normpath(target), f"{len(out.encode()) / 1e6:.2f} MB")
