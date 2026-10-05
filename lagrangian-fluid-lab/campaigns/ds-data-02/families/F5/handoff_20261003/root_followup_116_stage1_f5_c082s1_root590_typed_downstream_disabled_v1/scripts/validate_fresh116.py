#!/usr/bin/env python3
"""Validate fresh116 source metadata without opening scientific products."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any

PKG = Path(__file__).resolve().parents[1]
DATA_CASE = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1")
TAGS = ("A080", "A120")
SCIENCE_SUFFIXES = {".dat", ".bi4", ".h5", ".hdf5", ".csv", ".vtk", ".vtu", ".npy", ".npz"}
COUNTS = {"dimension": 3, "fixed": 158559, "floating": 0, "fluid": 31658, "moving": 4210, "total": 194427}


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


def validate_manifest() -> None:
    manifest = load(PKG / "manifest.json")
    require(manifest.get("schema") == "ds02.f5.c082s1.fresh116-source-manifest.v1", "manifest schema")
    require(manifest.get("status") == "root588_native_approval_root590_typed_downstream_disabled", "manifest status")
    require(manifest.get("validator_report_excluded_from_manifest") is True, "validator exclusion")
    require(manifest.get("fresh115_modified") is False and manifest.get("science_payloads_read_or_hashed_by_source_builder") is False, "source provenance")
    require(manifest.get("jobs_started") is False and manifest.get("shared_state_modified") is False and manifest.get("future_receipts_and_hashes_null") is True, "side effects")
    files = manifest.get("files")
    require(isinstance(files, dict) and files, "manifest files")
    require("metadata/fresh116-validator-report.json" not in files, "manifest self reference")
    for rel, expected in files.items():
        path = PKG / rel
        require(path.is_file(), f"missing manifest file: {rel}")
        require(path.suffix.lower() not in SCIENCE_SUFFIXES, f"science file in package: {rel}")
        require(sha_source(path) == expected, f"manifest hash mismatch: {rel}")


def validate_gate() -> dict[str, Any]:
    gate = load(PKG / "metadata/root574-gate.json")
    require(gate.get("schema") == "ds02.f5.c082s1.root574-to-root590-downstream-gate.fresh116.v1", "gate schema")
    require(gate.get("status") == "PASS/root588_root574_short_window_native_approval_actual", "gate status")
    require(gate.get("root574_short_window_visual_pass") is True and gate.get("root575_native_launch_allowed") is True, "native approval")
    require(gate.get("full801_xmf_bed_render_authorized") is False and gate.get("complete_case_visual_approval") is False, "downstream hold")
    require(gate.get("new_six_full24s1201_authorized") is False and str(gate.get("new_six_full24s1201_gate", "")).startswith("WAIT"), "new six hold")
    approval = Path(gate["root574_approval_path"])
    require(approval.is_file() and sha_source(approval) == gate["root574_approval_sha256"], "Root574 approval binding")
    return gate


def validate_sources() -> None:
    for path in sorted((PKG / "scripts").glob("*.py")) + sorted((PKG / "workers").glob("*.py")):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    workers = {p.name: p.read_text(encoding="utf-8") for p in (PKG / "workers").glob("*.py")}
    require(set(workers) == {"bed_audit_A080_full801.py", "bed_audit_A120_full801.py", "export_xmf_legacy_aware.py"}, "worker set")
    for tag in TAGS:
        text = workers[f"bed_audit_{tag}_full801.py"]
        require("full-event-bed-audit-binding.fresh116.v1" in text and "full-event-bed-footprint-audit.fresh116.v1" in text, f"{tag} worker schema")
        for token in ("EXPECTED_FRAMES = 801", "EXPECTED_PARTICLE_AXIS = 194427", "EXPECTED_FLUID_PARTICLES = 31658", "EXPECTED_FIXED_PARTICLES = 158559", "EXPECTED_MOVING_PARTICLES = 4210", "DEPTH_TOLERANCES_M = (DP_M, 2.0 * DP_M)"):
            require(token in text, f"{tag} worker contract {token}")


def validate_snapshot(tag: str, gate: dict[str, Any]) -> dict[str, Any]:
    path = PKG / "metadata" / f"{tag}-root590-typed-producer-snapshot.json"
    snapshot = load(path)
    require(snapshot.get("schema") == "ds02.f5.c082s1.root590-typed-producer-snapshot.fresh116.v1", f"{tag} snapshot schema")
    require(snapshot.get("attempt_id") == f"root-stage1-f5-c082s1-{tag}-full801-native-typed-575-root590", f"{tag} typed identity")
    require(snapshot.get("expected_frames") == 801 and snapshot.get("expected_particles") == 194427 and snapshot.get("expected_dimension") == 3 and snapshot.get("expected_fluid_particles") == 31658, f"{tag} typed counts")
    require(snapshot.get("root574_gate") == gate and snapshot.get("typed_completed0_required_before_xmf") is True, f"{tag} typed gate")
    receipt = snapshot.get("receipt")
    if receipt is None:
        require(snapshot.get("receipt_sha256") is None and snapshot.get("status") in {None, "not_started_or_receipt_not_yet_published"}, f"{tag} future typed snapshot")
    else:
        receipt_path = Path(receipt)
        require(receipt_path.suffix.lower() == ".json" and receipt_path.is_file(), f"{tag} receipt path")
        require(snapshot.get("receipt_sha256") == sha_source(receipt_path), f"{tag} receipt hash")
        actual = load(receipt_path)
        require(actual.get("request", {}).get("attempt_id") == snapshot.get("attempt_id"), f"{tag} receipt attempt")
        require(snapshot.get("status") == actual.get("status"), f"{tag} receipt status")
    report = snapshot.get("conversion_report")
    if report is not None:
        report_path = Path(report)
        require(report_path.suffix.lower() == ".json" and report_path.is_file(), f"{tag} report path")
        require(snapshot.get("conversion_report_sha256") == sha_source(report_path), f"{tag} report hash")
        report_meta = load(report_path)
        h5_path = snapshot.get("trajectory_h5")
        h5_sha = snapshot.get("trajectory_h5_sha256")
        require(isinstance(h5_path, str) and Path(h5_path).suffix.lower() in {".h5", ".hdf5"}, f"{tag} producer H5 path")
        require(isinstance(h5_sha, str) and len(h5_sha) == 64, f"{tag} producer H5 digest")
        require(report_meta.get("output_hdf5") == h5_path and report_meta.get("output_sha256") == h5_sha, f"{tag} H5 producer attestation")
        require(snapshot.get("h5_producer_attestation", {}).get("source_agent_did_not_open_or_rehash_h5") is True, f"{tag} H5 source provenance")
    else:
        require(snapshot.get("conversion_report_sha256") is None, f"{tag} future report hash")
        require(snapshot.get("trajectory_h5") is None and snapshot.get("trajectory_h5_sha256") is None, f"{tag} future H5 source guard")
    return snapshot


def validate_input_closure(request: dict[str, Any], label: str) -> None:
    files = request.get("input_files", [])
    hashes = request.get("input_sha256", {})
    provenance = request.get("input_sha256_provenance", {})
    require(isinstance(files, list) and isinstance(hashes, dict) and isinstance(provenance, dict), f"{label} input closure types")
    require(set(files) <= set(hashes) and set(files) <= set(provenance), f"{label} input closure keys")
    for raw in files:
        if any(str(raw).lower().endswith(s) for s in SCIENCE_SUFFIXES):
            require(not str(raw).startswith(str(PKG)), f"{label} science payload copied into package")
            require(isinstance(hashes[raw], str) and len(hashes[raw]) == 64, f"{label} producer science digest")
            require("producer-attested science payload digest" in str(provenance[raw]), f"{label} science provenance")
            continue
        if str(raw).startswith("<root-bind:"):
            require(hashes[raw] is None, f"{label} future hash")
        path = Path(raw)
        if path.is_file() and str(PKG) in str(path):
            require(hashes[raw] == sha_source(path), f"{label} local hash {raw}")


def validate_candidate(tag: str, gate: dict[str, Any]) -> dict[str, Any]:
    bindings = {name: load(PKG / "bindings" / f"{tag}-full801-{suffix}.json") for name, suffix in {"native": "native-binding", "physical": "physical-binding", "xmf": "xmf-binding", "bed": "bed-audit-binding", "render": "render-binding"}.items()}
    snapshot = load(PKG / "metadata" / f"{tag}-root590-typed-producer-snapshot.json")
    producer_h5 = snapshot.get("trajectory_h5")
    producer_h5_sha = snapshot.get("trajectory_h5_sha256")
    require(bindings["native"].get("schema") == "ds02.f5.c082s1.root575-full801-native-binding.fresh116.v1", f"{tag} native schema")
    require(bindings["physical"].get("schema") == "ds02.f5.c082s1.full801-physical-binding.fresh116.v1", f"{tag} physical schema")
    require(bindings["xmf"].get("schema") == "ds02.f5.c082s1.legacy-aware-xmf-binding.fresh116.v1", f"{tag} XMF schema")
    require(bindings["bed"].get("schema") == "ds02.f5.c082s1.full-event-bed-audit-binding.fresh116.v1", f"{tag} bed schema")
    require(bindings["render"].get("schema") == "ds02.f5.c082s1.root023-full801-render-binding.fresh116.v1", f"{tag} render schema")
    require(bindings["native"].get("actual_counts") == COUNTS and bindings["native"].get("native_actual_status") == "completed/0", f"{tag} native status/counts")
    require(bindings["native"].get("root574_gate") == gate and bindings["native"].get("full801_authorized") is True, f"{tag} native gate")
    require(bindings["xmf"].get("expected_frames") == 801 and bindings["xmf"].get("expected_particles") == 194427 and bindings["xmf"].get("native_fields_preserved") is True, f"{tag} XMF axis")
    require(bindings["xmf"].get("source_h5_scope_schema") == "legacy-owner-scope.v0" and bindings["xmf"].get("source_h5_scope_status") == "legacy_incomplete; no cross-resolution physical claim", f"{tag} legacy scope")
    require(bindings["xmf"].get("trajectory_h5") == producer_h5 and bindings["xmf"].get("trajectory_h5_sha256") == producer_h5_sha, f"{tag} XMF producer H5 binding")
    require(bindings["bed"].get("expected_frames") == 801 and bindings["bed"].get("expected_particle_axis") == 194427 and bindings["bed"].get("native_bed_marker_mk") == 50 and bindings["bed"].get("source_bed_marker_mkbound") == 40, f"{tag} bed axis/marker")
    require(bindings["bed"].get("trajectory_h5") == producer_h5 and bindings["bed"].get("trajectory_h5_sha256") == producer_h5_sha, f"{tag} bed producer H5 binding")
    require(bindings["bed"].get("full801_authorized") is False and bindings["bed"].get("repair_success", "").startswith("unknown_until"), f"{tag} bed hold")
    require(bindings["render"].get("expected_frames") == 801 and bindings["render"].get("expected_particles") == 194427 and bindings["render"].get("camera_bounds") is None and bindings["render"].get("domain_bounds") is None, f"{tag} render axis")
    names = {"xmf": f"{tag}-full801-xmf-request.json", "bed": f"{tag}-full801-bed-audit-request.json", "render": f"{tag}-full801-render-root023-request.json"}
    requests = {kind: load(PKG / "requests" / name) for kind, name in names.items()}
    for kind, request in requests.items():
        label = f"{tag}/{kind}"
        require(request.get("schema") == "ds02.runner-request.v2" and request.get("disabled") is True and request.get("execution_allowed") is False and request.get("launch") is False, f"{label} disabled")
        require(request.get("solver_allowed") is False and request.get("conversion_allowed") is False and request.get("arrays_allowed") is False and request.get("array_edit_allowed") is False, f"{label} safety")
        require(request.get("root574_gate") == gate and request.get("full801_authorized") is False and request.get("q_n_granted") is False, f"{label} gate")
        require(request.get("expected_frames") == 801 and request.get("expected_particles") == 194427 and request.get("expected_dimension") == 3 and request.get("expected_fluid_particles") == 31658, f"{label} counts")
        require(request.get("native_bed_marker_mk") == 50 and request.get("source_bed_marker_mkbound") == 40, f"{label} markers")
        require(request.get("resource_window", {}).get("gpu_hours") == 512 and request.get("resource_window", {}).get("cpu_core_hours") == 3840, f"{label} resources")
        require(all(value is None for value in request.get("future_output_hashes", {}).values()), f"{label} future outputs")
        validate_input_closure(request, label)
    require(requests["xmf"].get("trajectory_h5") == producer_h5 and requests["xmf"].get("trajectory_h5_sha256") == producer_h5_sha, f"{tag} XMF request H5 binding")
    require(requests["bed"].get("trajectory_h5") == producer_h5 and requests["bed"].get("trajectory_h5_sha256") == producer_h5_sha, f"{tag} bed request H5 binding")
    require(requests["bed"]["depends_on_attempt"] == requests["xmf"]["attempt_id"] and requests["render"]["depends_on_attempt"] == requests["xmf"]["attempt_id"], f"{tag} downstream dependency")
    require(requests["xmf"]["depends_on_attempt"] == f"root-stage1-f5-c082s1-{tag}-full801-native-typed-575-root590", f"{tag} typed dependency")
    require(requests["xmf"]["attempt_id"].endswith("-xmf-590") and requests["bed"]["attempt_id"].endswith("-bed-audit-590") and requests["render"]["attempt_id"].endswith("-render-590"), f"{tag} attempt suffix")
    require(requests["render"].get("renderer_sha256") == "5e78f7b92ad7c6f1d15902e3ccacc9099affb04b1b992a42f540eb88241bde66", f"{tag} Root023 renderer")
    return {"tag": tag, "status": "disabled", "xmf_attempt": requests["xmf"]["attempt_id"], "bed_attempt": requests["bed"]["attempt_id"], "render_attempt": requests["render"]["attempt_id"]}


def main() -> int:
    validate_manifest()
    validate_sources()
    gate = validate_gate()
    plan = load(PKG / "metadata/fresh116-source-plan.json")
    provenance = load(PKG / "metadata/fresh116-root590-provenance.json")
    require(plan.get("candidates") == list(TAGS) and plan.get("actual_native575_completed0") is True and plan.get("root574_short_window_native_approval") is True, "source plan")
    require(plan.get("full801_xmf_bed_render_authorized") is False and plan.get("new_six_full24s1201_gate") == "WAIT", "plan gate")
    require(provenance.get("counts") == COUNTS and provenance.get("exact_dp_lattice_negative", {}).get("accepted") is False, "provenance")
    snapshots = {tag: validate_snapshot(tag, gate) for tag in TAGS}
    results = [validate_candidate(tag, gate) for tag in TAGS]
    report = {"schema": "ds02.f5.c082s1.fresh116-validator-report.v1", "status": "passed_root588_native_root590_typed_snapshot_downstream_disabled_contract", "candidates": results, "typed_snapshot_statuses": {tag: snapshots[tag].get("status") for tag in TAGS}, "root574_native_approval": True, "full801_xmf_bed_render_authorized": False, "new_six_full24s1201_gate": "WAIT", "exact_dp_lattice_negative_preserved": True, "science_payloads_read_or_hashed_by_validator": False}
    out = PKG / "metadata/fresh116-validator-report.json"
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
