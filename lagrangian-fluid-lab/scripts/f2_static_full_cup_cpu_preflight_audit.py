#!/usr/bin/env python3
"""Audit the existing F2 static full-cup CPU/native preflight closure.

The v4 matrix preparation already generated and decoded all fifteen registered
cells.  This read-only audit independently re-hashes the matrix report,
candidate/admission/root-review contracts, every prepared/preflight receipt,
and each declared cell input closure.  It also reports observed input disk
use and the candidate's CPU reservation envelope.  It never runs GenCase,
the native decoder, a solver, CUDA, a queue, a registry, or a ledger.

The result is a readiness observation for a future root decision about one
static cell-0 canary.  It cannot establish dynamic pouring, receiving,
overflow, wetting, or F2 T1 qualification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA = "core.f2.static_full_cup.cpu_preflight_audit.v1"
EXPECTED_CELLS = 15
EXPECTED_SCOPE = "F2_static_full_cup_volume_hold_x_v1"
EXPECTED_CANDIDATE = "F2_static_full_cup_volume_hold"


def digest(path: str | Path) -> str:
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            value.update(block)
    return value.hexdigest()


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def load(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def resolve(root: Path, value: str | Path) -> Path:
    path = Path(value).expanduser()
    return (path if path.is_absolute() else root / path).resolve()


def under(root: Path, path: Path) -> Path:
    path = path.resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as error:
        raise ValueError(f"input closure escapes lab root: {path}") from error
    return path


def ref(path: Path, root: Path, role: str) -> dict[str, Any]:
    path = under(root, path)
    if not path.is_file():
        raise FileNotFoundError(path)
    return {
        "path": str(path),
        "relative_to_lab": path.relative_to(root).as_posix(),
        "sha256": digest(path),
        "bytes": path.stat().st_size,
        "role": role,
    }


def verify_ref(item: Mapping[str, Any], root: Path, *, role: str) -> dict[str, Any]:
    path_value = item.get("path")
    if not isinstance(path_value, str) or not path_value:
        raise ValueError(f"{role} has no path")
    path = under(root, resolve(root, path_value))
    if not path.is_file():
        raise FileNotFoundError(f"{role}: {path}")
    observed = digest(path)
    declared = item.get("sha256")
    if not isinstance(declared, str) or observed != declared:
        raise ValueError(f"{role} SHA-256 mismatch: {path}")
    if item.get("bytes") is not None and int(item["bytes"]) != path.stat().st_size:
        raise ValueError(f"{role} byte count mismatch: {path}")
    return {
        "path": str(path),
        "relative_to_lab": path.relative_to(root).as_posix(),
        "sha256": observed,
        "bytes": path.stat().st_size,
        "role": role,
    }


def _check(errors: list[str], condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


def _load_cli_ref(root: Path, path: str | Path, role: str) -> tuple[dict[str, Any], dict[str, Any]]:
    resolved = under(root, resolve(root, path))
    payload = load(resolved)
    return payload, ref(resolved, root, role)


def _verify_contracts(
    *, root: Path, candidate: Mapping[str, Any], admission: Mapping[str, Any],
    root_review: Mapping[str, Any], scope_review: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    candidate_design = candidate.get("qualification_design", {})
    candidate_cells = candidate_design.get("cells", [])
    _check(errors, candidate.get("schema") == "core.f2.static_full_cup_volume_candidate.v1", "candidate schema mismatch")
    _check(errors, candidate.get("candidate_id") == EXPECTED_CANDIDATE, "candidate id mismatch")
    _check(errors, candidate.get("scope_id") == EXPECTED_SCOPE, "candidate scope mismatch")
    _check(errors, candidate.get("qualification_only") is True, "candidate is not qualification-only")
    _check(errors, candidate.get("qualified") is False, "candidate is marked qualified")
    _check(errors, candidate.get("central_ledger_mutation") == 0, "candidate permits ledger mutation")
    _check(errors, candidate.get("gpu_launch_by_subagent") is False, "candidate permits subagent GPU launch")
    _check(errors, candidate_design.get("cell_count") == EXPECTED_CELLS, "candidate cell count is not 15")
    _check(errors, len(candidate_cells) == EXPECTED_CELLS, "candidate cell list is not 15 rows")
    _check(errors, candidate_design.get("matrix_inputs_materialized") is False, "candidate design was mutated")
    _check(errors, candidate_design.get("matrix_jobs_materialized") is False, "candidate jobs were materialized")
    physical = candidate.get("physical_contract", {})
    motion = physical.get("motion", {})
    _check(errors, float(motion.get("angle_degrees", math.nan)) == 0.0, "candidate is not zero-angle static")
    _check(errors, "fixed cup" in str(physical.get("scene", "")), "candidate scene is not fixed-cup static")
    _check(errors, str(candidate.get("qualification_claim", "")).startswith("none;"), "candidate qualification claim is not closed")

    _check(errors, admission.get("schema") == "core.f2.static_full_cup.qualification_admission.v1", "admission schema mismatch")
    _check(errors, admission.get("scope_id") == EXPECTED_SCOPE, "admission scope mismatch")
    _check(errors, admission.get("qualification_claim") == "none; candidate static-volume scope only", "admission claim changed")
    controls = admission.get("admission_controls", {})
    for key in ("solver_launch_allowed", "gpu_launch_allowed", "job_spec_creation_allowed",
                "queue_mutation_allowed", "ledger_mutation_allowed", "registry_mutation_allowed"):
        _check(errors, controls.get(key) is False, f"admission control is open: {key}")
    product = admission.get("required_runtime_product_per_cell", {})
    _check(errors, product.get("fixed_denominator") == EXPECTED_CELLS, "admission denominator is not 15")
    _check(errors, product.get("anchor_trajectory_reuse") is False, "admission allows anchor trajectory reuse")
    _check(errors, product.get("missing_or_failed_rows_retained") is True, "admission drops failed rows")

    _check(errors, root_review.get("schema") == "core.f2.static_full_cup.root_review.v1", "root review schema mismatch")
    _check(errors, root_review.get("scope_id") == EXPECTED_SCOPE, "root review scope mismatch")
    _check(errors, root_review.get("status") == "approved_for_cpu_only_prepare_decode_pending_execution", "root review status changed")
    decision = root_review.get("root_review_decision", {})
    _check(errors, decision.get("cpu_only_full_matrix_prepare_decode_allowed_subsequently") is True, "root review does not allow CPU preflight")
    for key in ("solver_allowed", "gpu_allowed", "matrix_job_creation_allowed",
                "central_registry_mutation_allowed", "central_ledger_mutation_allowed"):
        _check(errors, decision.get(key) is False, f"root review opened forbidden action: {key}")
    review_controls = root_review.get("execution_controls", {})
    for key in ("gen_case_run_now", "decoder_run_now", "solver_run_now", "gpu_launch_now", "matrix_inputs_materialized_now", "matrix_jobs_materialized_now"):
        _check(errors, review_controls.get(key) is False, f"root review execution control changed: {key}")
    for key in ("queue_mutation_now", "ledger_mutation_now", "registry_mutation_now"):
        _check(errors, review_controls.get(key) == 0, f"root review central mutation changed: {key}")
    _check(errors, root_review.get("qualification_claim", "").startswith("none;"), "root review carries a qualification claim")

    _check(errors, scope_review.get("schema") == "core.scope_review.v1", "scope review schema mismatch")
    _check(errors, scope_review.get("decision") == "prerequisite_only", "static scope review is not prerequisite-only")
    _check(errors, scope_review.get("static_qualification_matrix_launch_admitted") is False, "scope review admits static qualification launch")
    _check(errors, scope_review.get("core_third_family_admitted") is False, "scope review admits F2 as a third family")
    return {
        "candidate_id": candidate.get("candidate_id"),
        "scope_id": candidate.get("scope_id"),
        "qualification_only": candidate.get("qualification_only"),
        "qualified": candidate.get("qualified"),
        "static_zero_angle": True,
        "dynamic_qualification_admitted": False,
        "candidate_cell_count": len(candidate_cells),
    }, errors


def _tree_bytes(path: Path) -> dict[str, int]:
    totals: dict[str, int] = {}
    for item in path.rglob("*"):
        if item.is_file() and not item.name.endswith(".partial"):
            relative = item.relative_to(path)
            top = relative.parts[0] if relative.parts else item.name
            totals[top] = totals.get(top, 0) + item.stat().st_size
    totals["total"] = sum(totals.values())
    return totals


def _resource_contract(candidate: Mapping[str, Any], dp: float) -> tuple[str, Mapping[str, Any]]:
    per_cell = candidate.get("resource_estimate", {}).get("per_cell", {})
    for key, value in per_cell.items():
        if not str(key).startswith("dp_"):
            continue
        try:
            if math.isclose(float(str(key)[3:]), float(dp), rel_tol=0.0, abs_tol=1e-12):
                return str(key), value
        except ValueError:
            continue
    raise ValueError(f"candidate has no resource contract for dp={dp}")


def _audit_cell(row: Mapping[str, Any], denominator_row: Mapping[str, Any], *, root: Path,
                candidate: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    errors: list[str] = []
    index = int(denominator_row.get("index", row.get("index", -1)))
    case_id = str(denominator_row.get("case_id", row.get("case_id", "")))
    _check(errors, index == int(row.get("index", -1)), "row index differs from failure denominator")
    _check(errors, case_id == str(row.get("case_id", "")), "row case_id differs from failure denominator")
    _check(errors, row.get("status") == "prepared", "cell is not prepared")
    _check(errors, row.get("preflight_pass") is True, "cell preflight_pass is not true")
    prepared_payload: dict[str, Any] | None = None
    preflight_payload: dict[str, Any] | None = None
    prepared_ref: dict[str, Any] | None = None
    preflight_ref: dict[str, Any] | None = None
    try:
        prepared_path = under(root, resolve(root, str(row.get("prepared", ""))))
        prepared_ref = verify_ref({"path": str(prepared_path), "sha256": row.get("prepared_sha256")}, root, role=f"cell {index} prepared")
        prepared_payload = load(prepared_path)
    except Exception as error:  # retain the row as a failed denominator entry
        errors.append(f"prepared binding: {type(error).__name__}: {error}")
    try:
        preflight_path = under(root, resolve(root, str(row.get("preflight", ""))))
        preflight_ref = verify_ref({"path": str(preflight_path), "sha256": row.get("preflight_sha256")}, root, role=f"cell {index} preflight")
        preflight_payload = load(preflight_path)
    except Exception as error:
        errors.append(f"preflight binding: {type(error).__name__}: {error}")

    resource: dict[str, Any] | None = None
    if prepared_payload is not None:
        _check(errors, prepared_payload.get("schema") == "core.f2.static_full_cup.matrix_cell_prepared.v1", "prepared schema mismatch")
        _check(errors, prepared_payload.get("candidate_id") == EXPECTED_CANDIDATE, "prepared candidate mismatch")
        _check(errors, prepared_payload.get("scope_id") == EXPECTED_SCOPE, "prepared scope mismatch")
        _check(errors, int(prepared_payload.get("index", -1)) == index, "prepared index mismatch")
        _check(errors, prepared_payload.get("case_id") == case_id, "prepared case identity mismatch")
        for key in ("preflight_pass", "hash_closure_pass"):
            _check(errors, prepared_payload.get(key) is True, f"prepared {key} is not true")
        for key in ("mass_rescaling", "solver_invoked", "gpu_invoked", "queue_mutated", "ledger_mutated", "registry_mutated"):
            _check(errors, prepared_payload.get(key) is False, f"prepared execution control changed: {key}")
        _check(errors, str(prepared_payload.get("qualification_claim", "")).startswith("none;"), "prepared claim is not closed")

        closure = prepared_payload.get("hash_closure", [])
        closure_errors: list[str] = []
        verified_refs: list[dict[str, Any]] = []
        if not isinstance(closure, list) or not closure:
            closure_errors.append("hash_closure is empty")
        else:
            for item in closure:
                try:
                    verified_refs.append(verify_ref(item, root, role=f"cell {index} closure"))
                except Exception as error:
                    closure_errors.append(f"{type(error).__name__}: {error}")
        errors.extend(f"input closure: {item}" for item in closure_errors)
        closure_keyset = {item.get("path") for item in closure if isinstance(item, Mapping)}
        definition = prepared_payload.get("definition_audit", {}).get("definition")
        motion_name = prepared_payload.get("definition_audit", {}).get("motion_file_name")
        generated_prefix = prepared_payload.get("generated_prefix")
        decoded_directory = prepared_payload.get("preflight")
        expected_paths = []
        if isinstance(definition, str):
            expected_paths.append(resolve(root, definition))
            if isinstance(motion_name, str):
                expected_paths.append(resolve(root, str(Path(definition).parent / motion_name)))
        if isinstance(generated_prefix, str):
            expected_paths.extend([resolve(root, generated_prefix + suffix) for suffix in (".xml", ".bi4")])
        for expected in expected_paths:
            _check(errors, str(expected) in closure_keyset or str(expected.resolve()) in closure_keyset,
                   f"input closure omits generated input: {expected}")
            _check(errors, expected.is_file(), f"generated input missing: {expected}")
        decoded_dir = None
        if preflight_payload is not None and isinstance(preflight_payload.get("decoded_directory"), str):
            decoded_dir = resolve(root, preflight_payload["decoded_directory"])
        if decoded_dir is None and isinstance(decoded_directory, str):
            decoded_dir = resolve(root, decoded_directory)
        _check(errors, decoded_dir is not None and decoded_dir.is_dir() and any(decoded_dir.rglob("*")), "decoded native directory is missing or empty")
        _check(errors, not any(str(item.get("path", "")).lower().endswith((".h5", ".hdf5")) for item in closure if isinstance(item, Mapping)), "trajectory input appears in CPU preflight closure")

        try:
            key, contract = _resource_contract(candidate, float(prepared_payload.get("dp_m")))
            files = _tree_bytes(prepared_path.parent)
            resource = {
                "contract_key": key,
                "cpu_cores": int(contract["cpu_cores"]),
                "ram_mib": int(contract["ram_mib"]),
                "gpu_peak_mib_recorded_only": int(contract["gpu_peak_mib"]),
                "timeout_seconds": int(contract["timeout_seconds"]),
                "artifact_bytes": files,
                "artifact_mib": files["total"] / (1024.0 * 1024.0),
                "fluid_particles": int(prepared_payload.get("sampling", {}).get("particle_count", 0)),
                "native_total_particles": int((preflight_payload or {}).get("native_source", {}).get("total_particles", 0)),
                "hash_closure_declared_count": len(closure) if isinstance(closure, list) else 0,
                "hash_closure_verified_count": len(verified_refs),
                "hash_closure_sha256": canonical_digest([
                    {"path": item["path"], "sha256": item["sha256"], "bytes": item["bytes"]}
                    for item in sorted(verified_refs, key=lambda item: item["path"])
                ]) if not closure_errors else None,
            }
        except Exception as error:
            errors.append(f"resource contract: {type(error).__name__}: {error}")

    if preflight_payload is not None:
        _check(errors, preflight_payload.get("schema") == "core.f2.static_full_cup.matrix_cell_preflight.v1", "preflight schema mismatch")
        _check(errors, preflight_payload.get("case_id") == case_id, "preflight case identity mismatch")
        _check(errors, int(preflight_payload.get("index", -1)) == index, "preflight index mismatch")
        _check(errors, preflight_payload.get("preflight_pass") is True, "preflight result is not passed")
        _check(errors, preflight_payload.get("trajectory_or_solver_checked") is False, "preflight checked a trajectory or solver")
        _check(errors, preflight_payload.get("mass_rescaling") is False, "preflight permits mass rescaling")
        checks = preflight_payload.get("checks", {})
        for name, value in checks.items():
            _check(errors, value is True, f"preflight check failed: {name}")
        for name in ("generated_definition", "native_bi4", "decoder"):
            value = preflight_payload.get(name)
            _check(errors, isinstance(value, str) and resolve(root, value).is_file(), f"preflight {name} missing")

    status = "passed" if not errors else "failed"
    result = {
        "index": index,
        "case_id": case_id,
        "q": denominator_row.get("q", row.get("q")),
        "dp_m": denominator_row.get("dp_m", row.get("dp_m")),
        "design_cell": denominator_row.get("design_cell", row.get("design_cell")),
        "denominator_included": True,
        "status": status,
        "prepared": prepared_ref,
        "preflight": preflight_ref,
        "resource": resource,
        "errors": errors,
        "failure": None if not errors else {"type": "CPU_PREFLIGHT_AUDIT_FAILURE", "messages": errors},
    }
    return result, resource


def audit(
    *, lab_root: str | Path, candidate: str | Path, admission: str | Path,
    root_review: str | Path, scope_review: str | Path,
    matrix_report: str | Path, matrix_audit: str | Path,
) -> dict[str, Any]:
    root = Path(lab_root).expanduser().resolve()
    candidate_payload, candidate_ref = _load_cli_ref(root, candidate, "candidate card")
    admission_payload, admission_ref = _load_cli_ref(root, admission, "admission contract")
    root_review_payload, root_review_ref = _load_cli_ref(root, root_review, "CPU root review")
    scope_review_payload, scope_review_ref = _load_cli_ref(root, scope_review, "static scope review")
    matrix_payload, matrix_ref = _load_cli_ref(root, matrix_report, "matrix preparation report")
    matrix_audit_payload, matrix_audit_ref = _load_cli_ref(root, matrix_audit, "matrix preparation audit")

    contract_summary, contract_errors = _verify_contracts(
        root=root, candidate=candidate_payload, admission=admission_payload,
        root_review=root_review_payload, scope_review=scope_review_payload)
    matrix_errors: list[str] = []
    _check(matrix_errors, matrix_payload.get("schema") == "core.f2.static_full_cup.matrix_preparation.v1", "matrix report schema mismatch")
    _check(matrix_errors, matrix_payload.get("candidate_id") == EXPECTED_CANDIDATE, "matrix candidate mismatch")
    _check(matrix_errors, matrix_payload.get("scope_id") == EXPECTED_SCOPE, "matrix scope mismatch")
    _check(matrix_errors, matrix_payload.get("registered_cell_count") == EXPECTED_CELLS, "matrix denominator is not 15")
    _check(matrix_errors, matrix_payload.get("prepared_cell_count") == EXPECTED_CELLS, "matrix prepared count is not 15")
    _check(matrix_errors, matrix_payload.get("failed_cell_count") == 0, "matrix contains failed rows")
    _check(matrix_errors, matrix_payload.get("unattempted_cell_count") == 0, "matrix contains unattempted rows")
    controls = matrix_payload.get("execution_controls", {})
    for key, expected in {
        "solver_invoked": False, "gpu_invoked": False, "queue_mutation": 0,
        "ledger_mutation": 0, "registry_mutation": 0, "matrix_jobs_materialized": False,
        "qualification_claim_allowed": False,
    }.items():
        _check(matrix_errors, controls.get(key) == expected, f"matrix execution control changed: {key}")
    _check(matrix_errors, matrix_payload.get("candidate_matrix_jobs_materialized") is False, "matrix report claims jobs")
    _check(matrix_errors, matrix_payload.get("failure_denominator", {}).get("fixed_registered_cell_denominator") == EXPECTED_CELLS, "matrix failure denominator is not fixed")
    _check(matrix_errors, matrix_payload.get("failure_denominator", {}).get("failed_rows_are_not_dropped") is True, "matrix failure denominator drops failed rows")
    _check(matrix_errors, matrix_payload.get("failure_denominator", {}).get("survivor_renormalization") is False, "matrix renormalizes survivors")
    _check(matrix_errors, matrix_audit_payload.get("source_report", {}).get("sha256") == matrix_ref["sha256"], "matrix audit is not bound to current report")
    _check(matrix_errors, matrix_audit_payload.get("schema") == "core.f2.static_full_cup.matrix_preparation_audit.v1", "matrix audit schema mismatch")
    _check(matrix_errors, matrix_audit_payload.get("fixed_failure_denominator") is True, "matrix audit does not preserve denominator")
    _check(matrix_errors, matrix_audit_payload.get("T1_numerical") is False, "matrix audit claims T1 numerical")
    _check(matrix_errors, matrix_audit_payload.get("scientific_results_present") is False, "matrix audit contains scientific results")

    rows = matrix_payload.get("cells", [])
    denominator = matrix_payload.get("failure_denominator", {}).get("rows", [])
    rows_by_index = {int(row.get("index", -1)): row for row in rows if isinstance(row, Mapping)}
    denominator_by_index = {int(row.get("index", -1)): row for row in denominator if isinstance(row, Mapping)}
    cell_results: list[dict[str, Any]] = []
    resource_rows: list[dict[str, Any]] = []
    for index in range(EXPECTED_CELLS):
        row = rows_by_index.get(index, {"index": index})
        denom_row = denominator_by_index.get(index, {
            "index": index,
            "case_id": next((cell.get("case_id") for cell in candidate_payload.get("qualification_design", {}).get("cells", []) if int(cell.get("index", -1)) == index), f"missing-cell-{index}"),
            "status": "missing",
        })
        result, resource = _audit_cell(row, denom_row, root=root, candidate=candidate_payload)
        cell_results.append(result)
        if resource is not None:
            resource_rows.append({"index": result["index"], "case_id": result["case_id"], **resource})

    passed = sum(item["status"] == "passed" for item in cell_results)
    failed = EXPECTED_CELLS - passed
    blocker_codes: list[str] = []
    if contract_errors:
        blocker_codes.append("CONTRACT_CLOSURE_GAP")
    if matrix_errors:
        blocker_codes.append("MATRIX_REPORT_CLOSURE_GAP")
    if failed:
        blocker_codes.append("CPU_PREFLIGHT_FAILURE")
    resource_totals = {
        "observed_artifact_bytes": sum(int(item["artifact_bytes"]["total"]) for item in resource_rows),
        "observed_artifact_mib": sum(int(item["artifact_bytes"]["total"]) for item in resource_rows) / (1024.0 * 1024.0),
        "maximum_cell_artifact_bytes": max((int(item["artifact_bytes"]["total"]) for item in resource_rows), default=0),
        "maximum_cell_artifact_mib": max((float(item["artifact_mib"]) for item in resource_rows), default=0.0),
        "maximum_ram_mib_reserved": max((int(item["ram_mib"]) for item in resource_rows), default=0),
        "maximum_cpu_cores_reserved": max((int(item["cpu_cores"]) for item in resource_rows), default=0),
        "reservation_timeout_seconds_sum": sum(int(item["timeout_seconds"]) for item in resource_rows),
        "reservation_timeout_hours_sum": sum(int(item["timeout_seconds"]) for item in resource_rows) / 3600.0,
        "maximum_recorded_gpu_peak_mib_metadata_only": max((int(item["gpu_peak_mib_recorded_only"]) for item in resource_rows), default=0),
        "resource_measurement_scope": "observed CPU/native input artifact bytes plus candidate reservation envelope; no solver/GPU timing was run",
    }
    status = "ready_for_root_canary_review" if not blocker_codes and passed == EXPECTED_CELLS else "blocked"
    canary = cell_results[0] if cell_results else {"status": "missing"}
    canary_recommendation = bool(status == "ready_for_root_canary_review" and canary.get("status") == "passed")
    return {
        "schema": SCHEMA,
        "audit_version": "f2-static-full-cup-cpu-preflight-audit-v1",
        "status": status,
        "blocker_codes": blocker_codes,
        "scope": {
            **contract_summary,
            "claim": "resting numerical F2 static full-cup volume-hold only",
            "dynamic_pouring_receiving_overflow_wetting_qualification": False,
            "t1_numerical": False,
        },
        "candidate": candidate_ref,
        "admission_contract": admission_ref,
        "root_review": root_review_ref,
        "static_scope_review": scope_review_ref,
        "matrix_report": matrix_ref,
        "matrix_audit": matrix_audit_ref,
        "contract_errors": contract_errors,
        "matrix_errors": matrix_errors,
        "failure_denominator": {
            "registered_cell_count": EXPECTED_CELLS,
            "included_cell_count": EXPECTED_CELLS,
            "passed_cell_count": passed,
            "failed_or_unresolved_cell_count": failed,
            "rows": cell_results,
            "all_rows_retained": True,
            "failed_rows_are_not_dropped": True,
            "survivor_renormalization": False,
            "any_cell_failure_blocks_f2_t1_registration": True,
        },
        "resource_estimate": {
            "source": "candidate_card.resource_estimate plus observed v4 cell artifact sizes",
            "rows": resource_rows,
            "totals": resource_totals,
            "gpu_fields_are_estimates_only": True,
        },
        "canary_recommendation": {
            "first_cell_index": 0,
            "first_cell_case_id": canary.get("case_id"),
            "worth_requesting_separate_root_approval": canary_recommendation,
            "current_runtime_authorized": False,
            "reason": (
                "all 15 CPU/native preflight rows and input closures pass; cell 0 is the nominal q=0, dp=0.010 static row. "
                "A separate root review is still required before any solver/GPU/job action."
                if canary_recommendation else
                "cell 0 cannot be recommended while the fixed 15-row CPU/native closure has unresolved failures"
            ),
            "required_next_action": "separate explicit root review for exactly one static cell-0 canary",
        },
        "execution_constraints": {
            "read_only_audit": True,
            "gencase_invoked_by_audit": False,
            "native_decoder_invoked_by_audit": False,
            "solver_invoked": False,
            "gpu_invoked": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "matrix_jobs_materialized": False,
            "qualification_claim_emitted": False,
        },
        "generator": {
            "path": "scripts/f2_static_full_cup_cpu_preflight_audit.py",
            "sha256": digest(Path(__file__).resolve()),
        },
    }


def write_immutable(path: str | Path, payload: Mapping[str, Any]) -> None:
    path = Path(path).expanduser().resolve()
    if path.exists():
        raise FileExistsError(f"immutable audit output already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    partial.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    partial.replace(path)


def write_sha256(path: str | Path, source: str | Path) -> None:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise FileExistsError(f"immutable audit digest already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"{digest(source)}  {Path(source).name}\n", encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-root", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--admission", type=Path, required=True)
    parser.add_argument("--root-review", type=Path, required=True)
    parser.add_argument("--scope-review", type=Path, required=True)
    parser.add_argument("--matrix-report", type=Path, required=True)
    parser.add_argument("--matrix-audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sha256-output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = audit(
        lab_root=args.lab_root, candidate=args.candidate, admission=args.admission,
        root_review=args.root_review, scope_review=args.scope_review,
        matrix_report=args.matrix_report, matrix_audit=args.matrix_audit,
    )
    write_immutable(args.output, report)
    write_sha256(args.sha256_output, args.output)
    print(json.dumps({"status": report["status"], "blocker_codes": report["blocker_codes"],
                      "passed_cell_count": report["failure_denominator"]["passed_cell_count"],
                      "failed_cell_count": report["failure_denominator"]["failed_or_unresolved_cell_count"],
                      "worth_requesting_separate_root_approval": report["canary_recommendation"]["worth_requesting_separate_root_approval"]}, sort_keys=True))
    return 0 if report["status"] == "ready_for_root_canary_review" else 2


if __name__ == "__main__":
    raise SystemExit(main())
