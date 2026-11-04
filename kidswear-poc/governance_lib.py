"""
Governance utilities shared by every step.

* audit_log(event, **detail)  - append-only, hash-chained audit trail (governance/audit_log.jsonl).
  Each entry stores the SHA-256 of the previous entry, so any edit or deletion breaks the chain.
* verify_audit()              - re-computes the chain and reports the first broken link, if any.
* file_hash / data_version    - content hashes used as data, feature and model versions.
* register_run(...)           - experiment and model registry (governance/model_registry.jsonl):
  parameters, training window, data/feature/model versions, all trials and metrics.
* psi(...)                    - population stability index for feature drift.
"""
import datetime, hashlib, json, os
import numpy as np
import paths

AUDIT = os.path.join(paths.GOV, "audit_log.jsonl")
REGISTRY = os.path.join(paths.GOV, "model_registry.jsonl")


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _canon(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def file_hash(path, n=16):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:n]


def text_hash(text, n=16):
    return hashlib.sha256(text.encode()).hexdigest()[:n]


def data_version(files):
    """One version id for a set of files (order-independent)."""
    parts = sorted(f"{os.path.basename(p)}:{file_hash(p)}" for p in files if os.path.exists(p))
    return text_hash("|".join(parts))


def _last_hash():
    if not os.path.exists(AUDIT):
        return "GENESIS"
    last = None
    with open(AUDIT) as f:
        for line in f:
            if line.strip():
                last = line
    return json.loads(last)["hash"] if last else "GENESIS"


def audit_log(event, actor="pipeline", **detail):
    entry = dict(ts=_now(), dept=paths.DEPT, event=event, actor=actor, detail=detail, prev=_last_hash())
    entry["hash"] = hashlib.sha256(_canon({k: v for k, v in entry.items() if k != "hash"}).encode()).hexdigest()
    with open(AUDIT, "a") as f:
        f.write(_canon(entry) + "\n")
    return entry["hash"]


def verify_audit(path=AUDIT):
    prev, n = "GENESIS", 0
    if not os.path.exists(path):
        return dict(ok=True, entries=0)
    with open(path) as f:
        for i, line in enumerate(f):
            if not line.strip():
                continue
            e = json.loads(line)
            body = {k: v for k, v in e.items() if k != "hash"}
            if e["prev"] != prev or hashlib.sha256(_canon(body).encode()).hexdigest() != e["hash"]:
                return dict(ok=False, entries=n, broken_at_line=i + 1)
            prev, n = e["hash"], n + 1
    return dict(ok=True, entries=n, head=prev)


def register_run(kind, **record):
    rec = dict(run_id=f"{kind}-{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S')}-{text_hash(_canon(record), 6)}",
               ts=_now(), dept=paths.DEPT, kind=kind, **record)
    with open(REGISTRY, "a") as f:
        f.write(_canon(rec) + "\n")
    audit_log("model_registered", run_id=rec["run_id"], kind=kind,
              model_version=record.get("model_version"), data_version=record.get("data_version"))
    return rec


def registry(kind=None, dept=None):
    if not os.path.exists(REGISTRY):
        return []
    out = [json.loads(l) for l in open(REGISTRY) if l.strip()]
    return [r for r in out if (kind is None or r["kind"] == kind) and (dept is None or r["dept"] == dept)]


def psi_bins(x, n=10):
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) == 0:
        return None
    edges = np.unique(np.quantile(x, np.linspace(0, 1, n + 1)))
    if len(edges) < 3:
        edges = np.array([x.min() - 1e-9, x.min() + 1e-9, x.max() + 1e-9])
    return edges


def psi(expected, actual, edges=None, n=10):
    """Population stability index. <0.1 stable, 0.1-0.25 moderate shift, >0.25 major shift."""
    e = np.asarray(expected, dtype=float); a = np.asarray(actual, dtype=float)
    e, a = e[np.isfinite(e)], a[np.isfinite(a)]
    if len(e) == 0 or len(a) == 0:
        return float("nan")
    edges = psi_bins(e, n) if edges is None else np.asarray(edges)
    ep = np.histogram(np.clip(e, edges[0], edges[-1]), edges)[0] / len(e)
    ap = np.histogram(np.clip(a, edges[0], edges[-1]), edges)[0] / len(a)
    ep, ap = np.clip(ep, 1e-4, None), np.clip(ap, 1e-4, None)
    return float(np.sum((ap - ep) * np.log(ap / ep)))


def write_json(name, obj):
    with open(paths.res(name), "w") as f:
        json.dump(obj, f, indent=2, default=lambda o: float(o) if isinstance(o, (np.floating,)) else int(o) if isinstance(o, np.integer) else str(o))
