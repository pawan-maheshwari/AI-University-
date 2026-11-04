"""
Retraining trigger, used by the scheduled workflow (.github/workflows/kidswear-retrain.yml).

    python retrain.py check      exit 0 = no retrain needed, exit 10 = retrain needed (reason printed)
    python retrain.py status     print the policy, the last run and the monitoring signals

Signals: weeks since the last registered model, new data (data version changed since that model),
drift alerts from the last monitoring run, and the test error recorded for the last model.
"""
import json, os, sys, glob, datetime
import paths
from governance_lib import registry, data_version, audit_log

POLICY = json.load(open(os.path.join(paths.ROOT, "config", "retrain_policy.json")))


def signals():
    runs = registry("demand_forecast", paths.DEPT)
    last = runs[-1] if runs else None
    files = glob.glob(os.path.join(paths.RAW, "*.csv*")) + glob.glob(os.path.join(paths.EXT, "*.csv"))
    now_version = data_version(files) if files else None
    weeks = None
    if last:
        t = datetime.datetime.strptime(last["ts"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
        weeks = (datetime.datetime.now(datetime.timezone.utc) - t).days / 7
    drift = []
    fm = paths.res("forecast_metrics.json")
    if os.path.exists(fm):
        drift = json.load(open(fm)).get("drift", {}).get("shifted", [])
    return dict(last_run=last["run_id"] if last else None, weeks_since_last=weeks, new_data=bool(last and now_version != last.get("data_version")),
                data_version_now=now_version, drift_alerts=drift)


def decide(sig):
    if sig["last_run"] is None:
        return True, "no model registered yet"
    min_w, max_w = POLICY["min_weeks_between_retrains"], POLICY["max_weeks_between_retrains"]
    cadence = {"weekly": 1, "monthly": 4, "quarterly": 12, "never": 10 ** 6}.get(POLICY["policy"], 4)
    if sig["weeks_since_last"] is not None and sig["weeks_since_last"] >= max_w:
        return True, f"{sig['weeks_since_last']:.1f} weeks since the last model (limit {max_w})"
    if sig["new_data"] and sig["weeks_since_last"] is not None and sig["weeks_since_last"] >= cadence:
        return True, f"new data and {sig['weeks_since_last']:.1f} weeks since the last model ({POLICY['policy']} cadence)"
    if sig["drift_alerts"] and sig["new_data"] and (sig["weeks_since_last"] or 0) >= min(min_w, cadence):
        return True, "input drift on " + ", ".join(sig["drift_alerts"][:4])
    return False, "model is current"


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    sig = signals()
    need, why = decide(sig)
    if cmd == "status":
        print(json.dumps(dict(policy=POLICY, signals=sig, retrain_needed=need, reason=why), indent=2, default=str))
    elif cmd == "check":
        audit_log("retrain_check", needed=need, reason=why)
        print(("RETRAIN: " if need else "OK: ") + why)
        sys.exit(10 if need else 0)
