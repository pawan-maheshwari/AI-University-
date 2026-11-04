"""Shared paths. Set DEPT=babywear (etc.) to run the pipeline for another department."""
import os

DEPT = os.environ.get("DEPT", "kidswear")
ROOT = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(ROOT, "data", DEPT, "raw")
GT = os.path.join(RAW, "ground_truth")          # hidden truth: scoring only, never training
EXT = os.path.join(RAW, "external")             # external feeds (weather, events, competitor, macro)
SRC = os.path.join(ROOT, "data", DEPT, "source_extracts")   # POS / ERP / inventory style extracts
SPL = os.path.join(ROOT, "data", DEPT, "splits")
RES = os.path.join(ROOT, "results", DEPT)
MOD = os.path.join(ROOT, "models", DEPT)
GOV = os.path.join(ROOT, "governance")
for _d in (RAW, GT, EXT, SRC, SPL, RES, MOD, GOV):
    os.makedirs(_d, exist_ok=True)


def res(name):
    return os.path.join(RES, name)

import warnings as _w
_w.filterwarnings("ignore", category=FutureWarning)
_w.filterwarnings("ignore", category=DeprecationWarning)
