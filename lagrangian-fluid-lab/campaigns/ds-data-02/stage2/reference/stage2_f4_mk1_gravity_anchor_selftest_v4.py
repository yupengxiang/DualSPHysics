#!/usr/bin/env python3
"""Manufactured guards for the forward F4 gravity-anchor worker.

This test does not read native or HDF5 data.  It exercises the worker's real
CLI success path with a monkeypatched computation, the failure artifact path,
and source/time/non-finite-input rejection paths.  It therefore catches the
v3 failure mode where a zero-exit UNKNOWN result printed to stdout but did not
create the requested JSON artifact.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile
from typing import Any, Callable

import stage2_f4_mk1_gravity_anchor_v4 as worker


def base_kwargs() -> dict[str, object]:
    return {
        "mass_kg": 1.0,
        "particle_count": 2,
        "gravity": (0.0, 0.0, -9.81),
        "external_motion_status": "PASS_EMPTY_EXECUTION_MOTION_AND_NO_MOVING_FLOATING_BLOCK",
        "shifting_status": "PASS_PARAMETER_Shifting_0",
        "id_status": "PASS_NO_ID_EXCLUSION_OR_REUSE",
        "internal_pair_force_status": "PAIRWISE_INTERNAL_FORCE_COM_CANCELLATION_SOURCE_CONTRACT",
        "separation_records": [
            {"status": "PASS_FARTHER_THAN_TWO_SUPPORT_RADII"},
            {"status": "PASS_FARTHER_THAN_TWO_SUPPORT_RADII"},
        ],
    }


def run_case(name: str, **updates: object) -> dict[str, object]:
    values = base_kwargs()
    values.update(updates)
    result = worker.evaluate_preconditions(**values)
    return {
        "name": name,
        "status": result["status"],
        "reasons": result["reasons"],
        "pass": result["status"].startswith("REJECT"),
    }


def _cli_args(output: Path, *, expected_final_time_s: str = "0") -> list[str]:
    return [
        "stage2_f4_mk1_gravity_anchor_v4.py",
        "--raw-root", str(output.parent / "raw"),
        "--runparts", str(output.parent / "RunPARTs.csv"),
        "--generated-xml", str(output.parent / "generated.xml"),
        "--decoder", str(output.parent / "decoder"),
        "--output", str(output),
        "--scratch-root", str(output.parent / "scratch"),
        "--solver-source-jsph", str(output.parent / "JSph.cpp"),
        "--solver-source-gpu", str(output.parent / "JSphGpuSingle.cpp"),
        "--solver-source-kernel", str(output.parent / "FunSphKernel.h"),
        "--expected-frame-count", "1",
        "--expected-final-time-s", expected_final_time_s,
        "--anchor-max-time-s", "0.06",
        "--frames", "0",
    ]


def _invoke_cli(argv: list[str], *, fake_run: Callable[[argparse.Namespace], dict[str, Any]] | None = None) -> tuple[int, dict[str, Any]]:
    old_argv = sys.argv
    old_run = worker.run
    try:
        sys.argv = argv
        if fake_run is not None:
            worker.run = fake_run  # type: ignore[assignment]
        return_code = worker.main()
        output = Path(argv[argv.index("--output") + 1])
        value = json.loads(output.read_text(encoding="utf-8"))
        return return_code, value
    finally:
        sys.argv = old_argv
        worker.run = old_run


def _source_mismatch_case(root: Path) -> dict[str, object]:
    wrong = root / "wrong_JSph.cpp"
    wrong.write_text("// manufactured wrong source\n", encoding="utf-8")
    try:
        worker.verify_source_contract(wrong, wrong, wrong)
    except worker.UnsupportedSemantics as exc:
        return {"name": "wrong_source_contract_rejected", "status": "REJECTED", "reason": str(exc), "pass": True}
    return {"name": "wrong_source_contract_rejected", "status": "ACCEPTED_UNEXPECTEDLY", "reason": "no rejection", "pass": False}


def _time_counterexample(root: Path) -> dict[str, object]:
    bad = root / "bad_RunPARTs.csv"
    bad.write_text("Part;TimeStep [s]\n0;0\n1;nan\n", encoding="utf-8")
    try:
        worker.read_runparts(bad)
    except ValueError as exc:
        return {"name": "nonfinite_runparts_time_rejected", "status": "REJECTED", "reason": str(exc), "pass": True}
    return {"name": "nonfinite_runparts_time_rejected", "status": "ACCEPTED_UNEXPECTEDLY", "reason": "no rejection", "pass": False}


def _cli_artifact_cases(root: Path) -> list[dict[str, object]]:
    success_output = root / "success" / "anchor.json"
    success_output.parent.mkdir(parents=True, exist_ok=True)

    def fake_run(_args: argparse.Namespace) -> dict[str, Any]:
        return {
            "schema": worker.SCHEMA,
            "status": "UNKNOWN_TEST_SUCCESS",
            "scope": {"hdf5_read": False, "full_native_tree_scanned": False},
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        }

    code, value = _invoke_cli(_cli_args(success_output), fake_run=fake_run)
    success_pass = (
        code == 0
        and success_output.is_file()
        and success_output.stat().st_size > 0
        and value.get("artifact_write_contract", {}).get("status") == "WRITTEN_BY_WORKER_SUCCESS_PATH"
    )
    success_case = {
        "name": "successful_cli_writes_nonempty_json_artifact",
        "status": value.get("status"),
        "artifact_bytes": success_output.stat().st_size if success_output.exists() else 0,
        "artifact_write_contract": value.get("artifact_write_contract"),
        "pass": success_pass,
    }

    failure_output = root / "failure" / "anchor.json"
    failure_output.parent.mkdir(parents=True, exist_ok=True)
    code, value = _invoke_cli(_cli_args(failure_output, expected_final_time_s="nan"))
    failure_pass = (
        code == 2
        and failure_output.is_file()
        and failure_output.stat().st_size > 0
        and value.get("status") == "FAILED_INPUT_OR_RUNTIME_WITH_ARTIFACT"
        and value.get("artifact_write_contract", {}).get("status") == "WRITTEN_BY_WORKER_FAILURE_PATH"
    )
    failure_case = {
        "name": "nonfinite_cli_input_writes_failure_artifact",
        "status": value.get("status"),
        "reason": value.get("reason"),
        "artifact_bytes": failure_output.stat().st_size if failure_output.exists() else 0,
        "pass": failure_pass,
    }
    return [success_case, failure_case]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="f4-gravity-anchor-v4-selftest-") as temporary:
        root = Path(temporary)
        cases = [
            run_case("zero_or_nonpositive_mass_rejected", mass_kg=0.0),
            run_case("multiple_particles_with_nonzero_internal_pair_force_rejected", internal_pair_force_status="NONZERO_INTERNAL_PAIR_FORCE"),
            run_case("contact_within_support_rejected", separation_records=[{"status": "FAIL_WITHIN_TWO_SUPPORT_RADII"}]),
            run_case("nonuniform_gravity_rejected", gravity_uniform=False),
            run_case("id_exclusion_rejected", id_status="FAIL_ID_EXCLUSION"),
            _source_mismatch_case(root),
            _time_counterexample(root),
            *_cli_artifact_cases(root),
        ]
    passed = all(bool(case["pass"]) for case in cases)
    value = {
        "schema": "ds02.stage2.f4-mk1-gravity-anchor-selftest.v4",
        "status": "PASS_ALL_MANUFACTURED_REJECTS_AND_ARTIFACT_GUARDS" if passed else "FAIL_MANUFACTURED_GUARD",
        "cases": cases,
        "uses_native_or_h5": False,
        "worker_schema_under_test": worker.SCHEMA,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "scope_note": "CLI artifact existence is tested with a monkeypatched computation; no scientific result is inferred.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        raise FileExistsError(args.output)
    args.output.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": value["status"], "output": str(args.output)}, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
