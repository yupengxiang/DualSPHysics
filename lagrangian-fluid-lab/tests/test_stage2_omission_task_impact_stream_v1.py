#!/usr/bin/env python3
"""Source-identity, timing, motive and mass-screen counterexamples."""
from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ds_data02_stage2_omission_task_impact_stream_v1.py"
SPEC = importlib.util.spec_from_file_location("impact_stream_v1", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot import impact stream v1")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
MANIFEST = Path(__file__).resolve().parents[1] / "campaigns/ds-data-02/stage2/requests/omission-task-impact-stream-v1/impact-stream-v1-manifest.json"


def expect_reject(entry: dict, label: str) -> None:
    try:
        MODULE.analyze_case(entry, verify_bound_inputs=False)
    except MODULE.StreamError:
        return
    raise AssertionError(f"manufactured {label} case was accepted")


def main() -> int:
    _, manifest = MODULE.read_json(MANIFEST, "impact stream manifest")
    first = next(item for item in manifest["entries"] if item["case_key"] == "F2/scan-F2-048-001")
    f6 = next(item for item in manifest["entries"] if item["case_key"] == "F6/scan-F6-240-001")
    high = MODULE.analyze_case(first, verify_bound_inputs=False)
    assert high["mass_screen"] == "mass_screen_subset_above_gate"
    assert high["observability"]["dynamical_impact"] == "UNKNOWN"
    assert high["native_motive_counts"] == {"position": 118}
    rigid = MODULE.analyze_case(f6, verify_bound_inputs=False)
    assert rigid["f6_mass_semantics"]["sample_floating_typed_initial_mass_kg"] == 256.0
    assert rigid["typed_initial_fluid_mass_kg"] == 5120.0

    wrong_family = copy.deepcopy(first)
    wrong_family["family_id"] = "F4"
    expect_reject(wrong_family, "wrong-family")
    wrong_digest = copy.deepcopy(first)
    wrong_digest["scan_sha256"] = "0" * 64
    expect_reject(wrong_digest, "wrong-scan-digest")

    with tempfile.TemporaryDirectory(prefix="ds02-impact-stream-tests-") as directory:
        root = Path(directory)
        forensic = json.loads(Path(first["forensic_path"]).read_text(encoding="utf-8"))
        forensic["excluded_particles"].append(copy.deepcopy(forensic["excluded_particles"][0]))
        duplicate_path = root / "duplicate-forensic.json"
        duplicate_path.write_text(json.dumps(forensic), encoding="utf-8")
        duplicate = copy.deepcopy(first)
        duplicate["forensic_path"] = str(duplicate_path)
        duplicate["forensic_sha256"] = MODULE.sha256(duplicate_path)
        expect_reject(duplicate, "duplicate-native-id")

        timed = json.loads(Path(first["forensic_path"]).read_text(encoding="utf-8"))
        timed["typed_identity"]["ids"][0]["first_missing_frame"] += 1
        timed_path = root / "wrong-time-forensic.json"
        timed_path.write_text(json.dumps(timed), encoding="utf-8")
        wrong_time = copy.deepcopy(first)
        wrong_time["forensic_path"] = str(timed_path)
        wrong_time["forensic_sha256"] = MODULE.sha256(timed_path)
        expect_reject(wrong_time, "first-missing-time")

        motive = json.loads(Path(first["forensic_path"]).read_text(encoding="utf-8"))
        motive["excluded_particles"][0]["native_motive_code"] = 2
        motive_path = root / "wrong-motive-forensic.json"
        motive_path.write_text(json.dumps(motive), encoding="utf-8")
        wrong_motive = copy.deepcopy(first)
        wrong_motive["forensic_path"] = str(motive_path)
        wrong_motive["forensic_sha256"] = MODULE.sha256(motive_path)
        expect_reject(wrong_motive, "wrong-native-motive")
    print("stage2 omission impact stream identity/time/motive/F6-mass counterexamples: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
