"""
Step 16 - Governance and audit report.

* Verifies the hash-chained audit trail, then proves tamper detection on a copy (one edited entry must break it).
* Lineage for the current forecast: data version -> feature version -> model version -> markdown pack -> decisions.
* Model registry summary and monitoring signals in one place for the planner app.
"""
import json, os, shutil
import paths
from governance_lib import verify_audit, registry, write_json, AUDIT, REGISTRY

ok = verify_audit()
tmp = os.path.join(paths.RES, "_tamper_test.jsonl")
shutil.copy(AUDIT, tmp)
lines = open(tmp).read().splitlines()
mid = len(lines) // 2
e = json.loads(lines[mid]); e["detail"]["tampered"] = True
lines[mid] = json.dumps(e, sort_keys=True, separators=(",", ":"))
open(tmp, "w").write("\n".join(lines) + "\n")
tamper = verify_audit(tmp)
os.remove(tmp)
events = [json.loads(l) for l in open(AUDIT) if l.strip()]
mine = [x for x in events if x["dept"] == paths.DEPT]
runs = registry(dept=paths.DEPT)
fm = json.load(open(paths.res("forecast_metrics.json")))
last_fc = [r for r in runs if r["kind"] == "demand_forecast"][-1]
pack_ev = [x for x in mine if x["event"] == "markdown_recommended"]
lineage = dict(data_version=last_fc["data_version"], feature_version=last_fc["feature_version"], model_run=last_fc["run_id"],
               model_version=last_fc["model_version"], training_window=last_fc["training_window"],
               markdown_pack_version=pack_ev[-1]["detail"]["pack_version"] if pack_ev else None,
               decisions=[dict(ts=x["ts"], event=x["event"], actor=x["actor"]) for x in mine
                          if x["event"] in ("overrides_ingested", "markdown_recommended", "trial_registered", "trial_outcome_recorded", "allocation_published")])
out = dict(audit_chain=ok, tamper_test=dict(edited_line=mid + 1, detected=not tamper["ok"], broken_at_line=tamper.get("broken_at_line")),
           events_total=len(events), events_this_department=len(mine),
           event_counts={k: sum(1 for x in mine if x["event"] == k) for k in sorted({x["event"] for x in mine})},
           registry=[dict(run_id=r["run_id"], kind=r["kind"], ts=r["ts"], model_version=r.get("model_version"),
                          data_version=r.get("data_version"), metrics={k: v for k, v in (r.get("metrics") or {}).items() if isinstance(v, (int, float))})
                     for r in runs],
           lineage=lineage, monitoring=dict(test_wape=fm["test"]["model_wape"], p10_p90_coverage=fm["test"]["p10_p90_coverage"],
                                            bias=fm["test"]["model_bias"], drift_shifted=fm["drift"]["shifted"], drift_watch=fm["drift"]["watch"]),
           recent_events=mine[-40:])
write_json("governance_report.json", out)
print(json.dumps({k: v for k, v in out.items() if k not in ("registry", "recent_events")}, indent=2))
