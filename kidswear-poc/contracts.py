"""
Data contracts: validate extracts against config/data_contracts.json.

validate_table(df, name)  -> list of findings
validate_all(raw_dir)     -> report dict; raises ContractError on any 'error' finding (fail fast)
"""
import json, os
import numpy as np
import pandas as pd
import sim

HERE = os.path.dirname(os.path.abspath(__file__))
CONTRACT = json.load(open(os.path.join(HERE, "config", "data_contracts.json")))


class ContractError(Exception):
    def __init__(self, report):
        self.report = report
        errs = [f for t in report["tables"].values() for f in t["findings"] if f["severity"] == "error"]
        super().__init__(f"{len(errs)} contract error(s): " + "; ".join(f"{e['table']}.{e['check']}: {e['message']}" for e in errs[:5]))


def _allowed(spec):
    if "allowed" in spec:
        return set(spec["allowed"])
    src = spec.get("allowed_from_config")
    if src == "sizes":
        return set(sim.SIZES)
    if src == "categories":
        return set(sim.CATEGORIES)
    return None


def validate_table(df, name, tables=None):
    spec = CONTRACT["tables"][name]
    out = []

    def add(check, severity, message, rows=0):
        out.append(dict(table=name, check=check, severity=severity, message=message, rows=int(rows)))

    for col, c in spec["columns"].items():
        if col not in df.columns:
            if c.get("required"):
                add(f"column:{col}", "error", "required column missing")
            continue
        s = df[col]
        if c.get("required"):
            n = int(s.isna().sum() + (s.astype(str).str.strip() == "").sum() if c["type"] == "str" else s.isna().sum())
            if n:
                add(f"nulls:{col}", "error", f"{n} empty values in required column", n)
        if c["type"] in ("int", "float"):
            num = pd.to_numeric(s, errors="coerce")
            bad = int((num.isna() & s.notna()).sum())
            if bad:
                add(f"type:{col}", "error", f"{bad} values are not numbers", bad)
            if c["type"] == "int":
                frac = int(((num % 1) != 0).sum())
                if frac:
                    add(f"type:{col}", "error", f"{frac} values are not whole numbers", frac)
            if "min" in c:
                n = int((num < c["min"]).sum())
                if n:
                    add(f"range:{col}", "error", f"{n} values below {c['min']}", n)
            if "max" in c:
                n = int((num > c["max"]).sum())
                if n:
                    add(f"range:{col}", "error", f"{n} values above {c['max']}", n)
        if c["type"] == "date":
            bad = int(pd.to_datetime(s, errors="coerce").isna().sum())
            if bad:
                add(f"type:{col}", "error", f"{bad} values are not dates", bad)
        allowed = _allowed(c)
        if allowed is not None:
            bad = ~s.fillna("").astype(str).isin(allowed)
            if bad.any():
                add(f"allowed:{col}", "error", f"{int(bad.sum())} values outside the allowed set, e.g. {s[bad].iloc[0]!r}", bad.sum())
        ref = c.get("references")
        if ref and tables is not None:
            t, k = ref.split(".")
            if t in tables:
                missing = ~s.isin(set(tables[t][k]))
                if missing.any():
                    add(f"reference:{col}", "error", f"{int(missing.sum())} rows point to unknown {t} ({s[missing].iloc[0]!r})", missing.sum())
    key = spec.get("key")
    if key and all(k in df.columns for k in key):
        d = int(df.duplicated(key).sum())
        if d:
            add("unique_key", "error", f"{d} duplicate rows on {'+'.join(key)}", d)
    for rule in spec.get("row_rules", []):
        try:
            ok = eval(rule["expr"], {"abs": np.abs, "__builtins__": {}}, {c: df[c] for c in df.columns})
            n = int((~ok.astype(bool)).sum())
            if n:
                add(f"rule:{rule['name']}", rule["severity"], f"{n} rows break '{rule['expr']}'", n)
        except Exception as e:  # missing columns are already reported above
            add(f"rule:{rule['name']}", "warn", f"could not evaluate ({e.__class__.__name__})")
    fr = spec.get("freshness")
    if fr and "week_index" in df.columns:
        w = np.sort(df.week_index.unique())
        gaps = int((np.diff(w) > 1).sum())
        if gaps > fr["max_missing_weeks"]:
            add("freshness:gaps", "error", f"{gaps} gaps in the week sequence", gaps)
    return out


def validate_all(raw_dir, fail_fast=True):
    tables, report = {}, dict(contract_version=CONTRACT["version"], tables={})
    order = ["style_master", "store_master", "sales_weekly", "returns_comments"]
    for name in order:
        p = os.path.join(raw_dir, CONTRACT["tables"][name]["file"])
        if not os.path.exists(p):
            report["tables"][name] = dict(rows=0, findings=[dict(table=name, check="file", severity="error", message="file missing", rows=0)])
            continue
        df = pd.read_csv(p, keep_default_na=True, dtype={"verified_reason": str})
        if "verified_reason" in df.columns:
            df["verified_reason"] = df.verified_reason.fillna("")
        tables[name] = df
        report["tables"][name] = dict(rows=len(df), findings=validate_table(df, name, tables))
    report["errors"] = sum(f["severity"] == "error" for t in report["tables"].values() for f in t["findings"])
    report["warnings"] = sum(f["severity"] == "warn" for t in report["tables"].values() for f in t["findings"])
    report["passed"] = report["errors"] == 0
    if fail_fast and not report["passed"]:
        raise ContractError(report)
    return report
