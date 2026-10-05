#!/usr/bin/env python3
"""Validate the fresh115 disabled metadata pack without opening science data."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any

PKG = Path(__file__).resolve().parents[1]
COUNTS = {"dimension": 3, "fixed": 158559, "floating": 0, "fluid": 31658, "moving": 4210, "total": 194427}
TAGS = ("A080", "A120")
SCIENCE_SUFFIXES = {".dat", ".bi4", ".h5", ".hdf5", ".csv", ".vtk", ".vtu", ".npy", ".npz"}
HASH_KEYS = ("sha256", "hash", "digest")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"JSON object required: {path}")
    return value


def sha_source(path: Path) -> str:
    require(path.suffix.lower() not in SCIENCE_SUFFIXES, f"science hash attempted: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assert_null_hashes(value: Any, context: str) -> None:
    """Reject future product hashes while allowing static input hashes."""
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = str(key).lower()
            if any(token in lowered for token in HASH_KEYS) and ("future" in context or "output" in context or "receipt" in context or "trajectory" in context):
                require(item is None, f"future hash is populated: {context}.{key}")
            assert_null_hashes(item, f"{context}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            assert_null_hashes(item, f"{context}[{index}]")


def validate_manifest() -> dict[str, Any]:
    manifest = load(PKG / "manifest.json")
    require(manifest.get("schema") == "ds02.f5.c082s1.fresh115-source-manifest.v1", "manifest schema")
    require(manifest.get("status") == "root575_full801_downstream_disabled_root574_gate_wait", "manifest status")
    require(manifest.get("validator_report_excluded_from_manifest") is True, "validator exclusion")
    require(manifest.get("source109_modified") is False and manifest.get("source097_modified") is False and manifest.get("source098_modified") is False, "upstream mutation")
    require(manifest.get("science_payloads_read_or_hashed_by_source_builder") is False, "science provenance")
    require(manifest.get("jobs_started") is False and manifest.get("shared_state_modified") is False, "side effects")
    require(manifest.get("full801_authorized") is False and manifest.get("fresh110_full24_gate") == "WAIT/null", "gate state")
    files = manifest.get("files")
    require(isinstance(files, dict) and files, "manifest files")
    require("metadata/fresh115-validator-report.json" not in files, "validator self reference")
    for relative, expected in files.items():
        path = PKG / relative
        require(path.is_file(), f"missing manifest file: {relative}")
        require(path.suffix.lower() not in SCIENCE_SUFFIXES, f"science file in package: {relative}")
        require(sha_source(path) == expected, f"manifest hash mismatch: {relative}")
    return manifest


def validate_gate() -> dict[str, Any]:
    gate = load(PKG / "metadata/root574-gate.json")
    require(gate.get("schema") == "ds02.f5.c082s1.root574-to-root575-full801-gate.fresh115.v1", "gate schema")
    require(gate.get("status") == "WAIT/root574_short_window_visual_review_record", "gate status")
    require(gate.get("root574_short_window_visual_pass") is None, "future short review")
    require(all(gate.get(key) is None for key in ("root574_receipt", "root574_report", "root574_receipt_sha256", "root574_report_sha256")), "future gate outputs")
    require(gate.get("root575_native_launch_allowed") is False and gate.get("root575_requires_manual_root_review") is True, "native gate")
    require(gate.get("short_window_can_authorize_current_A080_A120_full801_only_after_root574") is True, "current gate semantics")
    require(gate.get("short_window_can_authorize_new_fresh110_full24s_1201") is False and gate.get("six_fresh110_full24s_1201_gate") == "WAIT/null", "new six gate")
    return gate


def validate_source_files() -> None:
    for path in sorted((PKG / "scripts").glob("*.py")) + sorted((PKG / "workers").glob("*.py")):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    workers = {path.name: path.read_text(encoding="utf-8") for path in (PKG / "workers").glob("*.py")}
    require(set(workers) == {"bed_audit_A080_full801.py", "bed_audit_A120_full801.py", "export_xmf_legacy_aware.py"}, "ambiguous worker set")
    for tag in TAGS:
        text = workers[f"bed_audit_{tag}_full801.py"]
        require('BINDING_SCHEMA = "ds02.f5.c082s1.full-event-bed-audit-binding.fresh115.v1"' in text, f"{tag} worker schema")
        require("EXPECTED_FRAMES = 801" in text and "EXPECTED_PARTICLE_AXIS = 194427" in text and "EXPECTED_FLUID_PARTICLES = 31658" in text, f"{tag} worker axis")
        require("EXPECTED_FIXED_PARTICLES = 158559" in text and "EXPECTED_MOVING_PARTICLES = 4210" in text, f"{tag} worker counts")
        require("DEPTH_TOLERANCES_M = (DP_M, 2.0 * DP_M)" in text, f"{tag} penetration bins")
        require("native_bed_mk" in text and "SOURCE_H5_SCOPE_SCHEMA" in text, f"{tag} marker/scope logic")


def validate_local_hashes(request: dict[str, Any], label: str) -> None:
    files = request.get("input_files", [])
    hashes = request.get("input_sha256", {})
    provenance = request.get("input_sha256_provenance", {})
    require(isinstance(files, list) and isinstance(hashes, dict) and isinstance(provenance, dict), f"{label} input closure")
    require(set(files) <= set(hashes) and set(files) <= set(provenance), f"{label} input hash closure")
    for raw in files:
        require(not any(str(raw).lower().endswith(suffix) for suffix in SCIENCE_SUFFIXES), f"{label} science input path")
        if str(raw).startswith("<root-bind:"):
            require(hashes[raw] is None, f"{label} future bind hash")
        path = Path(raw)
        if path.is_file() and str(PKG) in str(path):
            require(path.suffix.lower() not in SCIENCE_SUFFIXES, f"{label} local science file")
            require(hashes[raw] == sha_source(path), f"{label} local hash {raw}")


def validate_common_request(request: dict[str, Any], tag: str, kind: str, gate: dict[str, Any]) -> None:
    label = f"{tag}/{kind}"
    require(request.get("schema") == "ds02.runner-request.v2", f"{label} schema")
    require(request.get("candidate_id") == f"C082S1_MOTION_{tag}" and request.get("case_id") == "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1", f"{label} identity")
    require(request.get("disabled") is True and request.get("execution_allowed") is False and request.get("launch") is False and request.get("launch_allowed") is False, f"{label} disabled")
    require(request.get("solver_allowed") is False and request.get("conversion_allowed") is False and request.get("arrays_allowed") is False and request.get("array_edit_allowed") is False, f"{label} safety")
    require(request.get("source_only") is True and request.get("shared_registry_write_allowed") is False, f"{label} source-only")
    require(request.get("expected_frames") == 801 and request.get("expected_particle_axis") == 194427 and request.get("expected_particles") == 194427, f"{label} frame axis")
    require(request.get("expected_dimension") == 3 and request.get("expected_fluid_particles") == 31658 and request.get("expected_fixed_particles") == 158559 and request.get("expected_moving_particles") == 4210, f"{label} counts")
    if kind in {"native", "bed"}:
        require(request.get("native_bed_mk") == 50 and request.get("source_mkbound") == 40, f"{label} bed marker")
    else:
        require(request.get("native_bed_marker_mk") == 50 and request.get("source_bed_marker_mkbound") == 40, f"{label} bed marker")
    require(request.get("full801_authorized") is False and request.get("q_n_granted") is False, f"{label} authorization")
    require(request.get("root575_gate") == gate, f"{label} root575 gate")
    require(request.get("resource_window", {}).get("gpu_hours") == 512 and request.get("resource_window", {}).get("cpu_core_hours") == 3840, f"{label} resource window")
    validate_local_hashes(request, label)
    assert_null_hashes(request.get("future_output_hashes", {}), f"{label}.future_output_hashes")


def validate_candidate(tag: str, gate: dict[str, Any]) -> dict[str, Any]:
    bdir = PKG / "bindings"
    rdir = PKG / "requests"
    physical = load(bdir / f"{tag}-full801-physical-binding.json")
    native = load(bdir / f"{tag}-full801-native-binding.json")
    xmf = load(bdir / f"{tag}-full801-xmf-binding.json")
    bed = load(bdir / f"{tag}-full801-bed-audit-binding.json")
    render = load(bdir / f"{tag}-full801-render-binding.json")
    require(physical.get("schema") == "ds02.f5.c082s1.full801-physical-binding.fresh115.v1", f"{tag} physical schema")
    require(native.get("schema") == "ds02.f5.c082s1.root575-full801-native-binding.fresh115.v1", f"{tag} native schema")
    require(xmf.get("schema") == "ds02.f5.c082s1.legacy-aware-xmf-binding.fresh115.v1", f"{tag} XMF schema")
    require(bed.get("schema") == "ds02.f5.c082s1.full-event-bed-audit-binding.fresh115.v1", f"{tag} bed schema")
    require(render.get("schema") == "ds02.f5.c082s1.root023-full801-render-binding.fresh115.v1", f"{tag} render schema")
    require(native.get("actual_counts") == COUNTS, f"{tag} native counts")
    require(bed.get("expected_particle_axis") == 194427 and bed.get("expected_frames") == 801 and bed.get("actual_counts", {}).get("total_particles") == 194427, f"{tag} bed axis")
    require(bed.get("native_bed_marker_mk") == 50 and bed.get("source_bed_marker_mkbound") == 40, f"{tag} bed marker")
    require(bed.get("full801_authorized") is False and bed.get("repair_success") == "unknown_until_actual_full801_particle_audit_and_root_review", f"{tag} bed gate")
    require(bed.get("worker_contract", {}).get("scan_all_801_frames") is True and bed.get("worker_contract", {}).get("thresholds_diagnostic_only") is True, f"{tag} bed worker contract")
    require(xmf.get("expected_frames") == 801 and xmf.get("expected_particles") == 194427 and xmf.get("native_fields_preserved") is True, f"{tag} XMF contract")
    require(xmf.get("source_h5_scope_schema") == "legacy-owner-scope.v0" and xmf.get("source_h5_scope_status") == "legacy_incomplete; no cross-resolution physical claim", f"{tag} legacy scope")
    require(render.get("expected_frames") == 801 and render.get("expected_particles") == 194427 and render.get("camera_bounds") is None and render.get("domain_bounds") is None, f"{tag} render contract")
    require(render.get("camera_bounds_policy") == "auto_scan_all_actual_valid_native_points", f"{tag} camera policy")
    request_names = {
        "native": f"{tag}-full801-native-request.json",
        "typed": f"{tag}-full801-typed-request.json",
        "xmf": f"{tag}-full801-xmf-request.json",
        "bed": f"{tag}-full801-bed-audit-request.json",
        "render": f"{tag}-full801-render-root023-request.json",
    }
    requests = {kind: load(rdir / name) for kind, name in request_names.items()}
    for kind, request in requests.items():
        validate_common_request(request, tag, kind, gate)
    native_req = requests["native"]
    require(native_req.get("attempt_id", "").endswith("-root575"), f"{tag} native attempt suffix")
    require(native_req.get("cpu_task_kind") == "solver" and native_req.get("kind") == "qualification", f"{tag} native kind")
    require(native_req.get("depends_on_attempt") == "<root-bind:root574_full801_enablement>", f"{tag} native gate dependency")
    typed_req = requests["typed"]
    require(typed_req.get("cpu_task_kind") == "conversion" and typed_req.get("depends_on_attempt") == native_req.get("attempt_id"), f"{tag} typed dependency")
    require(typed_req.get("expected_frames") == 801 and typed_req.get("expected_dimension") == 3, f"{tag} typed dimensions")
    xmf_req = requests["xmf"]
    require(xmf_req.get("cpu_task_kind") == "audit" and xmf_req.get("depends_on_attempt") == typed_req.get("attempt_id"), f"{tag} XMF dependency")
    bed_req = requests["bed"]
    require(bed_req.get("cpu_task_kind") == "audit" and bed_req.get("depends_on_attempt") == xmf_req.get("attempt_id"), f"{tag} bed dependency")
    require(bed_req.get("estimated_storage_bytes", 0) > 0 and bed_req.get("resource_window", {}).get("home_min_free_bytes") == 536870912000, f"{tag} bed runtime contract")
    render_req = requests["render"]
    require(render_req.get("cpu_task_kind") == "audit" and render_req.get("depends_on_attempt") == xmf_req.get("attempt_id"), f"{tag} render dependency")
    require(render_req.get("renderer_sha256") == "5e78f7b92ad7c6f1d15902e3ccacc9099affb04b1b992a42f540eb88241bde66", f"{tag} Root023 renderer")
    return {"tag": tag, "status": "disabled", "native_attempt": native_req["attempt_id"], "typed_attempt": typed_req["attempt_id"], "xmf_attempt": xmf_req["attempt_id"], "bed_attempt": bed_req["attempt_id"], "render_attempt": render_req["attempt_id"]}


def main() -> int:
    validate_manifest()
    validate_source_files()
    gate = validate_gate()
    plan = load(PKG / "metadata/fresh115-source-plan.json")
    provenance = load(PKG / "metadata/fresh115-root575-provenance.json")
    require(plan.get("candidates") == list(TAGS) and plan.get("all_requests_disabled") is True, "source plan")
    require(plan.get("root574_gate_status") == gate["status"] and plan.get("six_new_full24_conditions_gate") == "WAIT/null", "plan gates")
    require(plan.get("exact_dp_lattice_negative_preserved") is True and plan.get("no_qn_or_case_credit") is True, "precision/credit policy")
    require(provenance.get("counts") == COUNTS and provenance.get("native_axis") == 194427 and provenance.get("fluid_uid_denominator") == 31658, "provenance counts")
    require(provenance.get("exact_dp_lattice_negative", {}).get("accepted") is False, "precision negative")
    results = [validate_candidate(tag, gate) for tag in TAGS]
    report = {
        "schema": "ds02.f5.c082s1.fresh115-validator-report.v1",
        "status": "passed_root575_disabled_full801_downstream_metadata_contract",
        "candidates": results,
        "root574_gate": "WAIT/null",
        "full801_authorized": False,
        "six_new_full24s_1201_gate": "WAIT/null",
        "exact_dp_lattice_negative_preserved": True,
        "science_payloads_read_or_hashed_by_validator": False,
    }
    out = PKG / "metadata/fresh115-validator-report.json"
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
