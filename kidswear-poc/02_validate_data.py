"""
Step 2 - Validate every extract against the data contracts (fail fast on errors).

Also proves the checks work: a deliberately corrupted copy of the sales extract must be rejected.
Writes results/<dept>/data_validation.json and an audit entry with the data version.
"""
import glob, json, os
import numpy as np
import pandas as pd
import paths, contracts
from governance_lib import audit_log, data_version, write_json

report = contracts.validate_all(paths.RAW, fail_fast=False)

# negative test: corrupt a sample and make sure the contract catches every defect
sales = pd.read_csv(os.path.join(paths.RAW, "sales_weekly.csv.gz"), nrows=5000)
bad = sales.copy()
bad.loc[0, "sales_units"] = bad.loc[0, "stock_on_hand_start"] + 5      # sold more than stock
bad.loc[1, "discount"] = 1.4                                            # impossible discount
bad.loc[2, "store_id"] = "S999"                                         # unknown store
bad.loc[3, "size"] = "XXL"                                              # size not in this department
bad.loc[4, "sales_units"] = np.nan                                      # missing value
bad = pd.concat([bad, bad.iloc[[5]]])                                   # duplicate key
tables = {"store_master": pd.read_csv(os.path.join(paths.RAW, "store_master.csv")),
          "style_master": pd.read_csv(os.path.join(paths.RAW, "style_master.csv"))}
found = {f["check"] for f in contracts.validate_table(bad, "sales_weekly", tables) if f["severity"] == "error"}
expected = {"rule:sales_not_above_stock", "range:discount", "reference:store_id", "allowed:size", "nulls:sales_units", "unique_key"}
report["self_test"] = dict(defects_injected=sorted(expected), defects_caught=sorted(found & expected),
                           passed=expected <= found)

files = glob.glob(os.path.join(paths.RAW, "*.csv*")) + glob.glob(os.path.join(paths.EXT, "*.csv"))
report["data_version"] = data_version(files)
write_json("data_validation.json", report)
audit_log("data_validated", data_version=report["data_version"], passed=report["passed"],
          errors=report["errors"], warnings=report["warnings"])
print(json.dumps({k: v for k, v in report.items() if k != "tables"}, indent=2))
for name, t in report["tables"].items():
    print(f"{name:<17} rows {t['rows']:>8,}  findings {len(t['findings'])}", [f["check"] for f in t["findings"]])
if not report["passed"] or not report["self_test"]["passed"]:
    raise SystemExit("Data contract check failed - pipeline stopped.")
