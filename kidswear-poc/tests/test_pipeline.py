"""
Unit and integration checks. Run: python3 tests/test_pipeline.py  (no test framework needed; pytest also works).
Unit tests use small synthetic inputs; integration tests read the results of the last pipeline run.
"""
import json, os, sys, shutil, tempfile
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("DEPT", "kidswear")
import paths, contracts, adapters, governance_lib as gl, foundation  # noqa: E402

RES = lambda n: json.load(open(paths.res(n)))


def test_contract_catches_defects():
    stores = pd.DataFrame(dict(store_id=["S1"], cluster=["A"], region=["X"]))
    styles = pd.DataFrame(dict(style_id=["KW1"], category=["T-shirts"], supplier=["V"], full_price=[100.0], unit_cost=[40.0], launch_week_start=["2024-07-01"]))
    good = pd.DataFrame(dict(season="FY2025", week_index=[1, 2], week_start=["2024-07-01", "2024-07-08"], fy_week=[1, 2], store_id="S1", style_id="KW1",
                             size="2-3Y", full_price=100.0, selling_price=100.0, discount=0.0, stock_on_hand_start=[5, 5], sales_units=[3, 5], return_units=[0, 1]))
    t = {"store_master": stores, "style_master": styles}
    assert not [f for f in contracts.validate_table(good, "sales_weekly", t) if f["severity"] == "error"]
    bad = good.copy(); bad.loc[0, "sales_units"] = 9; bad.loc[1, "store_id"] = "S9"
    checks = {f["check"] for f in contracts.validate_table(bad, "sales_weekly", t)}
    assert "rule:sales_not_above_stock" in checks and "reference:store_id" in checks


def test_audit_chain_detects_tampering():
    d = tempfile.mkdtemp()
    try:
        p = os.path.join(d, "a.jsonl")
        old = gl.AUDIT
        gl.AUDIT = p
        for i in range(5):
            gl.audit_log("e", n=i)
        gl.AUDIT = old
        assert gl.verify_audit(p)["ok"]
        lines = open(p).read().splitlines()
        e = json.loads(lines[2]); e["detail"]["n"] = 99
        lines[2] = json.dumps(e, sort_keys=True, separators=(",", ":"))
        open(p, "w").write("\n".join(lines) + "\n")
        r = gl.verify_audit(p)
        assert not r["ok"] and r["broken_at_line"] == 3
    finally:
        shutil.rmtree(d)


def test_psi():
    rng = np.random.default_rng(0)
    a = rng.normal(0, 1, 5000)
    assert gl.psi(a, rng.normal(0, 1, 5000)) < 0.05
    assert gl.psi(a, rng.normal(1.5, 1, 5000)) > 0.25


def test_adapters_round_trip_small():
    items = pd.DataFrame({"SKU": ["KW1-2-3Y"], "STYLE": ["KW1"], "SIZE_DESC": ["2-3Y"], "SUB_DEPT": ["T-shirts"], "FABRIC": ["Cotton"], "FIT": ["Slim"],
                          "VENDOR": ["V"], "COLOUR": ["Red"], "RSP": [100.0], "LANDED_COST": [40.0], "FIRST_RECEIPT_DATE": ["2024-07-01"]})
    st, sku = adapters.erp_items(items)
    pos = pd.DataFrame({"STORE_CODE": ["S1", "S1", "S1"], "ARTICLE_SIZE_CODE": ["KW1-2-3Y"] * 3, "TRADING_DATE": ["2024-07-01", "2024-07-03", "2024-07-04"], "NET_QTY": [2, 1, -1]})
    inv = pd.DataFrame({"LOCATION": ["S1"], "SKU": ["KW1-2-3Y"], "SNAPSHOT_DATE": ["2024-07-01"], "SOH_UNITS": [10]})
    pr = pd.DataFrame({"STYLE": ["KW1"], "EFFECTIVE_FROM": ["2024-07-01"], "SELLING_PRICE": [80.0]})
    out = adapters.build_sales_weekly(adapters.pos_daily(pos, sku), adapters.inventory(inv, sku), adapters.erp_prices(pr, st), st)
    r = out.iloc[0]
    assert (r.sales_units, r.return_units, r.stock_on_hand_start, round(r.discount, 2)) == (3, 1, 10, 0.2)


def test_nnls_and_fallbacks():
    w = foundation.nnls_weights(np.c_[np.arange(10.0), np.ones(10)], 2 * np.arange(10.0))
    assert abs(w[0] - 2) < 1e-6
    try:
        foundation.load_timesfm()
        assert False
    except foundation.FoundationModelUnavailable:
        pass


def test_results_integration():
    v = RES("data_validation.json"); assert v["passed"] and v["self_test"]["passed"]
    u = RES("unconstraining_diagnostics.json"); assert u["converged"] and u["wape_vs_true_em_same_rows"] < u["wape_vs_true_v1_share_scaling"]
    f = RES("forecast_metrics.json"); assert f["test"]["model_wape"] < f["test"]["planner_rule_wape"] and 0.7 < f["test"]["p10_p90_coverage"] < 0.9
    h = RES("hierarchy_reconciliation.json")
    assert all(h["results"][m]["max_coherence_gap_units"] < 0.01 for m in ("bottom_up", "top_down", "mint_wls"))
    s = RES("size_curves.json"); assert s["variants"]["E_dynamic_plus_fit"] < s["variants"]["A_chain_flat"]
    assert sorted(x["store_id"] for x in s["stores_reassigned"]) == s["stores_that_truly_changed"]
    look = pd.read_csv(paths.res("size_curve_lookup.csv")); assert np.allclose(look[[c for c in look.columns if c not in ("style_id", "store_id", "cluster")]].sum(1), 1, atol=1e-3)
    p = RES("markdown_pack.json")
    assert all(x["constraints"]["never_decreases"] and x["constraints"]["max_depth_ok"] for x in p["styles"])
    assert all(x["cash_p10"] <= x["expected_cash"] + 1 for x in p["styles"])
    a = RES("adapter_roundtrip.json"); assert a["passed"]
    g = RES("governance_report.json"); assert g["audit_chain"]["ok"] and g["tamper_test"]["detected"]
    o = RES("override_feedback.json"); assert o["overall"]["learned_wape"] <= o["overall"]["accept_all_wape"]
    t = RES("trial_preregistration.json"); assert len(t["pairs"]) * 2 == 24 and t["registration_hash"]


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print("PASS", name)
            except Exception as e:  # noqa: BLE001
                fails += 1; print("FAIL", name, repr(e))
    print(f"{fails} failed")
    sys.exit(1 if fails else 0)
