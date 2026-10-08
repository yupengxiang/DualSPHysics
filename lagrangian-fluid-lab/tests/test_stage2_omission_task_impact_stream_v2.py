#!/usr/bin/env python3
"""Source-closure counterexamples for the all-118 impact stream v2."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import tempfile


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ds_data02_stage2_omission_task_impact_stream_v2.py"
SPEC = importlib.util.spec_from_file_location("impact_stream_v2", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot import impact stream v2")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def expect_rejected(callback, label: str) -> None:
    try:
        callback()
    except MODULE.ImpactStreamV2Error:
        return
    raise AssertionError(f"manufactured {label} was accepted")


def main() -> int:
    closure = MODULE.validate_manifest()
    assert len(closure["source_records"]) == 118
    assert closure["h5_content_hash_performed"] is False
    assert {row["family_id"] for row in closure["source_records"]} == {"F2", "F4", "F6"}
    assert all(row["producer"]["trajectory"]["content_hash_performed"] is False for row in closure["source_records"])

    with tempfile.TemporaryDirectory(prefix="ds02-impact-stream-v2-tests-") as directory:
        root = Path(directory)
        source_path, source = MODULE.read_json(MODULE.V1_MANIFEST, "v1 manifest")
        wrong = copy.deepcopy(source)
        wrong["entries"][0]["physical_case_id"] = "WRONG_CURRENT_CASE"
        wrong_path = root / "wrong-manifest.json"
        wrong_path.write_text(json.dumps(wrong), encoding="utf-8")
        expect_rejected(lambda: MODULE.validate_manifest(wrong_path), "wrong physical case identity")

        wrong_h5 = copy.deepcopy(source)
        scan_path = Path(wrong_h5["entries"][0]["scan_path"])
        scan = json.loads(scan_path.read_text(encoding="utf-8"))
        wrong_h5["inputs"][scan["trajectory"]] = "deadbeef"
        wrong_h5_path = root / "h5-bound-manifest.json"
        wrong_h5_path.write_text(json.dumps(wrong_h5), encoding="utf-8")
        expect_rejected(lambda: MODULE.validate_manifest(wrong_h5_path), "H5 entering v2 input set")

        # A declared receipt H5 hash is metadata evidence.  A manifest that
        # silently changes the scan trajectory must fail the exact path join.
        wrong_scan = copy.deepcopy(source)
        scan_copy = root / "scan-copy.json"
        scan_copy.write_text(scan_path.read_text(encoding="utf-8"), encoding="utf-8")
        wrong_scan["entries"][0]["scan_path"] = str(scan_copy)
        wrong_scan_path = root / "wrong-scan-path.json"
        wrong_scan_path.write_text(json.dumps(wrong_scan), encoding="utf-8")
        expect_rejected(lambda: MODULE.validate_manifest(wrong_scan_path), "wrong scan path/receipt join")

    print("stage2 all-118 impact stream v2 H5/case/receipt source counterexamples: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
