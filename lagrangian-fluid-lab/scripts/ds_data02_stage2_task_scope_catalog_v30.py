#!/usr/bin/env python3
"""Expose the bounded task-scope subset of the actual v29 catalog.

v29 is the immutable 336-case scientific-audit/native-impact catalog.  This
forward-only reader adds a small, reviewable qualification index for tasks
that are actually supported by the recorded fields: CURRENT inventory,
field-failure/finite-lifecycle diagnostics, native motive and source-visible
mass bookkeeping, and saved-record censor brackets.  It also records the
complete v28 dependency and reproduction chain.  None of these scopes grants
QN, QE, QI, physical fate, legal flux, continuous event truth, recovery
transfer, effective split safety, or a dynamics/error bound.

Only JSON, receipts, proofs, and source files named by the request are read.
The worker never opens trajectory H5, materialized-label H5, BI4, raw solver
output, or a solver/model.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
FAMILIES = [f"F{i}" for i in range(1, 8)]
FORBIDDEN_SUFFIXES = {".h5", ".hdf5", ".bi4", ".bi2", ".bi1"}
V29_SCHEMA = "ds02.stage2.final-qualification-catalog.v29"
V29_MANIFEST_SCHEMA = "ds02.stage2.final-qualification-catalog-manifest.v29"
V29_REQUEST_SCHEMA = "ds02.stage2.final-qualification-catalog-v29-request.v1"
V30_SCHEMA = "ds02.stage2.task-scope-catalog.v30"
V30_MANIFEST_SCHEMA = "ds02.stage2.task-scope-catalog-manifest.v30"
V30_REQUEST_SCHEMA = "ds02.stage2.task-scope-catalog-v30-request.v1"
V28_REQUEST_SCHEMA = "ds02.stage2.product-delivery-metadata-v28-request.v1"
V28_HANDOFF_SCHEMA = "ds02.stage2.product-delivery-metadata-v28-handoff.v1"
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class ScopeError(RuntimeError):
    """Raised when a v29/v28 identity or scope boundary is open."""


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _path(value: Path | str, label: str, *, output: bool = False) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ScopeError(f"{label} must be absolute: {path}")
    if not output and path.suffix.lower() in FORBIDDEN_SUFFIXES:
        raise ScopeError(f"{label} is forbidden scientific payload: {path}")
    if not output and not path.is_file():
        raise ScopeError(f"{label} is missing: {path}")
    return path


def _json(value: Path | str, label: str) -> tuple[Path, dict[str, Any]]:
    path = _path(value, label)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ScopeError(f"{label} is invalid JSON: {path}") from error
    if not isinstance(data, dict):
        raise ScopeError(f"{label} must be an object: {path}")
    return path, data


def _ref(path: Path, role: str) -> dict[str, Any]:
    return {"role": role, "path": str(path), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def _require_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA_RE.fullmatch(value):
        raise ScopeError(f"{label} is not a lowercase SHA-256 digest")
    return value


def _require_file_sha(path: Path, declared: Any, label: str) -> str:
    expected = _require_sha(declared, label)
    actual = sha256_file(path)
    if expected != actual:
        raise ScopeError(f"{label} mismatch: declared {expected}, actual {actual}")
    return actual


def _git_commit() -> str | None:
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=SCRIPT.parents[2], check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


def _validate_v28_request(path: Path, request: dict[str, Any]) -> dict[str, Any]:
    if request.get("schema") != "ds02.runner-request.v1" or request.get("request_schema") != V28_REQUEST_SCHEMA:
        raise ScopeError("v28 request schema is not product-delivery-metadata.v28")
    if request.get("status") != "prepared_guard_pending_actual_CPU" or request.get("launch_allowed") is not True:
        raise ScopeError("v28 request is not the prepared root-owned CPU request")
    if request.get("cpu_threads") != 1 or request.get("max_wall_seconds") != 900:
        raise ScopeError("v28 request resource contract changed")
    cost = request.get("source_cost") or {}
    if any(cost.get(name, 0) != 0 for name in ("original_trajectory_h5_bytes_read", "materialized_label_h5_bytes_read", "part_bi4_bytes_read", "raw_solver_output_bytes_read")):
        raise ScopeError("v28 request declares scientific payload reads")
    policy = request.get("read_policy") or {}
    if any(policy.get(name) is not False for name in ("trajectory_h5_opened", "materialized_label_h5_opened", "part_bi4_opened", "solver_started", "model_invoked")):
        raise ScopeError("v28 request read policy is open")
    inputs = request.get("input_files")
    hashes = request.get("input_sha256")
    if not isinstance(inputs, list) or not isinstance(hashes, dict) or len(inputs) != 10:
        raise ScopeError("v28 request input closure is incomplete")
    refs = []
    for item in inputs:
        p = _path(item, "v28 request input")
        if item not in hashes:
            raise ScopeError(f"v28 request lacks input hash: {item}")
        _require_file_sha(p, hashes[item], f"v28 request input {item}")
        refs.append(_ref(p, "v28 request input"))
    return {"request": _ref(path, "v28 guarded request"), "inputs": refs, "resource": {"cpu_threads": request["cpu_threads"], "max_wall_seconds": request["max_wall_seconds"], "estimated_storage_bytes": request.get("estimated_storage_bytes")}, "status": request["status"], "claim_boundary": request.get("claim_boundary")}


def _validate_v28_handoff(path: Path, handoff: dict[str, Any], request_path: Path, request: dict[str, Any]) -> dict[str, Any]:
    if handoff.get("schema") != V28_HANDOFF_SCHEMA or handoff.get("status") != "PREPARED_REQUEST_PENDING_CONSUMER_GUARD":
        raise ScopeError("v28 handoff is not the immutable pending-guard handoff")
    request_ref = handoff.get("request") or {}
    if request_ref.get("path") != str(request_path) or request_ref.get("sha256") != sha256_file(request_path):
        raise ScopeError("v28 handoff does not bind the exact request")
    if request_ref.get("request_schema") != V28_REQUEST_SCHEMA:
        raise ScopeError("v28 handoff request schema differs")
    expected = ["e30fea6ee", "87741b84c", "455d6b730", "86db22652"]
    dependencies = handoff.get("dependencies")
    if not isinstance(dependencies, list) or [item.get("commit") for item in dependencies] != expected:
        raise ScopeError("v28 handoff dependency chain is incomplete or reordered")
    worker = next((item for item in request.get("input_files", []) if item.endswith("ds_data02_stage2_product_delivery_metadata_v28.py")), None)
    worker_ref = (handoff.get("source_bindings") or {}).get("v28_worker") or {}
    if worker is None or worker_ref.get("path") != worker or worker_ref.get("sha256") != request.get("input_sha256", {}).get(worker):
        raise ScopeError("v28 handoff worker source does not bind the request")
    stages = handoff.get("reproduction_chain") or {}
    if stages.get("portable_raw_to_typed_to_label_replay") != "PENDING_CONSUMER_GUARD" or stages.get("physical_fate") != "UNKNOWN" or stages.get("dynamical_impact") != "UNKNOWN":
        raise ScopeError("v28 handoff weakens pending/UNKNOWN reproduction boundaries")
    return {"handoff": _ref(path, "v28 exact dependency/access handoff"), "dependencies": dependencies, "request": request_ref, "reproduction_chain": stages, "access_policy": handoff.get("access_policy"), "verification": handoff.get("verification")}


def _validate_v29(
    product_path: Path,
    product: dict[str, Any],
    manifest_path: Path,
    manifest: dict[str, Any],
    request_path: Path,
    request: dict[str, Any],
    proof_path: Path,
    proof: dict[str, Any],
    receipt_path: Path,
    receipt: dict[str, Any],
) -> list[dict[str, Any]]:
    if product.get("schema") != V29_SCHEMA or not str(product.get("status", "")).startswith("ACTUAL_336_CASE_AUDIT"):
        raise ScopeError("v29 product is not the actual per-case audit catalog")
    coverage = product.get("coverage") or {}
    if coverage.get("current_cases") != 336 or coverage.get("scientific_audit_cases") != 336 or coverage.get("native_impact_cases") != 118 or coverage.get("quality_anchor_cases") != 7:
        raise ScopeError("v29 coverage is incomplete")
    q = product.get("scientific_qualification") or {}
    if any(q.get(name) != "UNKNOWN" for name in ("QN", "QE", "QI", "physical_fate", "dynamical_impact")):
        raise ScopeError("v29 grants scientific qualification")
    cases = product.get("cases")
    if not isinstance(cases, list) or len(cases) != 336:
        raise ScopeError("v29 case catalog is not 336 cases")
    keys = set()
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("case_key"), str) or case["case_key"] in keys:
            raise ScopeError("v29 case identity is duplicate or malformed")
        keys.add(case["case_key"])
        eq = (case.get("qualification_dimensions") or {}).get("error_qualification") or {}
        if any(eq.get(name) != "UNKNOWN" for name in ("QN", "QE", "QI", "physical_fate", "dynamical_impact")):
            raise ScopeError(f"v29 case grants qualification: {case['case_key']}")
    if manifest.get("schema") != V29_MANIFEST_SCHEMA:
        raise ScopeError("v29 manifest schema is unexpected")
    manifest_product = manifest.get("product") or {}
    if manifest_product.get("path") != str(product_path) or manifest_product.get("sha256") != sha256_file(product_path):
        raise ScopeError("v29 manifest does not bind the supplied product")
    if proof.get("schema") != "ds02.stage2.root-actual-verification.v1" or not str(proof.get("status", "")).startswith("PASS_ACTUAL"):
        raise ScopeError("v29 proof is not actual")
    if proof.get("H5_BI4_read_by_root") is not False:
        raise ScopeError("v29 proof opens H5/BI4 scope")
    proof_product = proof.get("report") or proof.get("product") or proof.get("output")
    proof_product_path = proof_product.get("path") if isinstance(proof_product, dict) else proof_product
    if proof_product_path != str(product_path):
        raise ScopeError("v29 proof does not bind product path")
    proof_product_sha = proof.get("report_sha256") or proof.get("product_sha256")
    if isinstance(proof_product, dict):
        proof_product_sha = proof_product.get("sha256") or proof_product_sha
    if proof_product_sha is not None:
        _require_file_sha(product_path, proof_product_sha, "v29 proof product")
    if proof.get("receipt") != str(receipt_path) or proof.get("receipt_sha256") != sha256_file(receipt_path):
        raise ScopeError("v29 proof does not bind receipt")
    if proof.get("request") not in (None, str(request_path)):
        raise ScopeError("v29 proof does not bind request")
    if proof.get("request_sha256") is not None:
        _require_file_sha(request_path, proof.get("request_sha256"), "v29 proof request")
    if request.get("request_schema") != V29_REQUEST_SCHEMA:
        raise ScopeError("v29 request schema is unexpected")
    if receipt.get("schema") != "ds02.execution-receipt.v1" or receipt.get("status") != "completed" or receipt.get("returncode") not in (None, 0):
        raise ScopeError("v29 receipt is not completed")
    if receipt.get("output_root") and Path(receipt["output_root"]) != product_path.parent:
        raise ScopeError("v29 receipt output_root differs")
    return cases


def _finite_scope(case: dict[str, Any]) -> dict[str, Any]:
    finite = ((case.get("qualification_dimensions") or {}).get("finite_fields") or {})
    failures = finite.get("field_failures") if isinstance(finite.get("field_failures"), list) else []
    ledger = case.get("scientific_audit", {}).get("fluid_ledger")
    lifecycle = "NOT_EXPOSED_IN_AUDIT_ROW"
    metrics: dict[str, Any] = {}
    if isinstance(ledger, dict):
        names = ("active_nonfinite", "active_nonpositive_mass", "active_nonpositive_density")
        metrics = {name: ledger.get(name) for name in names}
        def all_zero(value: Any) -> bool:
            if isinstance(value, dict):
                return bool(value) and all(all_zero(item) for item in value.values())
            return isinstance(value, (int, float)) and value == 0

        zero = all(all_zero(ledger.get(name)) for name in names)
        lifecycle = "CLOSED_ZERO_NONFINITE_AND_NONPOSITIVE_MASS_DENSITY" if zero else "LIFECYCLE_FAILURE_OR_NONZERO_REPORTED"
    return {"field_failure_count": len(failures), "field_failures": failures, "field_audit": "ELIGIBLE_FIELD_FAILURE_LIST_EMPTY" if not failures else "FAILED_FIELD_AUDIT_SCOPE", "lifecycle": lifecycle, "lifecycle_metrics": metrics, "qualification_credit": "finite field/lifecycle diagnostic only"}


def _task_case(case: dict[str, Any]) -> dict[str, Any]:
    native = case.get("native_omission")
    dims = case.get("qualification_dimensions") or {}
    current = case.get("current") or {}
    audit = case.get("scientific_audit") or {}
    quality = case.get("quality_scope") or {}
    finite = _finite_scope(case)
    mass = dims.get("mass") or {}
    identity = dims.get("identity") or {}
    time = dims.get("time") or {}
    censor = dims.get("censoring") or {}
    return {
        "case_key": case["case_key"],
        "current_inventory": {
            "status": "ELIGIBLE_EXACT_CURRENT_INVENTORY",
            "current_index": current.get("current_index"),
            "family_id": current.get("family_id"),
            "physical_case_id": current.get("physical_case_id"),
            "runtime_case_alias": current.get("runtime_case_alias"),
            "frames": current.get("frames"),
            "particles": current.get("particles"),
            "actual_time_window_s": current.get("actual_time_window_s"),
            "source_role": current.get("source_role"),
        },
        "finite_field_scope": finite,
        "native_mk_scope": {
            "status": "ELIGIBLE_NATIVE_MOTIVE_ID_AND_COUNT" if native else "NOT_IN_118_NATIVE_LEDGER",
            "motive": native.get("native_motive") if native else None,
            "native_count": native.get("native_count") if native else None,
            "source_mk_mass_partition": (mass.get("source_mk_partition") if native else None),
            "per_mk_mass_status": "UNKNOWN" if native else "NOT_APPLICABLE",
            "native_cause_scope": "native motive/ID/RunPARTs only; physical destination UNKNOWN" if native else "UNKNOWN",
        },
        "mass_scope": {
            "status": "ELIGIBLE_SOURCE_VISIBLE_LOWER_BOUND_ONLY" if native else "SCIENTIFIC_SCAN_INITIAL_MASS_AND_MISSING_COUNT_ONLY",
            "initial_mass_kg": mass.get("initial_fluid_mass_denominator_kg", mass.get("initial_fluid_mass_kg")),
            "missing_mass_lower_bound_kg": mass.get("missing_source_visible_mass_lower_bound_kg"),
            "missing_fraction_lower_bound": mass.get("missing_source_visible_fraction_lower_bound"),
            "gate": mass.get("screen_gate_fraction"),
            "error_bound": "UNKNOWN",
        },
        "id_scope": {
            "status": identity.get("native_identity") if native else identity.get("current_identity"),
            "identity_key": identity.get("identity_key"),
            "native_count": identity.get("native_count"),
        },
        "time_scope": {
            "status": "ELIGIBLE_SAVED_RECORD_BRACKET_DIAGNOSTIC" if native else "ELIGIBLE_CURRENT_SAVED_WINDOW_AND_FRAME_COUNT",
            "current_saved_window_s": time.get("current_saved_window_s"),
            "frames": time.get("frames"),
            "first_missing_window_s": time.get("first_missing_window_s"),
            "event_time": "UNKNOWN; saved-record bracket only" if native else "UNKNOWN",
        },
        "censor_scope": {
            "status": censor.get("status"),
            "particle_observation_count": (native.get("saved_censoring") or {}).get("particle_observation_count") if native else None,
            "saved_record_impact_count": (native.get("saved_censoring") or {}).get("saved_record_impact_count") if native else None,
            "hidden_continuous_crossings": "UNKNOWN",
            "hidden_recrossings": "UNKNOWN",
        },
        "failed_scope": {
            "scientific_audit_field_failures": audit.get("field_failures", []),
            "producer_parent_failure_or_recovery": ((dims.get("failed_scope") or {}).get("producer_parent_failure_or_recovery")),
            "error_scope": "field/producer failure scope only; no numerical solution error bound",
        },
        "quality_scope": {
            "status": "ELIGIBLE_STRICT_ANCHOR_TASK_SCOPE" if quality.get("quality_checks_closed") is True else "NOT_EVALUATED_NON_ANCHOR",
            "source_role": quality.get("source_role"),
            "task_eligibility": quality.get("task_eligibility") if quality.get("quality_checks_closed") is True else None,
            "qualification_credit": "NONE",
        },
        "error_qualification": {
            "QN": "UNKNOWN", "QE": "UNKNOWN", "QI": "UNKNOWN", "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN", "effective_split_safe": "UNKNOWN", "qualification_credit": "NONE",
        },
    }


def _assemble(
    v29_product_path: Path,
    v29_product: dict[str, Any],
    v29_manifest_path: Path,
    v29_manifest: dict[str, Any],
    v29_request_path: Path,
    v29_request: dict[str, Any],
    v29_proof_path: Path,
    v29_proof: dict[str, Any],
    v29_receipt_path: Path,
    v29_receipt: dict[str, Any],
    v28_request_path: Path,
    v28_request: dict[str, Any],
    v28_handoff_path: Path,
    v28_handoff: dict[str, Any],
) -> dict[str, Any]:
    cases = _validate_v29(v29_product_path, v29_product, v29_manifest_path, v29_manifest, v29_request_path, v29_request, v29_proof_path, v29_proof, v29_receipt_path, v29_receipt)
    v28 = _validate_v28_request(v28_request_path, v28_request)
    v28_handoff_summary = _validate_v28_handoff(v28_handoff_path, v28_handoff, v28_request_path, v28_request)
    task_cases = [_task_case(case) for case in cases]
    finite_failure_free = sum(x["finite_field_scope"]["field_failure_count"] == 0 for x in task_cases)
    lifecycle_closed = sum(x["finite_field_scope"]["lifecycle"] == "CLOSED_ZERO_NONFINITE_AND_NONPOSITIVE_MASS_DENSITY" for x in task_cases)
    native = sum(x["native_mk_scope"]["status"] == "ELIGIBLE_NATIVE_MOTIVE_ID_AND_COUNT" for x in task_cases)
    censor = sum(x["time_scope"]["status"] == "ELIGIBLE_SAVED_RECORD_BRACKET_DIAGNOSTIC" for x in task_cases)
    quality = sum(x["quality_scope"]["status"] == "ELIGIBLE_STRICT_ANCHOR_TASK_SCOPE" for x in task_cases)
    result = {
        "schema": V30_SCHEMA,
        "status": "ACTUAL_V29_TASK_SCOPE_INDEX_WITH_QN_QE_QI_UNKNOWN",
        "producer": {"script_path": str(SCRIPT), "script_sha256": sha256_file(SCRIPT), "git_commit": _git_commit()},
        "source": {"v29_product": _ref(v29_product_path, "actual v29 catalog"), "v29_manifest": _ref(v29_manifest_path, "actual v29 manifest"), "v29_request": _ref(v29_request_path, "actual v29 request"), "v29_proof": _ref(v29_proof_path, "actual v29 proof"), "v29_receipt": _ref(v29_receipt_path, "actual v29 receipt"), "v28": v28, "v28_handoff": v28_handoff_summary},
        "coverage": {"current_cases": 336, "finite_field_failure_free_cases": finite_failure_free, "finite_lifecycle_zero_metric_cases": lifecycle_closed, "native_motive_id_cases": native, "saved_record_bracket_cases": censor, "strict_quality_anchor_cases": quality, "all_qn_qe_qi_unknown": True},
        "cases": task_cases,
        "task_qualification": {
            "current_inventory": "ELIGIBLE_EXACT_CURRENT_INVENTORY",
            "finite_field_failure_list": "ELIGIBLE_FIELD_FAILURE_LIST_SCOPE_ONLY",
            "finite_lifecycle_metrics": "ELIGIBLE_ONLY_WHERE_AUDIT_EXPOSES_ZERO_METRICS",
            "native_mk_motive_and_id": "ELIGIBLE_118_SOURCE_CLOSED_CASES",
            "source_visible_mass": "ELIGIBLE_LOWER_BOUND_ONLY",
            "saved_record_censor": "ELIGIBLE_118_SAVED_BRACKET_CASES",
            "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "continuous_events": "UNKNOWN", "dynamical_impact": "UNKNOWN", "effective_split_safe": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "QI": "UNKNOWN", "qualification_credit": "NONE",
        },
        "v28_reproduction_chain": {
            "status": "PREPARED_REQUEST_PENDING_CONSUMER_GUARD",
            "dependencies": [
                {"commit": "e30fea6ee", "scope": "JSON-only v28 delivery loader, F2 reproduction contract, access boundary"},
                {"commit": "87741b84c", "scope": "require terminal F2 native-v4 status"},
                {"commit": "455d6b730", "scope": "guarded v28 CPU request builder"},
                {"commit": "86db22652", "scope": "request bound to actual v27 product/proof/receipt"},
            ],
            "request": v28["request"],
            "stages": [
                {"stage": "v27_product_and_current", "status": "ACTUAL_VERIFIED_JSON_ONLY"},
                {"stage": "F2_native_raw_typed_label", "status": "ACTUAL_NATIVE_V4_TERMINAL_VERIFIED"},
                {"stage": "saved_frame_quality", "status": "ACTUAL_STRICT_PRODUCER_BOUND"},
                {"stage": "portable_raw_typed_label_replay", "status": "PENDING_CONSUMER_GUARD"},
                {"stage": "physical_fate_dynamics_QN_QE_QI", "status": "UNKNOWN"},
            ],
            "access": {"metadata_json_receipt_proof": "read-only workspace scope", "trajectory_h5": "forbidden", "label_h5": "forbidden", "bi4": "forbidden", "solver_model": "forbidden", "redistribution": "not authorized"},
        },
        "claim_boundary": {"finite": "field/lifecycle diagnostic scope; no numerical error bound", "mass": "source-visible lower bound only", "identity": "CURRENT and native motive identities", "time": "saved windows/brackets only", "censoring": "hidden crossings UNKNOWN", "failed_scope": "producer/field failure scope only", "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "QI": "UNKNOWN"},
        "read_policy": {"v29_json_opened": True, "v28_request_opened": True, "trajectory_h5_opened": False, "materialized_label_h5_opened": False, "part_bi4_opened": False, "raw_solver_output_opened": False, "solver_started": False, "model_invoked": False},
        "manifest_path": None,
    }
    return result


def build_catalog(v29_product: Path | str, v29_manifest: Path | str, v29_request: Path | str, v29_proof: Path | str, v29_receipt: Path | str, v28_request: Path | str, v28_handoff: Path | str, output: Path | str, manifest_output: Path | str) -> dict[str, Any]:
    v29_product, product = _json(v29_product, "actual v29 product")
    v29_manifest, manifest = _json(v29_manifest, "actual v29 manifest")
    v29_request, request = _json(v29_request, "actual v29 request")
    v29_proof, proof = _json(v29_proof, "actual v29 proof")
    v29_receipt, receipt = _json(v29_receipt, "actual v29 receipt")
    v28_request, v28 = _json(v28_request, "v28 guarded request")
    v28_handoff, handoff = _json(v28_handoff, "v28 handoff")
    result = _assemble(v29_product, product, v29_manifest, manifest, v29_request, request, v29_proof, proof, v29_receipt, receipt, v28_request, v28, v28_handoff, handoff)
    output = _path(output, "v30 output", output=True).resolve()
    manifest_output = _path(manifest_output, "v30 manifest output", output=True).resolve()
    if output.exists() or manifest_output.exists():
        raise ScopeError("refusing to overwrite v30 output")
    output.parent.mkdir(parents=True, exist_ok=True); manifest_output.parent.mkdir(parents=True, exist_ok=True)
    result["manifest_path"] = str(manifest_output)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest_data = {"schema": V30_MANIFEST_SCHEMA, "status": result["status"], "product": _ref(output, "v30 task-scope catalog"), "producer": result["producer"], "source": result["source"], "coverage": result["coverage"], "task_qualification": result["task_qualification"], "read_policy": result["read_policy"]}
    manifest_output.write_text(json.dumps(manifest_data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def make_request(v29_product: Path | str, v29_manifest: Path | str, v29_request: Path | str, v29_proof: Path | str, v29_receipt: Path | str, v28_request: Path | str, v28_handoff: Path | str, output: Path | str, runtime_root: Path | str, worker_root: Path | str, attempt_id: str = "task-scope-catalog-v30-forward-001") -> dict[str, Any]:
    paths = [v29_product, v29_manifest, v29_request, v29_proof, v29_receipt, v28_request, v28_handoff]
    loaded = [_json(item, label) for item, label in zip(paths, ("v29 product", "v29 manifest", "v29 request", "v29 proof", "v29 receipt", "v28 request", "v28 handoff"))]
    v29_product, product = loaded[0]; v29_manifest, manifest = loaded[1]; v29_request, request = loaded[2]; v29_proof, proof = loaded[3]; v29_receipt, receipt = loaded[4]; v28_request, v28 = loaded[5]; v28_handoff, handoff = loaded[6]
    _assemble(v29_product, product, v29_manifest, manifest, v29_request, request, v29_proof, proof, v29_receipt, receipt, v28_request, v28, v28_handoff, handoff)
    runtime_root = Path(runtime_root).expanduser().resolve(); worker_root = Path(worker_root).expanduser().resolve()
    worker = worker_root / "lagrangian-fluid-lab/scripts/ds_data02_stage2_task_scope_catalog_v30.py"
    runtime_files = [runtime_root / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py", runtime_root / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py", runtime_root / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"]
    inputs = [worker, *runtime_files, v29_product, v29_manifest, v29_request, v29_proof, v29_receipt, v28_request, v28_handoff]
    unique: list[Path] = []; seen: set[str] = set()
    for item in inputs:
        item = _path(item, "v30 request input")
        if str(item) not in seen: seen.add(str(item)); unique.append(item)
    hashes = {str(item): sha256_file(item) for item in unique}
    result = {
        "schema": "ds02.runner-request.v1", "request_schema": V30_REQUEST_SCHEMA, "attempt_id": attempt_id, "case_id": "DS02_STAGE2_TASK_SCOPE_CATALOG_V30", "family_id": "infra", "dataset_families": FAMILIES, "kind": "cpu", "cpu_task_kind": "metadata_task_scope_catalog", "cpu_threads": 1, "max_wall_seconds": 600, "estimated_storage_bytes": 16 * 1024 * 1024, "cwd": str(worker_root / "lagrangian-fluid-lab/scripts"), "worktree_root": str(worker_root),
        "command": ["/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python", str(worker), "build", "--v29-product", str(v29_product), "--v29-manifest", str(v29_manifest), "--v29-request", str(v29_request), "--v29-proof", str(v29_proof), "--v29-receipt", str(v29_receipt), "--v28-request", str(v28_request), "--v28-handoff", str(v28_handoff), "--output", "{attempt_root}/task-scope-catalog-v30.json", "--manifest-output", "{attempt_root}/task-scope-catalog-manifest-v30.json"],
        "input_files": [str(item) for item in unique], "input_sha256": hashes, "launch_allowed": True, "primary_launch_owner": "root", "status": "prepared_guard_pending_actual_CPU", "source_cost": {"small_json_receipt_proof_bytes_read": sum(item.stat().st_size for item in unique if item.suffix.lower() == ".json"), "trajectory_h5_bytes_read": 0, "materialized_label_h5_bytes_read": 0, "part_bi4_bytes_read": 0, "raw_solver_output_bytes_read": 0, "solver_started": False, "cfd_or_model_run": False}, "claim_boundary": {"finite": "field/lifecycle diagnostic only", "mass": "source-visible lower bound only", "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "QI": "UNKNOWN", "qualification_credit": "none"}, "read_policy": {"metadata_json_opened": True, "trajectory_h5_opened": False, "materialized_label_h5_opened": False, "part_bi4_opened": False, "solver_started": False, "model_invoked": False},
    }
    output = _path(output, "v30 request output", output=True).resolve()
    if output.exists(): raise ScopeError("refusing to overwrite v30 request")
    output.parent.mkdir(parents=True, exist_ok=True); output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest="command", required=True)
    for name in ("build", "make-request"):
        p = sub.add_parser(name)
        for arg in ("v29-product", "v29-manifest", "v29-request", "v29-proof", "v29-receipt", "v28-request", "v28-handoff"):
            p.add_argument(f"--{arg}", type=Path, required=True)
        p.add_argument("--output", type=Path, required=True)
        if name == "build": p.add_argument("--manifest-output", type=Path, required=True)
        else:
            p.add_argument("--runtime-root", type=Path, required=True); p.add_argument("--worker-root", type=Path, required=True); p.add_argument("--attempt-id", default="task-scope-catalog-v30-forward-001")
    args = parser.parse_args(argv)
    if args.command == "build":
        build_catalog(args.v29_product, args.v29_manifest, args.v29_request, args.v29_proof, args.v29_receipt, args.v28_request, args.v28_handoff, args.output, args.manifest_output)
    else:
        make_request(args.v29_product, args.v29_manifest, args.v29_request, args.v29_proof, args.v29_receipt, args.v28_request, args.v28_handoff, args.output, args.runtime_root, args.worker_root, args.attempt_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
