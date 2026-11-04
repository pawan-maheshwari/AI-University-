#!/usr/bin/env bash
# Full pipeline: Kidswear end to end, Babywear core steps, then the planner app.
# Usage: bash run_all.sh            (about 12 minutes on a laptop)
#        FRESH=1 bash run_all.sh    (also clears the audit trail and model registry)
set -euo pipefail
cd "$(dirname "$0")"
if [ "${FRESH:-0}" = "1" ]; then rm -f governance/audit_log.jsonl governance/model_registry.jsonl; fi
run() { echo "== $*"; python3 "$@"; }
for s in 01_generate_data 02_validate_data 03_quality_nlp 04_prepare_features 05_demand_forecast 06_foundation_ensemble \
         07_hierarchy 08_size_curves 09_business_metrics 10_markdown 11_allocation 12_overrides 13_store_trial \
         14_retrain_cadence 15_adapters; do
  DEPT=kidswear run "$s.py"
done
for s in 01_generate_data 02_validate_data 03_quality_nlp 04_prepare_features 05_demand_forecast 08_size_curves; do
  DEPT=babywear run "$s.py"
done
DEPT=kidswear run 16_governance_report.py
run 17_departments.py
DEPT=kidswear run 18_build_planner.py
python3 tests/test_pipeline.py
echo "Done. Results in results/, planner at ../kidswear-planner.html"
