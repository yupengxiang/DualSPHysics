#!/usr/bin/env python3
"""Static validator for fresh108 disabled Root690 successors."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

PACKAGE=Path(__file__).resolve().parents[1]
def load(path): return json.loads(Path(path).read_text(encoding="utf-8"))
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--package",type=Path,required=True); a=ap.parse_args()
    p=a.package.resolve(); idx=load(p/"index.json")
    assert idx["request_count"]==24 and idx["all_disabled"] is True and len(idx["requests"])==24
    sys.path.insert(0,str(PACKAGE/"workers")); from repair_disabled_root690_request import validate_runtime_fields
    seen=set()
    for row in idx["requests"]:
        q=load(row["path"]); validate_runtime_fields(q,disabled=True); seen.add(q["case_id"])
        assert row["sha256"]==__import__("hashlib").sha256(Path(row["path"]).read_bytes()).hexdigest()
    assert len(seen)==24
    print("fresh108 source contract: PASS (24 disabled requests; Root142/runtime fields; Root023 CLI; metadata-only input closure)")
if __name__=="__main__": main()
