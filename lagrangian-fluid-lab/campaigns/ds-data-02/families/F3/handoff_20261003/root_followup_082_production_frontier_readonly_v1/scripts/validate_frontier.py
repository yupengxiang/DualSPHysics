#!/usr/bin/env python3
"""Validate the disabled, metadata-only frontier package without touching evidence paths."""
from pathlib import Path
import hashlib, json, re
ROOT=Path(__file__).resolve().parents[1]
report=json.loads((ROOT/"metadata/frontier-report.json").read_text())
assert report["source_only"] is True
assert report["dispatch_contract"]["all_requests_disabled"] is True
assert report["dispatch_contract"]["future_science_hashes_null"] is True
assert report["scope"]["science_payloads_read_or_hashed"] is False
files=list((ROOT/"requests").glob("F1/*.json"))+list((ROOT/"requests").glob("F2/*.json"))+list((ROOT/"requests").glob("F7/*.json"))
assert len(files)==31, len(files)
for p in files:
    d=json.loads(p.read_text())
    assert d["source_only"] is True and d["gate"]["enabled"] is False and d["gate"]["launch_allowed"] is False
    assert d["gate"]["production_approval"] == "none" and d["gate"]["q_n"] == "not_granted"
    assert re.fullmatch(r"[0-9a-f]{64}", d["physical_condition_sha256"])
    assert d["future_outputs"]["typed_h5_sha256"] is None and d["future_outputs"]["xmf_sha256"] is None and d["future_outputs"]["render_sha256"] is None
print(f"frontier structural validation passed: {len(files)} immediate disabled handoffs")
