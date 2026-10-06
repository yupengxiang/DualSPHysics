#!/usr/bin/env python3
"""Metadata-only preflight for the fresh163 M086 Root963 bed binding.

This validator reads JSON/XML/Python metadata only.  It deliberately refuses to
hash or open H5/BI4/CSV/DAT/VTK/array payloads and never launches a worker.
"""
from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

PACKAGE = Path(__file__).resolve().parents[1]
OLD_PACKAGE = PACKAGE.parent / "root_followup_161_m086_case_rebind_adapter_v2_disabled_v1"
OLD_BINDING = OLD_PACKAGE / "bindings/M086_T085-case-rebind-bed-binding.json"
OLD_REQUEST = OLD_PACKAGE / "requests/M086_T085-case-rebind-bed-request.json"
ADAPTER = OLD_PACKAGE / "workers/identity_bound_bed_audit_fresh161.py"
ORIGINAL = Path(
    "/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/"
    "root_followup_138_stage1_f5_remaining10_full801_downstream_disabled_v1/"
    "workers/bed_audit_full801_fresh138.py"
)
BINDING = PACKAGE / "bindings/M086_T085-actual963-bed-binding.json"
REQUEST = PACKAGE / "requests/M086_T085-actual963-bed-request.json"
MANIFEST = PACKAGE / "manifest.json"
REPORT = PACKAGE / "metadata/fresh163-validator-report.json"

ACTUAL_ROOT = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/"
    "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M086_T085_NEXT34/"
)
GEN_ROOT = ACTUAL_ROOT / "root-stage1-f5-next34-m086_t085-own824-genuine-gencase-root848"
QA_ROOT = ACTUAL_ROOT / "root-stage1-f5-next34-m086_t085-own848-initial-placement-mk50-root849"
NATIVE_ROOT = ACTUAL_ROOT / "root-stage1-f5-next34-m086_t085-own848849-full801-native-root850"
TYPED_ROOT = ACTUAL_ROOT / "root-stage1-f5-next34-m086_t085-own850-full801-typed-nvme-root864"
XMF_ROOT = ACTUAL_ROOT / "root-stage1-f5-m086-t085-actual864-full801-N3-XMF-root963"
GEN_RECEIPT = GEN_ROOT / "execution-receipt.json"
QA_RECEIPT = QA_ROOT / "execution-receipt.json"
QA_REPORT = QA_ROOT / "initial-qa/placement/c082s1-stage1-placement-mk50-audit.json"
NATIVE_RECEIPT = NATIVE_ROOT / "execution-receipt.json"
TYPED_RECEIPT = TYPED_ROOT / "execution-receipt.json"
TYPED_REPORT = TYPED_ROOT / "typed/conversion-report.json"
XMF_RECEIPT = XMF_ROOT / "execution-receipt.json"
XMF_MANIFEST = XMF_ROOT / "xmf/manifest.json"
XDMF = XMF_ROOT / "xmf/case.xmf"

PRODUCER_CASE_ID = "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M086_T085_NEXT34"
PHYSICAL_CASE_ID = "F5_COMPACT_RUNUP_RECOVERY_C082S1_M086_T085"
XMF_ATTEMPT = "root-stage1-f5-m086-t085-actual864-full801-N3-XMF-root963"
EXPECTED_COUNTS = {
    "fixed_particles": 158559,
    "floating_particles": 0,
    "fluid_particles": 31658,
    "moving_particles": 4210,
    "solver_dimension": 3,
    "total_particles": 194427,
    "xml_particle_counts": {
        "fixed": 158559,
        "floating": 0,
        "fluid": 31658,
        "moving": 4210,
    },
}
MUTABLE_BINDING_FIELDS = {
    "actual_counts",
    "initial_qa_output_root",
    "xmf_manifest",
    "xmf_manifest_sha256",
    "xdmf",
    "xdmf_sha256",
    "xmf_receipt",
    "xmf_receipt_sha256",
    "xmf_attempt_id",
}
SCIENCE_SUFFIXES = {
    ".h5", ".hdf5", ".bi4", ".ibi4", ".csv", ".dat", ".vtk", ".vtu",
    ".npy", ".npz", ".png",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def load_json(path: Path) -> dict[str, Any]:
    require(path.is_file(), f"missing JSON metadata: {path}")
    value = json.loads(path.read_text())
    require(isinstance(value, dict), f"JSON object required: {path}")
    return value


def sha256_metadata(path: Path) -> str:
    require(path.is_file(), f"missing metadata input: {path}")
    require(path.suffix.lower() not in SCIENCE_SUFFIXES, f"science payload hash forbidden: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize_counts(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "fixed_particles": int(value["fixed_particles"]),
        "floating_particles": int(value["floating_particles"]),
        "fluid_particles": int(value["fluid_particles"]),
        "moving_particles": int(value["moving_particles"]),
        "solver_dimension": int(value["solver_dimension"]),
        "total_particles": int(value["total_particles"]),
        "xml_particle_counts": {
            key: int(value["xml_particle_counts"][key])
            for key in ("fixed", "floating", "fluid", "moving")
        },
    }


def receipt_completed(path: Path, attempt_id: str) -> dict[str, Any]:
    value = load_json(path)
    require(value.get("status") == "completed", f"{path}: status is not completed")
    require(value.get("returncode") == 0, f"{path}: returncode is not zero")
    request = value.get("request", {})
    require(request.get("attempt_id") == attempt_id, f"{path}: attempt identity mismatch")
    require(request.get("case_id") == PRODUCER_CASE_ID, f"{path}: case identity mismatch")
    require(value.get("output_root") == str(path.parent), f"{path}: output_root mismatch")
    return value


def strip_allowed(value: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(value)
    for key in MUTABLE_BINDING_FIELDS:
        result.pop(key, None)
    return result


def compare_request_immutable(old: dict[str, Any], new: dict[str, Any]) -> None:
    # Request identity and source-input closure necessarily change for a new
    # disabled successor.  All execution/source/physics policy fields remain
    # byte-equivalent to fresh161.
    critical = (
        "kind", "cpu_task_kind", "cpu_threads", "disabled", "execution_allowed",
        "launch", "launch_allowed", "solver_allowed", "source_only",
        "full801_authorized", "full801_visual_gate", "case_credit",
        "independent_case_count_increment", "dp_m", "expected_counts",
        "expected_dimension", "expected_frames", "expected_particle_axis",
        "expected_particles", "family_id", "environment_policy",
        "estimated_storage_bytes", "resource_guard", "root142_registration_required",
        "root_review_required", "root142_runtime", "physical_case_id",
        "producer_case_id", "physical_condition_sha256",
        "source_plan_physical_condition_sha256", "source_h5_legacy_scope_sha256",
        "source_h5_scope_status", "native_bed_marker_mk", "source_bed_marker_mkbound",
        "numerical_logic_unchanged", "science_input_policy",
        "source_agent_did_not_read_or_hash_science_payloads", "q_n_granted",
    )
    for key in critical:
        require(new.get(key) == old.get(key), f"request immutable field changed: {key}")
    old_identity = copy.deepcopy(old.get("identity_adapter", {}))
    new_identity = copy.deepcopy(new.get("identity_adapter", {}))
    old_identity.pop("adapter_worker_sha256", None)
    new_identity.pop("adapter_worker_sha256", None)
    require(new_identity == old_identity, "request identity adapter changed beyond measured worker SHA")


def verify_manifest() -> None:
    manifest = load_json(MANIFEST)
    require(manifest.get("schema") == "ds02.f5.fresh163.manifest.v1", "package manifest schema")
    listed = {entry["path"]: entry["sha256"] for entry in manifest.get("files", [])}
    require("manifest.json" not in listed, "manifest self reference")
    require("metadata/fresh163-validator-report.json" not in listed, "validator report self reference")
    require(listed, "empty package manifest")
    for relative, expected in listed.items():
        path = PACKAGE / relative
        require(path.is_file(), f"manifest file missing: {relative}")
        require(path.suffix.lower() not in SCIENCE_SUFFIXES, f"manifest payload listed: {relative}")
        require(sha256_metadata(path) == expected, f"package file SHA mismatch: {relative}")


def verify_producers(binding: dict[str, Any]) -> dict[str, Any]:
    gen = receipt_completed(GEN_RECEIPT, "root-stage1-f5-next34-m086_t085-own824-genuine-gencase-root848")
    qa = receipt_completed(QA_RECEIPT, "root-stage1-f5-next34-m086_t085-own848-initial-placement-mk50-root849")
    native = receipt_completed(NATIVE_RECEIPT, "root-stage1-f5-next34-m086_t085-own848849-full801-native-root850")
    typed = receipt_completed(TYPED_RECEIPT, "root-stage1-f5-next34-m086_t085-own850-full801-typed-nvme-root864")
    xmf = receipt_completed(XMF_RECEIPT, XMF_ATTEMPT)
    qa_report = load_json(QA_REPORT)
    typed_report = load_json(TYPED_REPORT)
    manifest = load_json(XMF_MANIFEST)

    require(qa_report.get("status") == "completed_stage1_placement_mk50_diagnostic", "QA report status")
    require(qa_report.get("all_basic_placement_checks_pass") is True, "initial placement gate failed")
    require(qa_report.get("stage1_basic_placement_proof") == "pass_excluding_numerical_precision", "QA proof changed")
    require(qa_report.get("numerical_precision_result_accepted") is False, "precision negative was relabeled")
    require(normalize_counts(qa_report["actual_counts"]) == EXPECTED_COUNTS, "QA counts changed")
    bins = qa_report.get("mk50_coverage", {}).get("six_segment_bins", [])
    require(len(bins) == 6 and all(int(row.get("central_abs_y_le_0p01_surface_half_dp_count", 0)) > 0 for row in bins), "Mk50 six-segment support missing")

    require(typed_report.get("conversion_status") == "completed", "typed report status")
    require(typed_report.get("frames") == 801 and typed_report.get("particles") == 194427, "typed dimensions")
    dimension = typed_report.get("solver_dimension", {})
    require(isinstance(dimension, dict) and dimension.get("solver_dimension") == 3, "typed dimension")
    require(50 in set(typed_report.get("typed_identity", {}).get("observed_mks", [])), "typed Mk50 identity")

    require(manifest.get("case_id") == PRODUCER_CASE_ID, "XMF case identity")
    require(manifest.get("physical_case_id") == PHYSICAL_CASE_ID, "XMF physical identity")
    require(manifest.get("frames") == 801 and manifest.get("particles") == 194427, "XMF dimensions")
    require(normalize_counts(manifest["actual_counts"]) == EXPECTED_COUNTS, "XMF actual counts")
    require(manifest.get("root_actual_XMF_attempt_id") == XMF_ATTEMPT, "XMF producer attempt")
    require(manifest.get("xdmf") == str(XDMF), "XMF XDMF path")
    require(manifest.get("xdmf_sha256") == sha256_metadata(XDMF), "XMF XDMF digest")
    require(manifest.get("source_h5_sha256") == binding.get("trajectory_h5_sha256"), "producer H5 attestation mismatch")
    require(manifest.get("physical_condition_sha256") == binding.get("physical_condition_sha256"), "canonical scope changed")
    require(manifest.get("canonical_physical_condition_sha256") == binding.get("physical_condition_sha256"), "canonical XMF scope changed")
    require(manifest.get("source_plan_physical_condition_sha256") == binding.get("source_plan_physical_condition_sha256"), "source-plan scope changed")
    require(manifest.get("source_h5_scope_schema") == binding.get("source_h5_scope_schema"), "legacy scope schema changed")
    require(manifest.get("source_h5_scope_status") == binding.get("source_h5_scope_status"), "legacy scope status changed")

    xmf_request = xmf.get("request", {})
    require(xmf_request.get("execution_allowed") is True and xmf_request.get("disabled") is False, "Root963 producer state unexpected")
    require(xmf_request.get("full801_authorized") is True, "Root963 producer full801 authorization missing")
    return {
        "gencase": {"attempt_id": gen["request"]["attempt_id"], "receipt": str(GEN_RECEIPT), "receipt_sha256": sha256_metadata(GEN_RECEIPT)},
        "initial_qa": {"attempt_id": qa["request"]["attempt_id"], "receipt": str(QA_RECEIPT), "receipt_sha256": sha256_metadata(QA_RECEIPT), "report": str(QA_REPORT), "report_sha256": sha256_metadata(QA_REPORT)},
        "native": {"attempt_id": native["request"]["attempt_id"], "receipt": str(NATIVE_RECEIPT), "receipt_sha256": sha256_metadata(NATIVE_RECEIPT)},
        "typed": {"attempt_id": typed["request"]["attempt_id"], "receipt": str(TYPED_RECEIPT), "receipt_sha256": sha256_metadata(TYPED_RECEIPT), "report": str(TYPED_REPORT), "report_sha256": sha256_metadata(TYPED_REPORT)},
        "xmf": {"attempt_id": XMF_ATTEMPT, "receipt": str(XMF_RECEIPT), "receipt_sha256": sha256_metadata(XMF_RECEIPT), "manifest": str(XMF_MANIFEST), "manifest_sha256": sha256_metadata(XMF_MANIFEST), "xdmf": str(XDMF), "xdmf_sha256": sha256_metadata(XDMF)},
        "counts": EXPECTED_COUNTS,
    }


def main() -> None:
    old_binding = load_json(OLD_BINDING)
    old_request = load_json(OLD_REQUEST)
    binding = load_json(BINDING)
    request = load_json(REQUEST)
    require(sha256_metadata(ADAPTER) == binding["identity_adapter"]["adapter_worker_sha256"], "fresh161 adapter worker SHA")
    require(sha256_metadata(ORIGINAL) == binding["identity_adapter"]["original_worker_sha256"], "original worker SHA")
    require(strip_allowed(binding) == strip_allowed(old_binding), "binding changed outside fresh161 allowlist")
    require(binding.get("case_id") == PRODUCER_CASE_ID and binding.get("physical_case_id") == PHYSICAL_CASE_ID, "binding identity")
    require(binding.get("actual_counts") == old_binding.get("actual_counts"), "actual_counts changed from fresh161")
    require(binding.get("initial_qa_output_root") == old_binding.get("initial_qa_output_root"), "initial QA root changed")
    require(binding.get("disabled") is True and binding.get("execution_allowed") is False and binding.get("launch_allowed") is False and binding.get("solver_allowed") is False, "binding is not disabled")
    require(binding.get("full801_authorized") is False and binding.get("bed_audit_attempt_id") is None, "future bed gate changed")
    require(binding.get("xmf_attempt_id") == XMF_ATTEMPT, "actual XMF attempt not bound")
    for path_key, hash_key in (("xmf_manifest", "xmf_manifest_sha256"), ("xdmf", "xdmf_sha256"), ("xmf_receipt", "xmf_receipt_sha256")):
        path = Path(str(binding[path_key]))
        require(path.is_file() and path.suffix.lower() not in SCIENCE_SUFFIXES, f"bound XMF metadata missing: {path}")
        require(sha256_metadata(path) == binding[hash_key], f"bound XMF metadata SHA mismatch: {path_key}")
    require(binding["xmf_manifest"] == str(XMF_MANIFEST) and binding["xdmf"] == str(XDMF) and binding["xmf_receipt"] == str(XMF_RECEIPT), "wrong Root963 paths")
    qa_receipt = load_json(QA_RECEIPT)
    require(Path(str(qa_receipt.get("output_root"))).resolve() == Path(str(binding["initial_qa_output_root"])).resolve(), "QA root mismatch")
    qa_report = load_json(QA_REPORT)
    require(qa_report.get("actual_counts") == binding.get("actual_counts"), "QA actual_counts mismatch")
    require(normalize_counts(binding["actual_counts"]) == EXPECTED_COUNTS, "binding count contract")
    compare_request_immutable(old_request, request)
    require(request.get("binding") == str(BINDING), "request binding path")
    require(request.get("binding_sha256") == sha256_metadata(BINDING), "request binding SHA")
    require(request.get("xmf_attempt_id") == XMF_ATTEMPT, "request XMF attempt")
    for key in ("xmf_manifest", "xmf_manifest_sha256", "xdmf", "xdmf_sha256", "xmf_receipt", "xmf_receipt_sha256"):
        require(request.get(key) == binding.get(key), f"request/binding XMF field mismatch: {key}")
    require(XMF_ATTEMPT in request.get("depends_on_attempts", []), "Root963 dependency missing")
    require(request.get("identity_adapter", {}).get("adapter_worker_sha256") == sha256_metadata(ADAPTER), "request worker SHA stale")
    require(request.get("disabled") is True and request.get("execution_allowed") is False and request.get("launch") is False and request.get("launch_allowed") is False and request.get("solver_allowed") is False, "request is not disabled")
    require(request.get("full801_authorized") is False and request.get("case_credit") == 0 and request.get("independent_case_count_increment") == 0, "request gate/credit changed")
    require(all(value is None for value in request.get("future_output_hashes", {}).values()), "future output hash populated")
    files = request.get("input_files", [])
    hashes = request.get("input_sha256", {})
    require(set(files) == set(hashes), "request input/hash set mismatch")
    require(all(Path(raw).suffix.lower() not in SCIENCE_SUFFIXES for raw in files), "science input registered by source package")
    for raw in files:
        path = Path(raw)
        require(path.is_file(), f"request input missing: {path}")
        require(sha256_metadata(path) == hashes[raw], f"request input SHA mismatch: {path}")
    require(str(XMF_MANIFEST) in files and str(XDMF) in files and str(XMF_RECEIPT) in files, "actual XMF metadata absent from request closure")
    ET.parse(XDMF)
    producer = verify_producers(binding)
    verify_manifest()
    regression = subprocess.run([sys.executable, str(ADAPTER), "--check"], cwd=str(PACKAGE), capture_output=True, text=True, check=False)
    require(regression.returncode == 0, f"fresh161 CASE_ID regression failed: {regression.stdout} {regression.stderr}")
    report = {
        "schema": "ds02.f5.fresh163.validator-report.v1",
        "status": "passed",
        "source_only": True,
        "science_payload_opened_or_hashed": False,
        "producer": producer,
        "actual_xmf_attempt_id": XMF_ATTEMPT,
        "actual_xmf_metadata_sha256": {
            "manifest": sha256_metadata(XMF_MANIFEST),
            "xdmf": sha256_metadata(XDMF),
            "receipt": sha256_metadata(XMF_RECEIPT),
        },
        "checks": {
            "fresh161_binding_immutable_outside_allowlist": True,
            "fresh161_original_case_id_regression_passed": True,
            "actual_gen848_qa849_native850_typed864_xmf963_completed0": True,
            "actual_counts_and_mk50_placement_bound": True,
            "actual_xmf_manifest_xml_receipt_hashes_bound": True,
            "canonical_source_plan_legacy_scopes_separate": True,
            "execution_source_physics_flags_unchanged": True,
            "disabled_request_and_binding": True,
            "future_bed_hashes_null": True,
            "request_input_hash_closure": True,
            "no_science_payload_access": True,
        },
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
