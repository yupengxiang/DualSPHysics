#!/usr/bin/env python3
"""Build a bounded, non-authorizing F1 formal-run readiness projection.

This bridge joins the existing F1 preparation, qualification metadata, fixed
15-cell job plan, evaluation summary, and retained negative evidence.  It
reads only a fixed allow-list of bounded JSON files.  Paths recorded inside
those JSON files are treated as metadata and are never followed, opened,
stat'ed, hashed, or decoded.

The result is deliberately fail-closed.  F1 preparation is not a formal
runtime, a historical failed canary is not a terminal pass, and a complete
event window does not rescue a hard-integrity failure.  The bridge does not
launch or stop any solver, worker, native decoder, GPU, or queue and does not
mutate the registry, ledger, denominator, gate, PLAN, or completion state.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any, Mapping, Sequence


LAB_ROOT = Path(__file__).resolve().parents[1]
REPORT_SCHEMA = "core.f1.formal_run_readiness_evidence_bridge_report.v1"
RECORD_ID = "f1-formal-run-readiness-evidence-bridge-v1"
SCOPE_ID = "F1_single_obstacle_height_range_v1"
DESIGN_REVISION = "F1_H1_geometry_observer_qualification_v1"
CANDIDATE_REVISION = "F1_H1_obstacle_height_range_v1"
OBSERVED_AT_UTC = "2026-09-28T00:00:00Z"
MAX_JSON_BYTES = 256 * 1024
SHA256_HEX = frozenset("0123456789abcdef")

DEFAULT_REPORT = LAB_ROOT / "reports/F1-FORMAL-RUN-READINESS-EVIDENCE-BRIDGE-V1-2026-09-28.json"
DEFAULT_ZH_REPORT = LAB_ROOT / "reports/F1-FORMAL-RUN-READINESS-EVIDENCE-BRIDGE-V1-2026-09-28.zh-CN.md"

DEPENDENCY_SPECS: dict[str, dict[str, Any]] = {
    "candidate_card": {
        "path": Path("campaigns/core-v1/cfd/f1-reference-candidate-card.json"),
        "schema": "core.cfd.static.v1",
        "role": "15-cell F1 candidate contract",
    },
    "qualification_design": {
        "path": Path("campaigns/core-v1/cfd/f1-reference-qualification-design.json"),
        "schema": "core.f1.qualification.v1",
        "role": "F1 qualification design and observer metadata",
    },
    "prepared_matrix": {
        "path": Path("campaigns/core-v1/cfd/prepared/F1_H1_qualification/prepared-matrix.json"),
        "schema": "core.f1.qualification.v1",
        "role": "15-cell preparation aggregate",
    },
    "static_validation": {
        "path": Path("campaigns/core-v1/cfd/f1-reference-static-validation.json"),
        "schema": "core.cfd.static.v1",
        "role": "bounded F1 static/preparation validation metadata",
    },
    "jobs_manifest": {
        "path": Path("campaigns/core-v1/cfd/f1-reference-qualification-jobs.json"),
        "schema": "core.cfd.jobs.v1",
        "role": "fixed 15-cell formal job metadata",
    },
    "qualification_evaluation": {
        "path": Path("campaigns/core-v1/cfd/f1-qualification-evaluation.json"),
        "schema": "core.f1.qualification.v1",
        "role": "F1 qualification evaluation summary",
    },
    "observer_calibration": {
        "path": Path("campaigns/core-v1/cfd/f1-observer-calibration.json"),
        "schema": "core.f1.observer.calibration.v1",
        "role": "manufactured observer calibration metadata",
    },
    "route_closed": {
        "path": Path("campaigns/core-v1/cfd/f1-f2-third-t1-route-closed-v3.json"),
        "schema": "core.third_t1.f1_f2_route_closed.candidate_card.v3",
        "role": "current F1/F2 route authorization and denominator policy",
    },
    "terminal_canary_audit": {
        "path": Path("campaigns/core-v1/evidence/f1-fullwindow-failed-audit.json"),
        "schema": "core.cfd.v1",
        "role": "historical F1 full-window canary audit",
    },
    "h2_repair_stop": {
        "path": Path("campaigns/core-v1/evidence/f1-h2-mdbc-summary.json"),
        "schema": "core.canary_result.v1",
        "role": "historical H1/H2 repair-stop negative evidence",
    },
    "g1_negative_anchor": {
        "path": Path("campaigns/core-v1/evidence/f1-suspended-obstacle-gap-g1-anchor-negative-evidence-v1.json"),
        "schema": "core.f1.suspended_obstacle_gap.negative_evidence.v1",
        "role": "historical G1 hard-integrity negative anchor",
    },
}

BLOCKER_CODES = (
    "fresh_f1_reopen_authorization_missing",
    "formal_runtime_products_missing",
    "source_identity_closure_missing",
    "terminal_evidence_missing_or_failed",
    "fixed_15_row_denominator_incomplete",
    "qualification_gates_incomplete",
    "material_evidence_absent",
)

AUTHORIZATION = {
    "diagnostic_only": True,
    "readiness_projection_only": True,
    "formal_run_ready": False,
    "execution_authorized": False,
    "formal": False,
    "formal_eligible": False,
    "qualification": False,
    "T1_numerical": False,
    "T2_macro": False,
    "T2_path": False,
    "T2": False,
    "qualification_credit": 0,
    "T2_credit": 0,
    "credit": 0,
    "registry_eligible": False,
}

MUTATIONS = {
    "completion_mutation": 0,
    "denominator_mutation": 0,
    "gate_mutation": 0,
    "ledger_mutation": 0,
    "plan_mutation": 0,
    "queue_mutation": 0,
    "registry_mutation": 0,
}

READ_POLICY = {
    "bounded_json_allowlist_only": True,
    "max_json_bytes": MAX_JSON_BYTES,
    "production_hdf5_bi4_trajectory_opened": False,
    "production_hdf5_bi4_trajectory_stat_or_hash": False,
    "nested_artifact_paths_followed": False,
    "xml_or_native_input_opened": False,
    "solver_worker_native_gpu_queue": False,
    "registry_ledger_denominator_gate_plan_write": False,
}

SIDE_EFFECTS = {
    "bounded_json_inputs_opened": True,
    "production_hdf5_opened": False,
    "production_bi4_opened": False,
    "production_trajectory_opened": False,
    "production_artifact_stat_or_hash": False,
    "solver_started": False,
    "worker_started": False,
    "native_started": False,
    "gpu_started": False,
    "queue_started": False,
    "completion_mutation": 0,
    "denominator_mutation": 0,
    "gate_mutation": 0,
    "ledger_mutation": 0,
    "plan_mutation": 0,
    "registry_mutation": 0,
}

PROHIBITED_OPERATIONS = (
    "production_hdf5_bi4_trajectory_read_or_hash",
    "nested_artifact_path_follow_or_open",
    "xml_native_or_solver_input_execution",
    "solver_worker_native_gpu_queue_start",
    "registry_ledger_denominator_gate_plan_completion_mutation",
    "preparation_or_historical_failure_promoted_to_formal_T1_or_T2",
)


class ReadinessBridgeError(ValueError):
    """A bounded input or fail-closed report contract is invalid."""


def _fail(message: str) -> None:
    raise ReadinessBridgeError(f"fail-closed: {message}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _reject_constant(token: str) -> Any:
    _fail(f"non-standard JSON constant is not allowed: {token}")


def _check_finite(value: Any, label: str) -> None:
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            _fail(f"{label} contains a non-finite number")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            _check_finite(item, f"{label}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _check_finite(item, f"{label}[{index}]")


def _identity(info: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
        info.st_nlink,
    )


def _display_path(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _safe_json_path(root: Path, value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    if any(part in {"", ".", ".."} for part in path.parts[1:]):
        _fail(f"non-canonical JSON input path: {value}")
    if path.suffix.lower() != ".json":
        _fail(f"non-JSON input rejected before open: {value}")
    return path


def _assert_no_symlink_components(path: Path) -> None:
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current /= component
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            continue
        except OSError as error:
            raise ReadinessBridgeError(f"fail-closed: cannot inspect path {path}") from error
        if stat.S_ISLNK(info.st_mode):
            _fail(f"symlink component rejected: {path}")


def _read_bounded_json(root: Path, value: str | Path, *, role: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _safe_json_path(root, value)
    _assert_no_symlink_components(path)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(os.fspath(path), flags)
    except (FileNotFoundError, OSError) as error:
        _fail(f"JSON input is unavailable: {_display_path(root, path)}")
        raise AssertionError from error

    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            _fail(f"JSON input is not a single-link regular file: {_display_path(root, path)}")
        if before.st_size <= 0 or before.st_size > MAX_JSON_BYTES:
            _fail(f"JSON input exceeds bounded limit: {_display_path(root, path)}")
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            block = os.read(descriptor, min(64 * 1024, remaining))
            if not block:
                _fail(f"JSON input was truncated while read: {_display_path(root, path)}")
            chunks.append(block)
            remaining -= len(block)
        if os.read(descriptor, 1) != b"":
            _fail(f"JSON input grew while read: {_display_path(root, path)}")
        after = os.fstat(descriptor)
        named = os.stat(path, follow_symlinks=False)
        if _identity(before) != _identity(after) or _identity(after) != _identity(named):
            _fail(f"JSON input changed while read: {_display_path(root, path)}")
        raw = b"".join(chunks)
    except ReadinessBridgeError:
        raise
    except OSError as error:
        raise ReadinessBridgeError(f"fail-closed: JSON input read failed: {path}") from error
    finally:
        os.close(descriptor)

    try:
        value_obj = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except ReadinessBridgeError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReadinessBridgeError(f"fail-closed: invalid strict JSON input: {path}") from error
    if type(value_obj) is not dict:
        _fail(f"JSON input must be an object: {_display_path(root, path)}")
    _check_finite(value_obj, role)
    return value_obj, {
        "role": role,
        "path": _display_path(root, path),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "content_opened": True,
        "nested_artifact_paths_followed": False,
    }


def _read_dependencies(
    root: Path,
    dependency_paths: Mapping[str, str | Path] | None,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    payloads: dict[str, dict[str, Any]] = {}
    references: dict[str, dict[str, Any]] = {}
    overrides = dependency_paths or {}
    for key, spec in DEPENDENCY_SPECS.items():
        value = overrides.get(key, spec["path"])
        payload, reference = _read_bounded_json(root, value, role=spec["role"])
        if payload.get("schema") != spec["schema"]:
            _fail(f"{key} schema drift: {payload.get('schema')!r}")
        references[key] = {**reference, "expected_schema": spec["schema"]}
        payloads[key] = payload
    return payloads, references


def _require(condition: bool, message: str) -> None:
    if not condition:
        _fail(message)


def _validate_contracts(payloads: Mapping[str, Mapping[str, Any]]) -> None:
    candidate = payloads["candidate_card"]
    _require(candidate.get("scope_id") == SCOPE_ID, "candidate scope drift")
    _require(candidate.get("revision_id") == CANDIDATE_REVISION, "candidate revision drift")
    _require(candidate.get("candidate_status") == "pre_registered_unqualified", "candidate status drift")
    _require(candidate.get("cell_count") == 15, "candidate denominator drift")
    _require(candidate.get("qualification_claim") == "none", "candidate qualification claim drift")
    candidate_cells = candidate.get("cells")
    _require(type(candidate_cells) is list and len(candidate_cells) == 15, "candidate cell rows drift")
    for index, cell in enumerate(candidate_cells):
        _require(cell.get("family") == "F1", f"candidate family drift at {index}")
        _require(cell.get("scope_id") == SCOPE_ID, f"candidate scope drift at {index}")
        _require(cell.get("revision_id") == CANDIDATE_REVISION, f"candidate cell revision drift at {index}")
        _require(cell.get("stage") == "qualification", f"candidate stage drift at {index}")
        _require(cell.get("qualification_claim") == "none", f"candidate claim drift at {index}")
        _require(cell.get("qualified") is False, f"candidate qualification promotion at {index}")

    candidate_gates = candidate.get("preregistered_gates")
    _require(type(candidate_gates) is dict, "candidate gates missing")
    for key in ("event_completion_required", "no_missing_native_fluid_ids", "no_nonfinite_active_values", "qualification_requires_all_cells"):
        _require(candidate_gates.get(key) is True, f"candidate gate drift: {key}")
    _require(candidate_gates.get("saved_chord_crossings_allowed") == 0, "candidate chord gate drift")
    mass = candidate.get("static_mass_check")
    _require(type(mass) is dict and mass.get("cell_count") == 15, "candidate mass denominator drift")
    _require(mass.get("pass") is True and mass.get("mass_rescaling") is False, "candidate mass claim drift")
    _require(type(mass.get("rows")) is list and len(mass["rows"]) == 15, "candidate mass rows drift")
    _require(all(row.get("mass_gate_pass") is True for row in mass["rows"]), "candidate mass gate drift")

    design = payloads["qualification_design"]
    _require(design.get("family") == "F1", "design family drift")
    _require(design.get("scope_id") == SCOPE_ID, "design scope drift")
    _require(design.get("revision_id") == DESIGN_REVISION, "design revision drift")
    _require(design.get("candidate_status") == "pre_registered_unqualified", "design status drift")
    _require(design.get("cell_count") == 15 and type(design.get("cells")) is list, "design denominator drift")
    _require(len(design["cells"]) == 15 and design.get("qualification_claim") == "none", "design cell/claim drift")
    _require(all(cell.get("qualified") is False for cell in design["cells"]), "design qualification promotion")
    _require(design.get("preregistered_gates", {}).get("all_15_cells_required") is True, "design all-cell gate drift")
    _require(design.get("canary_dependency", {}).get("required_before_qualification") is True, "design canary dependency drift")
    _require(design.get("calibration_dependency", {}).get("required_pass") is True, "design calibration dependency drift")

    prepared = payloads["prepared_matrix"]
    _require(prepared.get("revision_id") == DESIGN_REVISION, "prepared revision drift")
    _require(prepared.get("complete") is True and prepared.get("qualification_claim") == "none", "prepared aggregate drift")
    _require(type(prepared.get("cells")) is list and len(prepared["cells"]) == 15, "prepared denominator drift")
    _require(
        all(
            cell.get("index") == index
            and cell.get("preflight_pass") is True
            and cell.get("static_quality_pass") is True
            and cell.get("mass_gate_pass") is True
            for index, cell in enumerate(prepared["cells"])
        ),
        "prepared cell gate drift",
    )

    static_validation = payloads["static_validation"]
    _require(static_validation.get("revision_id") == CANDIDATE_REVISION, "static validation revision drift")
    _require(static_validation.get("static_quality_pass") is True and static_validation.get("preflight_pass") is True, "static validation pass drift")
    _require(static_validation.get("mass_rescaling") is False, "static validation mass-rescaling drift")
    _require(static_validation.get("qualification_claim") == "none", "static validation claim drift")
    _require(static_validation.get("issues") == [], "static validation issues drift")

    jobs = payloads["jobs_manifest"]
    _require(jobs.get("revision_id") == DESIGN_REVISION, "jobs revision drift")
    _require(jobs.get("job_count") == 15 and type(jobs.get("jobs")) is list and len(jobs["jobs"]) == 15, "jobs denominator drift")
    _require(jobs.get("execution_status") == "prepared_only; canary gate required before qualification", "jobs execution status drift")
    _require(jobs.get("qualification_claim") == "none", "jobs qualification claim drift")
    for index, job in enumerate(jobs["jobs"]):
        _require(job.get("index") == index, f"job index drift at {index}")
        outputs = job.get("required_outputs")
        _require(type(outputs) is list and "product/trajectory.h5" in outputs, f"job trajectory contract drift at {index}")
        _require("product/result.json" in outputs and "product/audit.json" in outputs, f"job result contract drift at {index}")

    evaluation = payloads["qualification_evaluation"]
    _require(evaluation.get("family") == "F1" and evaluation.get("scope_id") == SCOPE_ID, "evaluation identity drift")
    _require(evaluation.get("revision_id") == DESIGN_REVISION, "evaluation revision drift")
    _require(evaluation.get("qualified") is False and evaluation.get("T1_numerical") is False, "evaluation T1 drift")
    _require(evaluation.get("T2_macro") is False and evaluation.get("T2_path") is False, "evaluation T2 drift")
    _require(evaluation.get("cells") == [] and type(evaluation.get("missing")) is list and len(evaluation["missing"]) == 15, "evaluation runtime rows drift")
    _require(evaluation.get("failures") == [], "evaluation failure projection drift")
    _require(evaluation.get("promotion_status") == "blocked_until_canary_matrix_and_external_campaign_review", "evaluation promotion drift")
    checks = evaluation.get("checks")
    _require(type(checks) is dict and checks.get("observer_calibrated") is True, "evaluation observer calibration drift")
    for key in ("all_case_hard_mass_event_gates", "canary_gate", "independent_checks", "matrix_complete", "native_output_cadence_gate", "spatial", "time_and_output"):
        _require(checks.get(key) is False, f"evaluation closed gate drift: {key}")
    _require(checks.get("static_matrix") is True, "evaluation static preparation drift")

    calibration = payloads["observer_calibration"]
    _require(calibration.get("family") == "F1" and calibration.get("passed") is True, "observer calibration drift")
    _require(calibration.get("qualification_claim") == "none; manufactured observer calibration", "observer claim drift")

    route = payloads["route_closed"]
    _require(route.get("status") == "route_closed_no_new_hypothesis" and route.get("T1_numerical") is False, "route closure drift")
    _require(route.get("matrix_credit") == 0 and route.get("qualification_claim") == "none", "route credit drift")
    decision = route.get("route_decision")
    _require(decision.get("authorized_now") is False and decision.get("root_review_required_to_reopen") is True, "route authorization drift")
    _require(route.get("new_definition", {}).get("status") == "none_auditable", "new-definition drift")
    core_gate = route.get("core_gate")
    _require(core_gate.get("third_t1_family_established") is False and core_gate.get("qualification_credit_added") == 0, "Core gate drift")
    controls = route.get("execution_controls")
    _require(controls.get("read_only_audit") is True and controls.get("solver_invoked") is False and controls.get("gpu_launched") is False, "route execution drift")
    _require(controls.get("registry_mutation") == 0 and controls.get("ledger_mutation") == 0 and controls.get("T1_denominator_mutation") == 0, "route mutation drift")
    denominator = route.get("denominator_policy")
    _require(denominator.get("existing_failure_denominators_unchanged") is True, "route denominator policy drift")
    _require(denominator.get("same_input_retry") is False and denominator.get("survivor_renormalization") is False, "route retry policy drift")

    canary = payloads["terminal_canary_audit"]
    _require(canary.get("qualified") is False and canary.get("hard_integrity_pass") is False, "terminal canary promotion drift")
    _require(canary.get("event_window_complete") is True and canary.get("requested_horizon_reached") is True, "terminal canary window drift")
    _require(canary.get("endpoint_violation_particle_frames", 0) > 0, "terminal canary negative evidence drift")
    _require(canary.get("qualification_claim", "").startswith("none;"), "terminal canary claim drift")

    h2 = payloads["h2_repair_stop"]
    _require(h2.get("T1_numerical") is False and h2.get("hard_integrity_pass") is False, "H2 promotion drift")
    _require(h2.get("execution_completed") is True and h2.get("native_death_count", 0) > 0, "H2 negative evidence drift")

    g1 = payloads["g1_negative_anchor"]
    _require(g1.get("family") == "F1" and g1.get("qualified") is False and g1.get("T1_numerical") is False, "G1 identity drift")
    _require(g1.get("status") == "completed_scientific_negative_anchor", "G1 status drift")
    _require(g1.get("event_window", {}).get("complete") is True, "G1 event window drift")
    hard = g1.get("hard_integrity")
    _require(hard.get("pass") is False and hard.get("closed_wall_endpoint_particle_frames", 0) > 0, "G1 hard-integrity drift")
    _require(g1.get("matrix_credit") == 0 and g1.get("qualification_claim") == "none", "G1 credit drift")


def _canonical_case_id(value: Any) -> Any:
    """Normalize only the two registered temporal suffix aliases."""

    if not isinstance(value, str):
        return value
    for suffix in ("_internal_time", "_native_output"):
        if value.endswith(suffix):
            return value[: -len(suffix)]
    return value


def _runtime_projection(payloads: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    candidate_cells = payloads["candidate_card"]["cells"]
    design_cells = payloads["qualification_design"]["cells"]
    missing = payloads["qualification_evaluation"]["missing"]
    _require([row.get("index") for row in missing] == list(range(15)), "evaluation missing-index drift")
    _require(
        [_canonical_case_id(row.get("case_id")) for row in missing]
        == [_canonical_case_id(cell.get("case_id")) for cell in candidate_cells],
        "evaluation missing-case drift",
    )
    _require([row.get("case_id") for row in missing] == [cell.get("case_id") for cell in design_cells], "evaluation design-case drift")
    rows: list[dict[str, Any]] = []
    for index, cell in enumerate(design_cells):
        parameter = cell.get("parameter")
        rows.append(
            {
                "index": index,
                "case_id": cell.get("case_id"),
                "design_cell": cell.get("design_cell"),
                "q": parameter.get("q") if isinstance(parameter, Mapping) else None,
                "dp_m": cell.get("dp_m"),
                "preparation_evidence": "prepared_input_only_not_formal_runtime",
                "runtime_status": "missing_runtime_product",
                "formal_run_readiness": "blocked_by_missing_runtime_evidence",
                "source_identity_status": "metadata_only_no_core_source_closure",
                "terminal_evidence_status": "no_formal_terminal_receipt",
                "trajectory_content_opened_by_bridge": False,
                "T1_numerical": False,
                "T2": False,
                "qualification_credit": 0,
                "credit": 0,
            }
        )
    return {
        "registered_rows": 15,
        "prepared_rows": 15,
        "formal_runtime_rows": 0,
        "formal_failed_rows": 0,
        "missing_runtime_rows": 15,
        "formal_evidence_complete": False,
        "fixed_failure_denominator": True,
        "missing_rows_retained": True,
        "rows": rows,
    }


def _blockers(runtime: Mapping[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "code": "fresh_f1_reopen_authorization_missing",
            "severity": "high",
            "detail": "the current F1/F2 route is closed with no auditable new falsifiable F1 Definition; fresh root review is required before any formal run or GPU submission.",
        },
        {
            "code": "formal_runtime_products_missing",
            "severity": "high",
            "detail": "the fixed F1 job manifest remains prepared_only and the qualification evaluation retains all 15 runtime rows as missing; preparation cannot substitute for result, audit, observations, or trajectory products.",
        },
        {
            "code": "source_identity_closure_missing",
            "severity": "high",
            "detail": "source Definition, design digest, and matrix digest are metadata-only bindings; no Core manifest, known_inputs closure, per-cell source hash, or solver/runtime identity is bound for the formal products.",
        },
        {
            "code": "terminal_evidence_missing_or_failed",
            "severity": "high",
            "detail": "no formal 15-cell terminal receipts exist; the retained full-window canary and G1 anchor complete their event windows but fail hard integrity, so neither is a terminal qualification pass.",
        },
        {
            "code": "fixed_15_row_denominator_incomplete",
            "severity": "high",
            "detail": f"the fixed 15-row denominator retains {runtime['missing_runtime_rows']} missing formal runtime rows and zero formal runtime rows; all missing rows must remain visible.",
        },
        {
            "code": "qualification_gates_incomplete",
            "severity": "high",
            "detail": "the current evaluation has canary, matrix, spatial, time/output, cadence, and independent checks closed; T1_numerical remains false and credit remains zero.",
        },
        {
            "code": "material_evidence_absent",
            "severity": "high",
            "detail": "F1 has no independently bound material sidecar, training, or reproduction evidence; preparation and historical negative evidence are not T2 evidence.",
        },
    ]


def build_report(
    root: str | Path = LAB_ROOT,
    *,
    dependency_paths: Mapping[str, str | Path] | None = None,
) -> dict[str, Any]:
    """Build the current bounded F1 readiness projection without execution."""

    root_path = Path(root).resolve()
    payloads, references = _read_dependencies(root_path, dependency_paths)
    _validate_contracts(payloads)
    runtime = _runtime_projection(payloads)
    blockers = _blockers(runtime)
    design = payloads["qualification_design"]
    jobs = payloads["jobs_manifest"]
    evaluation = payloads["qualification_evaluation"]
    canary = payloads["terminal_canary_audit"]
    g1 = payloads["g1_negative_anchor"]
    route = payloads["route_closed"]
    report = {
        "schema": REPORT_SCHEMA,
        "record_id": RECORD_ID,
        "created_at": OBSERVED_AT_UTC,
        "scope_id": SCOPE_ID,
        "status": "blocked_fail_closed",
        "decision": "bounded_f1_formal_run_readiness_evidence_projection",
        "read_policy": dict(READ_POLICY),
        "prohibited_operations": list(PROHIBITED_OPERATIONS),
        "dependencies": references,
        "evidence": {
            "candidate": {
                "scope_id": SCOPE_ID,
                "candidate_revision": CANDIDATE_REVISION,
                "candidate_status": payloads["candidate_card"]["candidate_status"],
                "qualification_only": True,
                "qualified": False,
                "qualification_claim": "none",
                "registered_cells": 15,
            },
            "preparation": {
                "registered_cells": 15,
                "prepared_cells": 15,
                "preflight_pass_cells": 15,
                "mass_gate_pass_cells": 15,
                "static_validation_pass": True,
                "jobs_materialized": False,
                "solver_invoked": False,
                "gpu_invoked": False,
                "evidence_class": "preparation_only_not_formal_runtime_or_T1",
            },
            "runtime": {
                **runtime,
                "jobs_execution_status": jobs["execution_status"],
                "evaluation_missing_rows": len(evaluation["missing"]),
                "evaluation_cells_present": len(evaluation["cells"]),
                "canary_gate": False,
                "matrix_complete": False,
            },
            "source_identity": {
                "source_definition_declared": bool(design.get("fixed_geometry", {}).get("source_definition")),
                "design_sha256_bound": jobs.get("design_sha256") == payloads["prepared_matrix"].get("design_sha256") == evaluation.get("design_sha256"),
                "matrix_sha256_bound": bool(jobs.get("matrix_sha256")) and jobs.get("matrix_sha256") == evaluation.get("matrix_sha256"),
                "formal_core_manifest_bound": False,
                "known_inputs_closure_bound": False,
                "per_cell_source_hash_closure": False,
                "solver_runtime_identity_bound": False,
                "closed": False,
                "artifact_paths_followed": False,
            },
            "terminal_evidence": {
                "formal_terminal_rows": 0,
                "formal_terminal_evidence_complete": False,
                "historical_fullwindow_canary": {
                    "event_window_complete": canary["event_window_complete"],
                    "requested_horizon_reached": canary["requested_horizon_reached"],
                    "hard_integrity_pass": canary["hard_integrity_pass"],
                    "qualified": canary["qualified"],
                    "numerator_eligible": False,
                },
                "historical_g1_anchor": {
                    "event_window_complete": g1["event_window"]["complete"],
                    "hard_integrity_pass": g1["hard_integrity"]["pass"],
                    "qualified": g1["qualified"],
                    "numerator_eligible": False,
                },
                "trajectory_content_opened_by_bridge": False,
                "historical_failure_not_promoted": True,
            },
            "historical_negative_evidence": {
                "fullwindow_canary": {
                    "hard_integrity_pass": canary["hard_integrity_pass"],
                    "event_window_complete": canary["event_window_complete"],
                    "endpoint_violation_particle_frames": canary["endpoint_violation_particle_frames"],
                    "qualification_credit": 0,
                },
                "h2_repair_stop": {
                    "hard_integrity_pass": payloads["h2_repair_stop"]["hard_integrity_pass"],
                    "native_death_count": payloads["h2_repair_stop"]["native_death_count"],
                    "qualification_credit": 0,
                },
                "g1_negative_anchor": {
                    "hard_integrity_pass": g1["hard_integrity"]["pass"],
                    "event_window_complete": g1["event_window"]["complete"],
                    "obstacle_penetration_particle_frames": g1["hard_integrity"]["obstacle_penetration_particle_frames"],
                    "finite_geometry_chord_crossings": g1["hard_integrity"]["finite_geometry_chord_crossings"],
                    "qualification_credit": 0,
                },
                "evidence_class": "historical_negative_only_not_formal_T1",
            },
            "denominator": {
                "registered_rows": 15,
                "prepared_rows": 15,
                "formal_runtime_rows": 0,
                "formal_failed_rows": 0,
                "missing_runtime_rows": 15,
                "fixed_failure_denominator": True,
                "missing_rows_retained": True,
                "historical_negative_anchors_excluded": True,
                "preparation_credit": 0,
                "qualification_credit": 0,
                "survivor_renormalization": False,
            },
            "route_authorization": {
                "status": route["status"],
                "authorized_now": route["route_decision"]["authorized_now"],
                "root_review_required_to_reopen": route["route_decision"]["root_review_required_to_reopen"],
                "new_definition_status": route["new_definition"]["status"],
                "third_t1_family_established": route["core_gate"]["third_t1_family_established"],
            },
            "observer": {
                "calibration_passed": payloads["observer_calibration"]["passed"],
                "calibration_is_not_qualification": True,
                "revision_id": payloads["observer_calibration"]["revision_id"],
            },
        },
        "checks": {
            "candidate_contract_bound": True,
            "fifteen_prepared_input_rows_bound": True,
            "preparation_is_not_formal_runtime": True,
            "fixed_fifteen_row_denominator_bound": True,
            "fifteen_formal_runtime_rows_present": False,
            "formal_source_identity_closed": False,
            "formal_terminal_evidence_complete": False,
            "historical_fullwindow_failure_bound": True,
            "historical_g1_failure_bound": True,
            "historical_failures_excluded_from_numerator": True,
            "fresh_reopen_authorization": False,
            "t1_runtime_evidence_complete": False,
            "t2_material_evidence_present": False,
            "qualification_credit_added": False,
        },
        "blockers": blockers,
        "readiness": {
            "preparation": {
                "required_cells": 15,
                "prepared_cells": 15,
                "pass": True,
            },
            "future_formal_run": {
                "admission_ready": False,
                "runtime_evidence_ready": False,
                "source_identity_ready": False,
                "terminal_evidence_ready": False,
                "formal_run_ready": False,
                "reason": "fresh F1 reopen authorization plus complete source-bound 15-cell runtime and terminal evidence are required",
            },
            "formal_qualification": {
                "T1_numerical": False,
                "T2": False,
                "qualification_credit": 0,
                "credit": 0,
            },
        },
        "authorization": dict(AUTHORIZATION),
        "mutations": dict(MUTATIONS),
        "side_effects": dict(SIDE_EFFECTS),
        "validation": {
            "contract_valid": True,
            "blocked": True,
            "blockers_nonempty": True,
            "preparation_not_promoted": True,
            "historical_failure_not_promoted": True,
            "source_identity_not_promoted": True,
            "terminal_evidence_not_promoted": True,
        },
        "next_safe_action": (
            "先由独立 root review 提出一个超出已关闭 H1/H2/H3/G1 谱系的新、可证伪 F1 Definition 和新 namespace；"
            "获准后再为固定 15 行取得 fresh runtime admission，并逐行绑定 prepared hash、Core manifest、known_inputs、"
            "source/solver/runtime identity、result/audit/observations/trajectory 终态证据。此 bridge 之前不得启动 solver、"
            "worker、native、GPU 或 queue，也不得把 preparation 或历史失败计作 formal/T1/T2。"
        ),
    }
    validate_report(report)
    return report


def validate_report(report: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "schema", "record_id", "created_at", "scope_id", "status", "decision",
        "read_policy", "prohibited_operations", "dependencies", "evidence", "checks",
        "blockers", "readiness", "authorization", "mutations", "side_effects",
        "validation", "next_safe_action",
    }
    if type(report) is not dict or set(report) != required:
        raise ReadinessBridgeError("fail-closed: report fields differ")
    if report["schema"] != REPORT_SCHEMA or report["record_id"] != RECORD_ID:
        raise ReadinessBridgeError("fail-closed: report identity drift")
    if report["created_at"] != OBSERVED_AT_UTC or report["scope_id"] != SCOPE_ID:
        raise ReadinessBridgeError("fail-closed: report scope/time drift")
    if report["status"] != "blocked_fail_closed" or report["decision"] != "bounded_f1_formal_run_readiness_evidence_projection":
        raise ReadinessBridgeError("fail-closed: report status drift")
    if report["read_policy"] != READ_POLICY or report["prohibited_operations"] != list(PROHIBITED_OPERATIONS):
        raise ReadinessBridgeError("fail-closed: read policy drift")
    if report["authorization"] != AUTHORIZATION:
        raise ReadinessBridgeError("fail-closed: authorization promotion detected")
    if report["mutations"] != MUTATIONS or report["side_effects"] != SIDE_EFFECTS:
        raise ReadinessBridgeError("fail-closed: mutation/side-effect boundary drift")

    dependencies = report["dependencies"]
    if set(dependencies) != set(DEPENDENCY_SPECS):
        raise ReadinessBridgeError("fail-closed: dependency inventory drift")
    for key, spec in DEPENDENCY_SPECS.items():
        reference = dependencies[key]
        if reference.get("expected_schema") != spec["schema"] or reference.get("role") != spec["role"]:
            raise ReadinessBridgeError(f"fail-closed: dependency contract drift: {key}")
        if reference.get("path") != spec["path"].as_posix():
            raise ReadinessBridgeError(f"fail-closed: dependency path drift: {key}")
        if reference.get("content_opened") is not True or reference.get("nested_artifact_paths_followed") is not False:
            raise ReadinessBridgeError(f"fail-closed: dependency access boundary drift: {key}")
        digest = reference.get("sha256")
        if type(digest) is not str or len(digest) != 64 or any(char not in SHA256_HEX for char in digest):
            raise ReadinessBridgeError(f"fail-closed: dependency digest drift: {key}")

    checks = report["checks"]
    if type(checks) is not dict or not all(type(value) is bool for value in checks.values()):
        raise ReadinessBridgeError("fail-closed: check projection is not boolean")
    for key in (
        "candidate_contract_bound", "fifteen_prepared_input_rows_bound", "preparation_is_not_formal_runtime",
        "fixed_fifteen_row_denominator_bound", "historical_fullwindow_failure_bound", "historical_g1_failure_bound",
        "historical_failures_excluded_from_numerator",
    ):
        if checks.get(key) is not True:
            raise ReadinessBridgeError(f"fail-closed: positive evidence check lost: {key}")
    for key in (
        "fifteen_formal_runtime_rows_present", "formal_source_identity_closed", "formal_terminal_evidence_complete",
        "fresh_reopen_authorization", "t1_runtime_evidence_complete", "t2_material_evidence_present",
        "qualification_credit_added",
    ):
        if checks.get(key) is not False:
            raise ReadinessBridgeError(f"fail-closed: closed gate promoted: {key}")

    blockers = report["blockers"]
    if type(blockers) is not list or [item.get("code") for item in blockers] != list(BLOCKER_CODES):
        raise ReadinessBridgeError("fail-closed: blocker inventory drift")
    if not all(item.get("severity") == "high" and item.get("detail") for item in blockers):
        raise ReadinessBridgeError("fail-closed: blocker severity/detail drift")

    evidence = report["evidence"]
    preparation = evidence.get("preparation")
    if preparation.get("registered_cells") != 15 or preparation.get("prepared_cells") != 15:
        raise ReadinessBridgeError("fail-closed: preparation denominator drift")
    if preparation.get("evidence_class") != "preparation_only_not_formal_runtime_or_T1":
        raise ReadinessBridgeError("fail-closed: preparation promotion drift")
    runtime = evidence.get("runtime")
    for key, value in (
        ("registered_rows", 15), ("prepared_rows", 15), ("formal_runtime_rows", 0),
        ("formal_failed_rows", 0), ("missing_runtime_rows", 15), ("evaluation_missing_rows", 15),
        ("evaluation_cells_present", 0),
    ):
        if runtime.get(key) != value:
            raise ReadinessBridgeError(f"fail-closed: runtime projection drift: {key}")
    if runtime.get("fixed_failure_denominator") is not True or runtime.get("missing_rows_retained") is not True:
        raise ReadinessBridgeError("fail-closed: denominator retention drift")
    rows = runtime.get("rows")
    if type(rows) is not list or len(rows) != 15 or [row.get("index") for row in rows] != list(range(15)):
        raise ReadinessBridgeError("fail-closed: formal denominator rows drift")
    if any(
        row.get("runtime_status") != "missing_runtime_product"
        or row.get("T1_numerical") is not False
        or row.get("T2") is not False
        or row.get("credit") != 0
        or row.get("trajectory_content_opened_by_bridge") is not False
        for row in rows
    ):
        raise ReadinessBridgeError("fail-closed: case-level promotion or access drift")

    source_identity = evidence.get("source_identity")
    for key in ("formal_core_manifest_bound", "known_inputs_closure_bound", "per_cell_source_hash_closure", "solver_runtime_identity_bound", "closed"):
        if source_identity.get(key) is not False:
            raise ReadinessBridgeError(f"fail-closed: source identity promotion: {key}")
    if source_identity.get("artifact_paths_followed") is not False:
        raise ReadinessBridgeError("fail-closed: source artifact path traversal detected")
    terminal = evidence.get("terminal_evidence")
    if terminal.get("formal_terminal_rows") != 0 or terminal.get("formal_terminal_evidence_complete") is not False:
        raise ReadinessBridgeError("fail-closed: terminal evidence promotion")
    if terminal.get("historical_fullwindow_canary", {}).get("hard_integrity_pass") is not False:
        raise ReadinessBridgeError("fail-closed: historical canary promotion")
    if terminal.get("historical_g1_anchor", {}).get("hard_integrity_pass") is not False:
        raise ReadinessBridgeError("fail-closed: historical G1 promotion")
    if terminal.get("trajectory_content_opened_by_bridge") is not False:
        raise ReadinessBridgeError("fail-closed: terminal trajectory access drift")
    denominator = evidence.get("denominator")
    if denominator.get("registered_rows") != 15 or denominator.get("missing_runtime_rows") != 15:
        raise ReadinessBridgeError("fail-closed: denominator evidence drift")
    if denominator.get("historical_negative_anchors_excluded") is not True or denominator.get("qualification_credit") != 0:
        raise ReadinessBridgeError("fail-closed: historical denominator promotion")

    readiness = report["readiness"]
    if readiness["preparation"] != {"required_cells": 15, "prepared_cells": 15, "pass": True}:
        raise ReadinessBridgeError("fail-closed: preparation readiness drift")
    future = readiness["future_formal_run"]
    for key in ("admission_ready", "runtime_evidence_ready", "source_identity_ready", "terminal_evidence_ready", "formal_run_ready"):
        if future.get(key) is not False:
            raise ReadinessBridgeError(f"fail-closed: formal-run readiness promotion: {key}")
    if readiness["formal_qualification"] != {"T1_numerical": False, "T2": False, "qualification_credit": 0, "credit": 0}:
        raise ReadinessBridgeError("fail-closed: formal qualification drift")
    validation = report["validation"]
    if validation != {
        "contract_valid": True,
        "blocked": True,
        "blockers_nonempty": True,
        "preparation_not_promoted": True,
        "historical_failure_not_promoted": True,
        "source_identity_not_promoted": True,
        "terminal_evidence_not_promoted": True,
    }:
        raise ReadinessBridgeError("fail-closed: validation boundary drift")
    if not isinstance(report["next_safe_action"], str) or not report["next_safe_action"]:
        raise ReadinessBridgeError("fail-closed: next safe action missing")
    return dict(report)


def _write_immutable(path: str | Path, payload: bytes) -> Path:
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(os.fspath(target), flags, 0o644)
    except FileExistsError:
        raise
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
    finally:
        os.close(descriptor)
    return target


def _zh_report(report: Mapping[str, Any]) -> str:
    blocker_lines = "\n".join(f"- `{item['code']}`：{item['detail']}" for item in report["blockers"])
    preparation = report["evidence"]["preparation"]
    runtime = report["evidence"]["runtime"]
    source = report["evidence"]["source_identity"]
    terminal = report["evidence"]["terminal_evidence"]
    return f"""# F1 formal-run readiness/evidence bridge V1

状态：`{report['status']}`。

本 bridge 只读取固定 allow-list 的 bounded JSON，并把 F1 的 15 行 preparation、formal job metadata、qualification evaluation、source identity 元数据和历史 negative evidence 串成一个只读投影。不打开或统计生产 HDF5、BI4、trajectory，不跟随 JSON 内嵌 artifact path，不启动或停止 solver、worker、native、GPU、queue，也不修改 registry、ledger、denominator、gate、PLAN 或 completion。

## 当前已经绑定

- F1 H1 candidate/design/prepared matrix：`{preparation['prepared_cells']}/{preparation['registered_cells']}` 行 preflight/static/mass preparation 通过；这仍然是 preparation-only，不是 formal runtime 或 T1。
- 固定 formal 分母：15 行；当前 formal runtime rows=`{runtime['formal_runtime_rows']}`，missing=`{runtime['missing_runtime_rows']}`，缺失行全部保留。
- source metadata：source Definition、design digest、matrix digest 已记录，但 Core manifest、known_inputs、每行 source hash 和 solver/runtime identity 尚未闭合（`closed={str(source['closed']).lower()}`）。
- 历史 terminal/negative evidence：full-window canary 的 event window 完成但 hard-integrity 失败；G1 anchor 同样 event complete 但 hard-integrity 失败；两者都排除 numerator。

## 未闭合 blocker

{blocker_lines}

因此：prepared={preparation['prepared_cells']}/{preparation['registered_cells']}，formal runtime={runtime['formal_runtime_rows']}/{runtime['registered_rows']}，terminal rows={terminal['formal_terminal_rows']}；`formal_run_ready=false`、`T1=false`、`T2=false`、credit=0。不能把 preparation、observer calibration 或历史失败当成 formal/T1/T2 成功。

下一步必须先获得一个超出 H1/H2/H3/G1 已关闭谱系的新 F1 物理 Definition、独立 root review 和新 namespace；之后才能补齐 source-bound 15-cell runtime/terminal evidence，并重新运行本 bridge。

机器报告：`F1-FORMAL-RUN-READINESS-EVIDENCE-BRIDGE-V1-2026-09-28.json`。
"""


def write_outputs(report: Mapping[str, Any], output: str | Path, zh_output: str | Path) -> tuple[Path, Path]:
    validate_report(report)
    payload = (json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    zh_payload = _zh_report(report).encode("utf-8")
    return _write_immutable(output, payload), _write_immutable(zh_output, zh_payload)


def verify_report(path: str | Path = DEFAULT_REPORT) -> dict[str, Any]:
    value, _reference = _read_bounded_json(LAB_ROOT, path, role="checked-in F1 bridge report")
    validate_report(value)
    expected = build_report()
    if value != expected:
        raise ReadinessBridgeError("fail-closed: checked-in F1 bridge report differs from current bounded evidence")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=LAB_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--zh-output", type=Path, default=DEFAULT_ZH_REPORT)
    args = parser.parse_args(argv)
    report = build_report(args.root)
    write_outputs(report, args.output, args.zh_output)
    print(json.dumps({"status": report["status"], "report": str(args.output)}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
