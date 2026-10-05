#!/usr/bin/env python3
"""Metadata/source contract validator for the disabled fresh104 handoff.

Only JSON reports/receipts and source/definition files are inspected.  The
validator explicitly refuses science payload suffixes, never starts a worker,
and never changes a runner or shared registry state.
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any

HEX = set("0123456789abcdefABCDEF")
SCIENCE_SUFFIXES = {".bi4", ".csv", ".h5", ".hdf5", ".vtk", ".vtu", ".npy", ".npz", ".dat"}
SOURCE_SUFFIXES = {".json", ".py", ".xml", ".md", ".txt"}
CASE = "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1"
GEN_SCHEMA = "ds02.root.actual-native-source-preflight.v1"
QA_SCHEMA = "ds02.f5.c082s1.stage1-placement-mk50-audit.fresh103.v1"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha256(path: Path) -> str:
    require(path.suffix.lower() in SOURCE_SUFFIXES,
            f"validator refuses non-source/non-JSON digest: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> tuple[dict[str, Any], str]:
    require(path.suffix.lower() == ".json", f"JSON metadata required: {path}")
    require(path.is_file(), f"missing metadata: {path}")
    digest = sha256(path)
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"JSON object required: {path}")
    return value, digest


def check_path_hashes(request: dict[str, Any], package_root: Path) -> dict[str, Any]:
    checked = 0
    placeholders = 0
    for raw in request.get("input_files", []):
        path_text = str(raw)
        if path_text.startswith("<root-bind:"):
            placeholders += 1
            continue
        path = Path(path_text)
        if path.suffix.lower() == ".dat":
            # Motion is an actual Root425 producer asset.  Its digest is
            # copied from the JSON producer report; this validator refuses to
            # open the DAT and only checks the declared identity.
            require(path_text == request.get("motion_asset_path"),
                    f"motion DAT is not the request-bound producer asset: {path}")
            declared = request.get("input_sha256", {}).get(path_text)
            require(declared == request.get("motion_asset_sha256") and
                    isinstance(declared, str) and len(declared) == 64,
                    "motion DAT lacks the producer-declared SHA")
            continue
        if path.suffix.lower() in SCIENCE_SUFFIXES:
            raise ValueError(f"native request lists forbidden science payload: {path}")
        if path.name == "DualSPHysics5.4_linux64":
            # The runner's declared binary SHA is provenance; this source
            # validator must not open or hash the solver binary.
            require(request.get("input_sha256", {}).get(path_text),
                    "official solver binary needs its declared SHA")
            continue
        require(path.is_file(), f"static request input missing: {path}")
        declared = request.get("input_sha256", {}).get(path_text)
        require(isinstance(declared, str) and len(declared) == 64,
                f"static input has no SHA: {path}")
        require(sha256(path) == declared, f"static input SHA mismatch: {path}")
        checked += 1
    return {"static_inputs_hashed": checked, "root_bind_placeholders": placeholders}


def receipt_identity(value: dict[str, Any]) -> dict[str, Any]:
    request = value.get("request")
    request = request if isinstance(request, dict) else {}
    return {"attempt_id": request.get("attempt_id") or value.get("attempt_id"),
            "case_id": request.get("case_id") or value.get("case_id")}


def check_actual_candidate(att: dict[str, Any], candidate: str) -> dict[str, Any]:
    receipt_path = Path(att["gencase_receipt_path"])
    prepared_path = Path(att["prepared_report_path"])
    receipt, receipt_sha = load(receipt_path)
    prepared, prepared_sha = load(prepared_path)
    require(receipt_sha == att["gencase_receipt_sha256"], f"{candidate} GenCase receipt SHA mismatch")
    require(prepared_sha == att["prepared_report_sha256"], f"{candidate} prepared report SHA mismatch")
    require(receipt.get("schema") == "ds02.execution-receipt.v1" and receipt.get("status") == "completed",
            f"{candidate} GenCase receipt is not completed")
    require(int(receipt.get("returncode", -1)) == 0, f"{candidate} GenCase returncode != 0")
    rid = receipt_identity(receipt)
    require(rid["attempt_id"] == att["gencase_attempt_id"] and rid["case_id"] == CASE,
            f"{candidate} GenCase receipt identity mismatch")
    require(prepared.get("schema") == GEN_SCHEMA, f"{candidate} prepared schema mismatch")
    counts = prepared.get("generated_xml_particle_counts")
    require(prepared.get("actual_total_particles") == 194427 and counts == {
        "fixed": 158559, "moving": 4210, "floating": 0, "fluid": 31658},
        f"{candidate} prepared count evidence mismatch")
    require(prepared.get("xml_sha256") == att["xml_sha256"] and
            prepared.get("bi4_sha256") == att["bi4_sha256"],
            f"{candidate} producer payload attestations mismatch")
    constants = prepared.get("actual_generated_constants", {})
    require(str(constants.get("data2d", {}).get("value", "")).lower() in {"false", "0"},
            f"{candidate} producer is not 3-D")
    qa_report_path = Path(att["qa_report_path"])
    qa_receipt_path = Path(att["qa_receipt_path"])
    qa, qa_sha = load(qa_report_path)
    qrec, qrec_sha = load(qa_receipt_path)
    require(qa_sha == att["qa_report_sha256"] and qrec_sha == att["qa_receipt_sha256"],
            f"{candidate} QA metadata SHA mismatch")
    require(qa.get("schema") == QA_SCHEMA and qa.get("status") == "completed_stage1_placement_mk50_diagnostic",
            f"{candidate} QA schema/status mismatch")
    require(qa.get("all_basic_placement_checks_pass") is True and
            qa.get("numerical_precision_result_accepted") is False,
            f"{candidate} QA placement/precision semantics mismatch")
    require(qrec.get("status") == "completed" and int(qrec.get("returncode", -1)) == 0,
            f"{candidate} QA receipt is not completed")
    qid = receipt_identity(qrec)
    require(qid["attempt_id"] == qa.get("qa_attempt_id") and qid["case_id"] == CASE,
            f"{candidate} QA receipt identity mismatch")
    require(qa.get("gencase_attempt_id") == att["gencase_attempt_id"],
            f"{candidate} QA GenCase dependency mismatch")
    actual = qa.get("actual_counts")
    require(isinstance(actual, dict) and actual.get("total_particles") == 194427 and
            actual.get("fluid_particles") == 31658 and actual.get("solver_dimension") == 3,
            f"{candidate} QA actual count/dimension mismatch")
    checks = qa.get("checks", {})
    for name in ("all_native_rows_finite", "uid_unique_consecutive",
                 "native_type_set_and_counts_match_actual_producer",
                 "fixed_moving_floating_fluid_spatial_no_overlap",
                 "fluid_inside_exact_source_box", "fluid_initial_above_exact_continuous_bed",
                 "fluid_has_exact_15_transverse_levels", "central_mk50_surface_support_is_present"):
        require(checks.get(name) is True, f"{candidate} QA check is not true: {name}")
    boundary = qa.get("review_boundary", {})
    require(boundary.get("short_solver_authorized") is False and
            boundary.get("full801_authorized") is False and boundary.get("q_n_granted") is False,
            f"{candidate} QA boundary incorrectly grants execution")
    return {"gencase_receipt_sha256": receipt_sha, "prepared_report_sha256": prepared_sha,
            "qa_report_sha256": qa_sha, "qa_receipt_sha256": qrec_sha,
            "qa_basic_placement": True, "qa_precision_accepted": False}


def check_worker_and_native_request(package_root: Path, candidate: str,
                                    att: dict[str, Any]) -> dict[str, Any]:
    qa_request = package_root.parent / "root_followup_103_stage1_f5_c082s1_typed_xmf_bed_binding_disabled_v1" / "requests" / f"{candidate}-initial-qa-mk50-request.json"
    qa_request_data, qa_request_sha = load(qa_request)
    command = qa_request_data.get("command", [])
    require(len(command) == 6 and command[2] == "--binding" and command[4] == "--output-dir",
            f"{candidate} fresh103 QA argv contract mismatch")
    worker_path = Path(command[1])
    require(worker_path.is_file(), f"fresh103 QA worker missing: {worker_path}")
    worker_source = worker_path.read_text(encoding="utf-8")
    ast.parse(worker_source, filename=str(worker_path))
    for token in ("--binding", "--output-dir", "LATTICE_THRESHOLD",
                  "numerical_precision_result_accepted", "arrays_opened_by_source_agent"):
        require(token in worker_source, f"fresh103 QA worker lacks contract token: {token}")
    native_path = package_root / "requests" / f"{candidate}-native-enable-request.json"
    native, native_sha = load(native_path)
    require(native.get("schema") == "ds02.runner-request.v2", f"{candidate} native schema mismatch")
    require(native.get("kind") == "qualification" and native.get("cpu_task_kind") == "solver",
            f"{candidate} native runtime kind mismatch")
    require(native.get("disabled") is True and native.get("execution_allowed") is False and
            native.get("launch") is False and native.get("solver_allowed") is False,
            f"{candidate} native request is executable")
    require(native.get("case_id") == CASE and native.get("expected_dimension") == 3 and
            native.get("expected_frames") == 51, f"{candidate} native solver shape mismatch")
    require(native.get("command") == [
        "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64",
        "<root-bind:gencase_prefix>", "{attempt_root}/solver_output", "-tmax:1.0", "-tout:0.02"],
        f"{candidate} native argv mismatch")
    require(native.get("gencase_attempt_id") == att["gencase_attempt_id"],
            f"{candidate} native GenCase dependency mismatch")
    require(native.get("producer_attested_gencase_bi4_sha256") == att["bi4_sha256"],
            f"{candidate} native BI4 attestation mismatch")
    require(native.get("actual_initial_qa_report_sha256") == att["qa_report_sha256"] and
            native.get("actual_initial_qa_receipt_sha256") == att["qa_receipt_sha256"],
            f"{candidate} native QA binding mismatch")
    require(native.get("future_output_hashes") and
            all(value is None for value in native["future_output_hashes"].values()),
            f"{candidate} native future hashes are not null")
    closure = check_path_hashes(native, package_root)
    return {"qa_request_sha256": qa_request_sha, "native_request_sha256": native_sha,
            "worker_sha256": sha256(worker_path), **closure}


def main() -> int:
    package_root = Path(__file__).resolve().parents[1]
    attestation, _ = load(package_root / "metadata" / "root426-qa441-actual-attestation.json")
    results = {}
    for candidate in ("A080", "A120"):
        results[candidate] = {
            **check_actual_candidate(attestation["candidates"][candidate], candidate),
            **check_worker_and_native_request(package_root, candidate,
                                               attestation["candidates"][candidate]),
        }
    report = {
        "schema": "ds02.f5.c082s1.fresh104-source-validator-report.v1",
        "status": "passed_metadata_and_source_contract",
        "candidates": results,
        "worker_argv_and_schema_checked": True,
        "actual_gencase_and_qa_json_checked": True,
        "producer_bi4_and_motion_hashes_reused_without_payload_read": True,
        "future_native_receipts_and_science_hashes_null": True,
        "science_payloads_read_or_hashed_by_validator": False,
        "jobs_started": False,
        "shared_state_modified": False,
        "source_only": True,
    }
    out = package_root / "metadata" / "fresh104-validator-report.json"
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "candidates": sorted(results),
                      "science_payloads_read_or_hashed_by_validator": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
