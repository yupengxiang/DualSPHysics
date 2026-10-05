#!/usr/bin/env python3
"""Bind actual Root426/QA441 JSON metadata for the disabled 51-frame solver.

This binder is deliberately metadata-only.  It may read and hash JSON
receipts/reports, but it never opens a BI4, CSV, H5, VTK, DAT, or solver
payload.  It never changes a runner request or grants qualification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

HEX = set("0123456789abcdefABCDEF")
CASE = "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1"
REPORT_SCHEMA = "ds02.f5.c082s1.stage1-placement-mk50-audit.fresh103.v1"
GEN_SCHEMA = "ds02.root.actual-native-source-preflight.v1"
EXPECTED = {
    "total": 194427,
    "fixed": 158559,
    "moving": 4210,
    "floating": 0,
    "fluid": 31658,
    "dimension": 3,
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha256_json(path: Path) -> str:
    require(path.suffix.lower() == ".json", f"metadata JSON required: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path, label: str) -> tuple[dict[str, Any], str]:
    digest = sha256_json(path)
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"{label} is not a JSON object")
    return value, digest


def producer_sha(value: Any, label: str) -> str:
    require(isinstance(value, str) and len(value) == 64 and set(value) <= HEX,
            f"{label} is not a producer-declared SHA-256")
    return value


def receipt_identity(receipt: Mapping[str, Any]) -> dict[str, Any]:
    request = receipt.get("request")
    request = request if isinstance(request, dict) else {}
    return {
        "attempt_id": request.get("attempt_id") or receipt.get("attempt_id"),
        "case_id": request.get("case_id") or receipt.get("case_id"),
        "output_root": receipt.get("output_root") or request.get("output_root"),
    }


def completed(receipt: Mapping[str, Any], label: str) -> None:
    require(receipt.get("status") == "completed", f"{label} is not completed")
    code = receipt.get("returncode", receipt.get("return_code", receipt.get("exit_code")))
    require(code is not None and int(code) == 0, f"{label} return code is not zero")


def load_attestation(package_root: Path, candidate: str) -> dict[str, Any]:
    path = package_root / "metadata" / "root426-qa441-actual-attestation.json"
    value, _ = load_json(path, "Root426/QA441 attestation")
    return value["candidates"][candidate]


def bind_gencase(receipt_path: Path, prepared_path: Path, candidate: str,
                 att: Mapping[str, Any]) -> dict[str, Any]:
    receipt, receipt_sha = load_json(receipt_path, "GenCase receipt")
    prepared, prepared_sha = load_json(prepared_path, "prepared-input-report")
    completed(receipt, "GenCase receipt")
    identity = receipt_identity(receipt)
    require(identity["case_id"] == CASE, "GenCase case identity mismatch")
    require(identity["attempt_id"] == att["gencase_attempt_id"],
            "GenCase attempt does not match Root426 attestation")
    require(prepared.get("schema") == GEN_SCHEMA, "GenCase prepared schema mismatch")
    counts = prepared.get("generated_xml_particle_counts")
    require(isinstance(counts, dict), "prepared report lacks generated counts")
    actual = {
        "total": int(prepared.get("actual_total_particles", -1)),
        "fixed": int(counts.get("fixed", -1)),
        "moving": int(counts.get("moving", -1)),
        "floating": int(counts.get("floating", -1)),
        "fluid": int(counts.get("fluid", -1)),
        "dimension": int(receipt.get("solver_dimension_from_gencase", -1)),
    }
    require(actual == EXPECTED, f"GenCase producer counts differ: {actual}")
    require(int(receipt.get("total_particles", -1)) == EXPECTED["total"],
            "GenCase receipt total differs")
    require(int(receipt.get("fluid_particles", -1)) == EXPECTED["fluid"],
            "GenCase receipt fluid count differs")
    data2d = prepared.get("actual_generated_constants", {}).get("data2d", {}).get("value")
    require(str(data2d).lower() in {"false", "0"}, "GenCase producer is 2-D")
    require(producer_sha(prepared.get("xml_sha256"), "prepared XML SHA") == att["xml_sha256"],
            "prepared XML SHA differs from Root426 attestation")
    require(producer_sha(prepared.get("bi4_sha256"), "prepared BI4 SHA") == att["bi4_sha256"],
            "prepared BI4 SHA differs from Root426 attestation")
    return {
        "candidate": candidate,
        "attempt_id": identity["attempt_id"],
        "case_id": identity["case_id"],
        "receipt_path": str(receipt_path),
        "receipt_sha256": receipt_sha,
        "prepared_report_path": str(prepared_path),
        "prepared_report_sha256": prepared_sha,
        "actual_counts": actual,
        "data2d": False,
        "generated_xml_sha256_producer_attested": att["xml_sha256"],
        "generated_bi4_sha256_producer_attested": att["bi4_sha256"],
        "payloads_opened_or_hashed_by_binder": False,
    }


def bind_initial_qa(report_path: Path, receipt_path: Path, candidate: str,
                    att: Mapping[str, Any], gencase: Mapping[str, Any]) -> dict[str, Any]:
    report, report_sha = load_json(report_path, "initial QA report")
    receipt, receipt_sha = load_json(receipt_path, "initial QA receipt")
    completed(receipt, "initial QA receipt")
    identity = receipt_identity(receipt)
    require(report.get("schema") == REPORT_SCHEMA, "initial QA report schema mismatch")
    require(report.get("status") == "completed_stage1_placement_mk50_diagnostic",
            "initial QA report status mismatch")
    require(report.get("all_basic_placement_checks_pass") is True,
            "initial QA basic placement/Mk50 checks did not pass")
    require(report.get("numerical_precision_result_accepted") is False,
            "initial QA precision result was incorrectly accepted")
    require(identity["case_id"] == CASE, "initial QA case identity mismatch")
    require(identity["attempt_id"] == report.get("qa_attempt_id"),
            "initial QA report/receipt attempt mismatch")
    require(report.get("gencase_attempt_id") == gencase["attempt_id"],
            "initial QA is bound to a different GenCase attempt")
    actual = report.get("actual_counts")
    require(isinstance(actual, dict), "initial QA actual_counts missing")
    compact = {
        "total": int(actual.get("total_particles", -1)),
        "fixed": int(actual.get("fixed_particles", -1)),
        "moving": int(actual.get("moving_particles", -1)),
        "floating": int(actual.get("floating_particles", -1)),
        "fluid": int(actual.get("fluid_particles", -1)),
        "dimension": int(actual.get("solver_dimension", -1)),
    }
    require(compact == EXPECTED, f"initial QA counts differ: {compact}")
    checks = report.get("checks")
    require(isinstance(checks, dict) and all(checks.get(k) is True for k in (
        "all_native_rows_finite", "uid_unique_consecutive",
        "native_type_set_and_counts_match_actual_producer",
        "fixed_moving_floating_fluid_spatial_no_overlap",
        "fluid_inside_exact_source_box", "fluid_initial_above_exact_continuous_bed",
        "fluid_has_exact_15_transverse_levels", "central_mk50_surface_support_is_present",
    )), "initial QA required physical checks are incomplete")
    boundary = report.get("review_boundary")
    require(isinstance(boundary, dict) and boundary.get("short_solver_authorized") is False,
            "initial QA report grants solver authorization")
    provenance = report.get("input_provenance")
    require(isinstance(provenance, dict)
            and provenance.get("generated_bi4_opened_by_this_worker") is False
            and provenance.get("source_agent_read_or_hashed_bi4") is False,
            "initial QA provenance is unsafe")
    require(provenance.get("generated_bi4_sha256") == gencase["generated_bi4_sha256_producer_attested"],
            "initial QA BI4 attestation differs from GenCase")
    return {
        "candidate": candidate,
        "attempt_id": identity["attempt_id"],
        "case_id": identity["case_id"],
        "report_path": str(report_path),
        "report_sha256": report_sha,
        "receipt_path": str(receipt_path),
        "receipt_sha256": receipt_sha,
        "actual_counts": compact,
        "basic_placement_and_mk50": "passed",
        "numerical_precision": "diagnostic_only; original threshold retained and not accepted",
        "official_csv_sha256_producer_attested": provenance.get("official_csv_sha256"),
        "generated_bi4_sha256_producer_attested": provenance.get("generated_bi4_sha256"),
        "short_solver_authorized_by_binder": False,
    }


def null_future(candidate: str) -> dict[str, Any]:
    return {
        "native_receipt_sha256": None,
        "solver_output_root": None,
        "typed_h5_sha256": None,
        "xmf_manifest_sha256": None,
        "bed_audit_report_sha256": None,
        "full16_or_full801_authorized": False,
        "independent_case_count_increment": 0,
        "candidate": candidate,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", choices=("A080", "A120"), required=True)
    parser.add_argument("--gencase-receipt", type=Path)
    parser.add_argument("--prepared-report", type=Path)
    parser.add_argument("--initial-qa-report", type=Path)
    parser.add_argument("--initial-qa-receipt", type=Path)
    parser.add_argument("--output-summary", type=Path, required=True)
    args = parser.parse_args()
    package_root = Path(__file__).resolve().parents[1]
    att = load_attestation(package_root, args.candidate)
    supplied = (args.gencase_receipt, args.prepared_report,
                args.initial_qa_report, args.initial_qa_receipt)
    require((args.gencase_receipt is None) == (args.prepared_report is None),
            "GenCase receipt and prepared report must be supplied together")
    require((args.initial_qa_report is None) == (args.initial_qa_receipt is None),
            "initial QA report and receipt must be supplied together")
    require(args.initial_qa_report is None or args.gencase_receipt is not None,
            "initial QA cannot be bound without actual GenCase metadata")
    gencase = None
    qa = None
    if args.gencase_receipt is not None:
        gencase = bind_gencase(args.gencase_receipt, args.prepared_report,
                               args.candidate, att)
        if args.initial_qa_report is not None:
            qa = bind_initial_qa(args.initial_qa_report, args.initial_qa_receipt,
                                 args.candidate, att, gencase)
    summary = {
        "schema": "ds02.f5.c082s1.native-enable-binding.fresh104.v1",
        "status": "ready_for_root_review_but_disabled" if qa else "awaiting_actual_root_bound_qa",
        "source_only": True,
        "candidate": args.candidate,
        "case_id": CASE,
        "gencase": gencase,
        "initial_qa": qa,
        "runtime_contract": {
            "native_solver_dimension": 3,
            "frames": 51,
            "save_interval_s": 0.02,
            "event_window_s": [0.0, 1.0],
            "cpu_threads": 2,
            "estimated_peak_gpu_mib": 4096,
            "official_solver_path": "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64",
            "official_solver_sha256_producer_declared": "0415b10e5e32af8b8b7ad2a703f9043dca67dfcf7626eb98f1c05a50856fde29",
            "cwd_must_be_actual_gencase_prepared_root": True,
            "root230_gpu_protection_required": True,
            "root_solver_concurrency_cap": 8,
        },
        "motion_asset": {
            "sha256": att["motion_asset_sha256"],
            "rows": 641,
            "provenance": "Root425 motion-transform report; producer-declared and copied as metadata only",
        },
        "source_provenance": {
            "fresh103_parent_commit": "80633ba02d75ca7395dd13821c4ed5315e598542",
            "root426_runner_git_at_launch": att.get("gencase_root426_runner_git_at_launch", "unknown-in-receipt"),
            "root230_entrypoint_sha256": "7f703fb94e17c2e2800873f4fcc021f9cd5f8201076afd8e10e3bc6a2d03396e",
            "root230_policy_sha256": "c9103e306f87bb5af871c5de28d9939aa05f0c95c72e1630778f4bcf50e91ab5",
            "root142_policy_sha256": "2649eedbcf4816f8d2fa7b2182828ea8b3ce107ef47f25c56780d29c5138def5",
        },
        "future": null_future(args.candidate),
        "science_payloads_read_or_hashed_by_binder": False,
        "jobs_started_by_binder": False,
        "shared_state_modified_by_binder": False,
        "acceptance": "not granted; Root must review actual 51-frame native result and framewise bed audit",
    }
    # Keep the optional input tuple visible in the output for auditability without
    # treating missing future products as evidence.
    summary["input_arguments_supplied"] = [str(v) if v is not None else None for v in supplied]
    args.output_summary.parent.mkdir(parents=True, exist_ok=True)
    args.output_summary.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n",
                                  encoding="utf-8")
    print(json.dumps({"status": summary["status"], "candidate": args.candidate,
                      "future_native_receipt_sha256": None,
                      "short_solver_authorized": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
