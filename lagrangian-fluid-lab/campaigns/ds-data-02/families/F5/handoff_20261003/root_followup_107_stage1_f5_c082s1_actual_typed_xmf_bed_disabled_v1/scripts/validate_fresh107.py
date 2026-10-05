#!/usr/bin/env python3
"""Source-only validator for the F5 fresh107 disabled downstream handoff.

The validator reads JSON/XML/Python/text metadata and producer-declared H5
SHA fields.  It never opens or hashes H5, BI4, CSV, VTK, or DAT payloads and
never executes an XMF or bed-audit worker.
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any

PKG = Path(__file__).resolve().parents[1]
CASE = "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1"
DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5")
COUNTS = {"total": 194427, "fixed": 158559, "moving": 4210, "floating": 0, "fluid": 31658}
ROOT142_POLICY_SHA = "2649eedbcf4816f8d2fa7b2182828ea8b3ce107ef47f25c56780d29c5138def5"
SCIENCE_SUFFIXES = {".bi4", ".csv", ".h5", ".hdf5", ".vtk", ".vtu", ".npy", ".npz", ".dat"}
SOURCE_SUFFIXES = {".json", ".py", ".xml", ".md", ".txt", ".log"}
HEX = set("0123456789abcdefABCDEF")


def require(value: bool, message: str) -> None:
    if not value:
        raise ValueError(message)


def load_json(path: Path) -> tuple[dict[str, Any], str]:
    require(path.suffix.lower() == ".json" and path.is_file(), f"JSON metadata missing: {path}")
    raw = path.read_bytes()
    value = json.loads(raw.decode("utf-8"))
    require(isinstance(value, dict), f"JSON object required: {path}")
    return value, hashlib.sha256(raw).hexdigest()


def sha_source(path: Path) -> str:
    require(path.suffix.lower() in SOURCE_SUFFIXES, f"source hash forbidden for payload: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha_json(path: Path) -> str:
    require(path.suffix.lower() == ".json", f"JSON hash required: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_counts(value: dict[str, Any], label: str, placement: bool = False) -> None:
    if placement:
        result = {
            "total": int(value.get("total_particles", -1)),
            "fixed": int(value.get("fixed_particles", -1)),
            "moving": int(value.get("moving_particles", -1)),
            "floating": int(value.get("floating_particles", -1)),
            "fluid": int(value.get("fluid_particles", -1)),
            "dimension": int(value.get("solver_dimension", -1)),
        }
    else:
        result = {
            "total": int(value.get("total", value.get("total_particles", -1))),
            "fixed": int(value.get("fixed", value.get("fixed_particles", -1))),
            "moving": int(value.get("moving", value.get("moving_particles", -1))),
            "floating": int(value.get("floating", value.get("floating_particles", -1))),
            "fluid": int(value.get("fluid", value.get("fluid_particles", -1))),
            "dimension": int(value.get("dimension", value.get("solver_dimension", -1))),
        }
    require(result == {**COUNTS, "dimension": 3}, f"{label}: counts {result}")


def check_manifest() -> dict[str, str]:
    manifest, _ = load_json(PKG / "manifest.json")
    require(manifest.get("schema") == "ds02.f5.c082s1.fresh107-source-manifest.v1", "manifest schema")
    require(manifest.get("status") == "actual_root486_typed_bound_xmf_bed_disabled", "manifest status")
    require(manifest.get("full801_authorized") is False and manifest.get("q_n_granted") is False, "manifest acceptance")
    require(manifest.get("science_payloads_read_or_hashed_by_source_builder") is False, "manifest source boundary")
    result: dict[str, str] = {}
    files = manifest.get("files")
    require(isinstance(files, dict), "manifest files")
    for relative, declared in files.items():
        path = PKG / relative
        require(path.is_file(), f"manifest file missing: {path}")
        require(path.suffix.lower() in SOURCE_SUFFIXES, f"science/unsupported package file: {path}")
        require(isinstance(declared, str) and len(declared) == 64, f"manifest hash shape: {relative}")
        require(sha_source(path) == declared, f"manifest hash mismatch: {relative}")
        result[relative] = declared
    return result


def check_input_closure(request: dict[str, Any], candidate: str, label: str, producer_h5_sha: str) -> dict[str, int]:
    files = request.get("input_files")
    hashes = request.get("input_sha256")
    provenance = request.get("input_sha256_provenance")
    require(isinstance(files, list) and isinstance(hashes, dict) and isinstance(provenance, dict), f"{label}: input closure shape")
    static = 0
    producer_payload = 0
    placeholders = 0
    for raw in files:
        text = str(raw)
        require(text in hashes and text in provenance, f"{label}: closure metadata missing {text}")
        suffix = Path(text).suffix.lower()
        if text.startswith("<root-bind:"):
            require(hashes[text] is None, f"{label}: future placeholder hash must be null: {text}")
            placeholders += 1
            continue
        require(Path(text).exists(), f"{label}: input path missing: {text}")
        if suffix in SCIENCE_SUFFIXES:
            require(suffix == ".h5", f"{label}: unexpected science payload path: {text}")
            require(hashes[text] == producer_h5_sha, f"{label}: H5 is not bound to producer output SHA")
            require("producer-declared" in str(provenance[text]), f"{label}: H5 provenance is not producer-declared")
            producer_payload += 1
            continue
        if suffix not in SOURCE_SUFFIXES:
            require(hashes[text] is None, f"{label}: executable/tool hash must be null unless source text")
            require("producer/tool" in str(provenance[text]) or "executable" in str(provenance[text]), f"{label}: unsupported tool provenance")
            continue
        declared = hashes[text]
        require(isinstance(declared, str) and len(declared) == 64 and set(declared) <= HEX, f"{label}: invalid static SHA {text}")
        require(sha_source(Path(text)) == declared, f"{label}: static SHA mismatch {text}")
        static += 1
    require(producer_payload == 1, f"{label}: expected one producer-declared H5 input")
    return {"static_inputs_hashed": static, "producer_h5_inputs": producer_payload, "root_placeholders": placeholders}


def check_typed_actual(candidate: str, xmf_binding: dict[str, Any], bed_binding: dict[str, Any]) -> dict[str, Any]:
    report_path = Path(str(xmf_binding["conversion_report"]))
    receipt_path = Path(str(xmf_binding["typed_receipt"]))
    report, report_sha = load_json(report_path)
    receipt, receipt_sha = load_json(receipt_path)
    require(report.get("schema") == "ds-data-02.bi4-direct-conversion.v1" and report.get("conversion_status") == "completed", f"{candidate}: report status")
    require(report.get("frames") == 51 and report.get("particles") == COUNTS["total"], f"{candidate}: report shape")
    dimension = report.get("solver_dimension")
    require(isinstance(dimension, dict) and dimension.get("solver_dimension") == 3 and dimension.get("xml_data2d") == "false", f"{candidate}: report dimension")
    producer_h5_sha = report.get("output_sha256")
    require(isinstance(producer_h5_sha, str) and len(producer_h5_sha) == 64, f"{candidate}: producer H5 SHA")
    identity = report.get("typed_identity", {})
    blocks = identity.get("blocks", [])
    totals: dict[str, int] = {}
    for block in blocks:
        if isinstance(block, dict):
            tag = str(block.get("tag"))
            totals[tag] = totals.get(tag, 0) + int(block.get("count", 0))
    require(totals.get("fixed") == COUNTS["fixed"] and totals.get("moving") == COUNTS["moving"] and totals.get("fluid") == COUNTS["fluid"], f"{candidate}: typed blocks")
    require(50 in identity.get("observed_mks", []) and {0, 1, 3}.issubset(set(identity.get("observed_types", []))), f"{candidate}: typed MK/type identity")
    scope = report.get("hash_scopes", {}).get("physical_condition", {})
    require(scope.get("schema") == "legacy-owner-scope.v0" and scope.get("semantic_binding_status") == "legacy_incomplete; no cross-resolution physical claim", f"{candidate}: legacy scope semantics")
    legacy_sha = report.get("hash_scopes", {}).get("physical_condition_sha256")
    require(legacy_sha == xmf_binding.get("source_h5_physical_condition_sha256"), f"{candidate}: legacy H5 SHA binding")
    require(xmf_binding.get("trajectory_h5_sha256") == producer_h5_sha and bed_binding.get("trajectory_h5_sha256") == producer_h5_sha, f"{candidate}: producer H5 SHA propagation")
    require(receipt.get("status") == "completed" and int(receipt.get("returncode", -1)) == 0, f"{candidate}: typed receipt status")
    nested = receipt.get("request", {})
    require(nested.get("attempt_id") == xmf_binding.get("typed_attempt_id", nested.get("attempt_id")) or nested.get("attempt_id") == Path(str(receipt.get("output_root"))).name, f"{candidate}: typed receipt identity")
    require(report_sha == xmf_binding.get("conversion_report_sha256") and report_sha == bed_binding.get("native_conversion_report_sha256"), f"{candidate}: report SHA binding")
    require(receipt_sha == xmf_binding.get("typed_receipt_sha256") and receipt_sha == bed_binding.get("typed_receipt_sha256"), f"{candidate}: receipt SHA binding")
    return {"report_sha256": report_sha, "receipt_sha256": receipt_sha, "producer_h5_sha256": producer_h5_sha, "legacy_h5_sha256": legacy_sha}


def check_binding(candidate: str, kind: str) -> dict[str, Any]:
    path = PKG / "bindings" / (f"{candidate}-short-xmf-binding.json" if kind == "xmf" else f"{candidate}-short-bed-audit-binding.json")
    binding, binding_sha = load_json(path)
    expected_schema = "ds02.f5.c082s1.legacy-aware-xmf-binding.fresh107.v1" if kind == "xmf" else "ds02.f5.c082s1.short-dynamic-bed-audit-binding.fresh107.v1"
    require(binding.get("schema") == expected_schema, f"{candidate} {kind}: schema")
    require(binding.get("case_id") == CASE and binding.get("physical_case_id") == f"F5_COMPACT_RUNUP_RECOVERY_C082S1_{candidate}", f"{candidate} {kind}: case identity")
    require(binding.get("expected_frames") == 51 and binding.get("expected_dimension") == 3 and binding.get("expected_particles") == COUNTS["total"], f"{candidate} {kind}: dimensions")
    require(binding.get("physical_condition_sha256") != binding.get("source_plan_physical_condition_sha256"), f"{candidate} {kind}: canonical/source plan collapsed")
    require(binding.get("physical_condition_sha256") != binding.get("source_h5_physical_condition_sha256"), f"{candidate} {kind}: canonical/H5 scope collapsed")
    semantics = binding.get("physical_condition_hash_semantics", {})
    require(semantics.get("canonical_owner_sha256") == binding.get("physical_condition_sha256"), f"{candidate} {kind}: canonical semantics")
    require(semantics.get("source_h5_sha256") == binding.get("source_h5_physical_condition_sha256"), f"{candidate} {kind}: legacy semantics")
    require(semantics.get("source_h5_scope_schema") == "legacy-owner-scope.v0", f"{candidate} {kind}: legacy schema")
    require(binding.get("full801_authorized") is False and binding.get("q_n_granted") is False, f"{candidate} {kind}: acceptance boundary")
    report, _ = load_json(Path(str(binding["conversion_report"] if kind == "xmf" else binding["native_conversion_report"])))
    receipt, _ = load_json(Path(str(binding["typed_receipt"])))
    require(report.get("frames") == 51 and report.get("particles") == COUNTS["total"], f"{candidate} {kind}: actual report dimensions")
    require(receipt.get("status") == "completed" and int(receipt.get("returncode", -1)) == 0, f"{candidate} {kind}: actual typed receipt")
    if kind == "xmf":
        require(binding.get("trajectory_h5") and binding.get("trajectory_h5_sha256"), f"{candidate} xmf: H5 producer binding")
        require(binding.get("future_output_hashes") and all(value is None for value in binding["future_output_hashes"].values()), f"{candidate} xmf: future hashes")
    else:
        check_counts(binding.get("actual_counts", {}), f"{candidate} bed actual counts", placement=True)
        require(binding.get("native_bed_marker_mk") == 50 and binding.get("source_bed_marker_mkbound") == 40, f"{candidate} bed: marker mapping")
        saved = binding.get("short_saved_state_metadata", {})
        require(saved.get("all_51_saved_states") is True and saved.get("saved_state_count") == 51 and saved.get("path") is None and saved.get("sha256") is None, f"{candidate} bed: saved-state fallback")
        require(saved.get("provenance") == "actual typed conversion-report frames=51; raw saved-state filename metadata remains Root runtime check", f"{candidate} bed: saved-state provenance")
        require(binding.get("xmf_manifest") is None and binding.get("xmf_manifest_sha256") is None and binding.get("xdmf") is None and binding.get("xdmf_sha256") is None, f"{candidate} bed: future XMF not falsely bound")
        require(all(value is None for key, value in binding.get("future_output_hashes", {}).items() if key in {"xmf_manifest_sha256", "bed_audit_report_sha256"}), f"{candidate} bed: future XMF/bed hash")
    return {"binding_sha256": binding_sha, "kind": kind}


def check_request(candidate: str, kind: str, actual: dict[str, Any]) -> dict[str, Any]:
    path = PKG / "requests" / (f"{candidate}-xmf-request.json" if kind == "xmf" else f"{candidate}-bed-audit-request.json")
    request, request_sha = load_json(path)
    task = "xmf_export" if kind == "xmf" else "audit"
    require(request.get("schema") == "ds02.runner-request.v2" and request.get("kind") == "cpu" and request.get("cpu_task_kind") == task, f"{candidate} {kind}: runner shape")
    require(request.get("disabled") is True and request.get("launch") is False and request.get("launch_allowed") is False and request.get("execution_allowed") is False and request.get("solver_allowed") is False, f"{candidate} {kind}: request is enabled")
    require(request.get("source_only") is True and request.get("shared_registry_write_allowed") is False and request.get("arrays_allowed") is False, f"{candidate} {kind}: source boundary")
    require(request.get("case_id") == CASE and request.get("physical_case_id") == actual["physical_case_id"], f"{candidate} {kind}: request identity")
    require(request.get("root_inventory_policy_source_sha256") == ROOT142_POLICY_SHA and request.get("cpu_threads") == 2, f"{candidate} {kind}: CPU policy")
    require(request.get("expected_frames") == 51 and request.get("expected_dimension") == 3 and request.get("expected_particles") == COUNTS["total"], f"{candidate} {kind}: request counts")
    require(request.get("full801_authorized") is False and request.get("q_n_granted") is False and request.get("independent_case_count_increment") == 0, f"{candidate} {kind}: acceptance boundary")
    future = request.get("future_output_hashes")
    require(isinstance(future, dict) and all(value is None for value in future.values()), f"{candidate} {kind}: future output hash not null")
    closure = check_input_closure(request, candidate, path.name, actual["trajectory_h5_sha256"])
    return {"request_sha256": request_sha, **closure}


def check_workers() -> dict[str, str]:
    result: dict[str, str] = {}
    paths = [PKG / "workers/export_xmf_legacy_aware.py", PKG / "workers/bed_audit_A080.py", PKG / "workers/bed_audit_A120.py", PKG / "scripts/bind_bed_after_xmf.py", PKG / "scripts/build_fresh107.py"]
    for path in paths:
        text = path.read_text(encoding="utf-8")
        ast.parse(text, filename=str(path))
        result[str(path.relative_to(PKG))] = sha_source(path)
    xmf = (PKG / "workers/export_xmf_legacy_aware.py").read_text(encoding="utf-8")
    require("--binding" in xmf and "--output-dir" in xmf and "source_h5_physical_condition_sha256" in xmf, "XMF CLI/legacy scope contract")
    for candidate in ("A080", "A120"):
        bed = (PKG / "workers" / f"bed_audit_{candidate}.py").read_text(encoding="utf-8")
        require("fresh107" in bed and "native_bed_mk" in bed and "thresholds_are_diagnostic_only" in bed and "--trajectory-h5" in bed and "--xdmf" in bed, f"{candidate}: bed worker contract")
        require("actual typed conversion-report frames=51; raw saved-state filename metadata remains Root runtime check" in bed, f"{candidate}: saved fallback contract")
    return result


def main() -> int:
    manifest = check_manifest()
    workers = check_workers()
    results: dict[str, Any] = {"candidates": {}, "manifest_files": len(manifest), "workers": workers}
    for candidate in ("A080", "A120"):
        xmf_binding, _ = load_json(PKG / "bindings" / f"{candidate}-short-xmf-binding.json")
        actual = {
            "physical_case_id": xmf_binding["physical_case_id"],
            "trajectory_h5_sha256": xmf_binding["trajectory_h5_sha256"],
        }
        bed_binding, _ = load_json(PKG / "bindings" / f"{candidate}-short-bed-audit-binding.json")
        typed = check_typed_actual(candidate, xmf_binding, bed_binding)
        results["candidates"][candidate] = {
            "typed_actual": typed,
            "xmf_binding": check_binding(candidate, "xmf"),
            "bed_binding": check_binding(candidate, "bed"),
            "xmf_request": check_request(candidate, "xmf", actual),
            "bed_request": check_request(candidate, "bed", actual),
        }
    report = {
        "schema": "ds02.f5.c082s1.fresh107-source-validator-report.v1",
        "status": "passed_actual_typed_bound_downstream_disabled_contract",
        "candidates": results["candidates"],
        "worker_sources": workers,
        "actual_typed_completed0": True,
        "actual_counts": {**COUNTS, "dimension": 3},
        "canonical_vs_legacy_scope_separate": True,
        "future_xmf_and_bed_hashes_null": True,
        "exact_dp_lattice_negative_retained": True,
        "full801_authorized": False,
        "q_n_granted": False,
        "independent_case_count_increment": 0,
        "science_payloads_read_or_hashed_by_validator": False,
        "jobs_started": False,
        "shared_state_modified": False,
        "source_only": True,
    }
    out = PKG / "metadata" / "fresh107-validator-report.json"
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "candidates": ["A080", "A120"], "science_payloads_read_or_hashed_by_validator": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
