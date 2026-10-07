#!/usr/bin/env python3
"""Manufactured C52 identity and native-join counterexamples for v3."""
from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ds_data02_stage2_f2_s1_fine_native_impact_v4.py"
V1_SCRIPT = SCRIPT.parent / "ds_data02_stage2_f2_s1_fine_native_impact_v1.py"
SPEC = importlib.util.spec_from_file_location("fine_native_impact_v4", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot import fine native v3")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


SOLVER_RECEIPT = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/"
    "F2_S1_FINE_FULL_REFERENCE_DP00855_T4_SAME_CFL_DENSE/"
    "f2-s1-fine-dp00855-same-cfl-full4s-primary-001/execution-receipt.json"
)
DECODER_RECEIPT = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/"
    "F2_S1_FINE_NATIVE_IMPACT_AUDIT_V2/"
    "f2-s1-fine-partvtkout-v2-primary-002/execution-receipt.json"
)


def expect_reject(receipt: dict, source: dict, directory: Path, label: str) -> None:
    path = directory / f"{label}.json"
    path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    try:
        MODULE.validate_decoder(path, source)
    except MODULE.FineAuditError:
        return
    raise AssertionError(f"manufactured {label} decoder receipt was accepted")


def main() -> int:
    solver_path, solver = MODULE.read_json(SOLVER_RECEIPT, "fine solver")
    v1 = MODULE.load_v1(V1_SCRIPT)
    source = v1._solver_sources(solver_path, solver)
    _, original = MODULE.read_json(DECODER_RECEIPT, "primary002 decoder")

    with tempfile.TemporaryDirectory(prefix="ds02-fine-v3-tests-") as directory:
        root = Path(directory)

        wrong_case = copy.deepcopy(original)
        wrong_case["request"]["case_id"] = "F2_S1_FINE_NATIVE_IMPACT_AUDIT_V1"
        expect_reject(wrong_case, source, root, "wrong-case")

        wrong_attempt = copy.deepcopy(original)
        wrong_attempt["request"]["attempt_id"] = "f2-s1-fine-partvtkout-v2-primary-001"
        expect_reject(wrong_attempt, source, root, "wrong-attempt")

        wrong_raw = copy.deepcopy(original)
        wrong_raw["request"]["source_raw_partout"] = str(source["runparts"])
        expect_reject(wrong_raw, source, root, "wrong-raw-parent")

        wrong_digest = copy.deepcopy(original)
        raw_key = str(Path(source["raw_partout"]).resolve())
        wrong_digest["request"]["input_sha256"][raw_key] = "0" * 64
        expect_reject(wrong_digest, source, root, "wrong-input-digest")

        # The v1 validator checks a decoded receipt identity that is intentionally
        # different from primary002.  v3 must reject that old receipt before any
        # parser or cause credit is reached.
        old_receipt = copy.deepcopy(original)
        old_receipt["request"]["case_id"] = "F2_S1_FINE_NATIVE_IMPACT_AUDIT_V1"
        old_receipt["request"]["attempt_id"] = "f2-s1-fine-partvtkout-v2-primary-001"
        expect_reject(old_receipt, source, root, "old-v1-receipt")

    class FakeV1:
        @staticmethod
        def parse_run_out(_path: Path):
            return {"case_name": "case.xml", "map_real_pos": {"border": [[0, 0, 0], [1, 1, 1]], "final": [[0, 0, 0], [1, 1, 1]]}}

    source_stub = {
        "run_out": Path("/tmp/unused-run.out"),
        "solver_command": ["solver", "case.xml"],
        "xml": {"massfluid_kg": 1.0, "initial_fluid_mass_kg": 2.0},
    }
    solver_stub = {"request": {"physical_window_s": [0.0, 0.1]}}
    good_timeline = {
        "rows": [
            {"part": 0, "time_s": 0.0, "NpOut": 0, "NpOutPos": 0, "NpOutRho": 0, "NpOutMov": 0},
            {"part": 1, "time_s": 0.1, "NpOut": 1, "NpOutPos": 1, "NpOutRho": 0, "NpOutMov": 0},
        ],
        "totals": {"NpOut": 1, "NpOutPos": 1, "NpOutRho": 0, "NpOutMov": 0},
    }
    good_partout = [{"idp": 4, "part_out": 1, "motive_code": 1, "position_m": [0, 0, 0], "density_kg_m3": 1000}]
    MODULE._native_rows(FakeV1, good_timeline, good_partout, solver_stub, source_stub)

    wrong_count = copy.deepcopy(good_timeline)
    wrong_count["rows"][1]["NpOutPos"] = 0
    try:
        MODULE._native_rows(FakeV1, wrong_count, good_partout, solver_stub, source_stub)
    except MODULE.FineAuditError:
        pass
    else:
        raise AssertionError("count/time inconsistent native join received cause credit")

    duplicate = good_partout + [dict(good_partout[0])]
    duplicate[1]["idp"] = duplicate[0]["idp"]
    try:
        MODULE._native_rows(FakeV1, good_timeline, duplicate, solver_stub, source_stub)
    except MODULE.FineAuditError:
        pass
    else:
        raise AssertionError("ambiguous Idp native join received cause credit")

    # An integration step may overshoot tmax, but the first saved row at or
    # after tmax must be the final row and its preceding row must bracket tmax.
    endpoint_solver = {"request": {"physical_window_s": [0.0, 0.15]}}
    overshoot_timeline = {
        "rows": [
            {"part": 0, "time_s": 0.0, "NpOut": 0, "NpOutPos": 0, "NpOutRho": 0, "NpOutMov": 0},
            {"part": 1, "time_s": 0.1, "NpOut": 0, "NpOutPos": 0, "NpOutRho": 0, "NpOutMov": 0},
            {"part": 2, "time_s": 0.2, "NpOut": 1, "NpOutPos": 1, "NpOutRho": 0, "NpOutMov": 0},
        ],
        "totals": {"NpOut": 1, "NpOutPos": 1, "NpOutRho": 0, "NpOutMov": 0},
    }
    overshoot_partout = [dict(good_partout[0], part_out=2)]
    MODULE._native_rows(FakeV1, overshoot_timeline, overshoot_partout, endpoint_solver, source_stub)
    post_endpoint = copy.deepcopy(overshoot_timeline)
    post_endpoint["rows"].append({"part": 3, "time_s": 0.3, "NpOut": 0, "NpOutPos": 0, "NpOutRho": 0, "NpOutMov": 0})
    try:
        MODULE._native_rows(FakeV1, post_endpoint, overshoot_partout, endpoint_solver, source_stub)
    except MODULE.FineAuditError:
        pass
    else:
        raise AssertionError("timeline with post-endpoint rows received native credit")

    print("stage2 fine native v4 identity/count/ambiguity/endpoint counterexamples: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
