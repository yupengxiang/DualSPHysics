#!/usr/bin/env python3
"""Read-only validator for fresh207's bounded cross-family spot audit."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

FORBIDDEN = (".h5", ".bi4", ".csv", ".dat", ".vtk", ".png")

def fail(msg: str) -> None:
    raise SystemExit(f"FAIL: {msg}")

def walk(value):
    if isinstance(value, dict):
        for k, v in value.items():
            yield k, v
            yield from walk(v)
    elif isinstance(value, list):
        for v in value:
            yield from walk(v)

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("audit", type=Path)
    args = ap.parse_args()
    d = json.loads(args.audit.read_text())
    if d.get("schema") != "ds02.f6.fresh207.cross-family-physical-distinctness-spot-audit.v1":
        fail("schema")
    if d.get("source_boundaries", {}).get("scientific_payloads_read_or_hashed") is not False:
        fail("scientific payload boundary")
    cases = d.get("cases", {})
    if {k: len(v) for k, v in cases.items()} != {"F3": 2, "F4": 3, "F5": 5}:
        fail("bounded case selection")
    # Output must not smuggle payload paths into evidence.  Producer-attested
    # hashes are allowed only as values copied from metadata, never as files
    # opened by this package.
    for key, value in walk(d):
        if isinstance(value, str) and value.lower().endswith(FORBIDDEN):
            fail(f"scientific payload path in output: {value}")
    for fam, rows in cases.items():
        for row in rows:
            if row.get("actual_native", {}).get("status") != "completed" or row.get("actual_native", {}).get("returncode") != 0:
                fail(f"native terminal gate {fam}/{row.get('physical_case_id')}")
            if row.get("actual_native", {}).get("metadata_input_mismatch_count") != 0:
                fail(f"launch-after metadata mismatch {fam}/{row.get('physical_case_id')}")
            for ev in row.get("source_evidence", []):
                if ev.get("exists") is not True:
                    fail(f"missing source evidence {ev}")
                if ev.get("path", "").lower().endswith(FORBIDDEN):
                    fail(f"forbidden source evidence {ev['path']}")
    f3 = {x["physical_case_id"]: x for x in cases["F3"]}
    if any(x.get("status") != "MISMATCH_ACTUAL_REQUEST_USED_NOMINAL_SOURCE" for x in cases["F3"]):
        fail("F3 mismatch must remain explicit")
    if f3["F3_TWOAXIS_PITCH1000_AY0250_VISUAL_DOMAIN"]["source_owner_tuple"]["pitch_numeric"] is not None:
        fail("F3 pitch must remain absent when no numeric source field exists")
    if f3["F3_TWOAXIS_PITCH1000_AY0250_VISUAL_DOMAIN"]["actual_native_request_tuple"]["transverse_amplitude_m_s2"] != 0.5:
        fail("F3 lower actual request amplitude")
    if f3["F3_TWOAXIS_PITCH1000_AY0750_VISUAL_DOMAIN"]["actual_native_request_tuple"]["transverse_amplitude_m_s2"] != 0.5:
        fail("F3 upper actual request amplitude")
    f4 = cases["F4"]
    if any(x.get("status") != "PASS_NORMALIZED_TUPLE_UNIQUE" for x in f4):
        fail("F4 selected tuple status")
    if len({x.get("normalized_tuple_sha256") for x in f4}) != len(f4):
        fail("F4 tuple collision")
    expected_f5 = {
        "F5_COMPACT_RUNUP_RECOVERY_C082S1_A080": (0.8, None),
        "F5_COMPACT_RUNUP_RECOVERY_C082S1_A120": (1.2, None),
        "F5_COMPACT_RUNUP_RECOVERY_C082S1_M085_T090": (0.85, 0.9),
        "F5_COMPACT_RUNUP_RECOVERY_C082S1_M115_T080": (1.15, 0.8),
        "F5_COMPACT_RUNUP_RECOVERY_C082S1_M115_T100": (1.15, 1.0),
    }
    for row in cases["F5"]:
        amp, scale = expected_f5[row["physical_case_id"]]
        motion = row.get("binding_motion_fields", {})
        if motion.get("amplitude_scale") != amp or motion.get("time_scale") != scale:
            fail(f"F5 explicit motion tuple {row['physical_case_id']}")
        if row.get("status") != "PASS_SOURCE_MOTION_TUPLE_RECOVERED":
            fail(f"F5 source tuple status {row['physical_case_id']}")
    # The validator itself has no mutation path and refuses to validate a
    # missing output.  This is the negative output-guard contract for callers.
    print(json.dumps({"status": "PASS", "schema": d["schema"], "cases": {k: len(v) for k, v in cases.items()}, "negative_contracts": ["F3 nominal-binding mismatch is not promoted", "F4 tuple collision fails", "F5 absent motion fields fail", "scientific payload paths fail"]}, sort_keys=True))

if __name__ == "__main__":
    main()
