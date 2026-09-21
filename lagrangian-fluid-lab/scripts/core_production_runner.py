#!/usr/bin/env python3
"""Prepare an evidence-gated F4 production proposal.

This module is intentionally a proposal builder.  It registers the new
resting-pool scalar scope in memory, verifies a qualification receipt and its
referenced evidence, asks :mod:`scripts.core_production` for the next batch,
and (when a batch is admissible) prepares CFD inputs and worker specifications
under a new scope-specific directory.  It never submits a job or updates a
central registry.

The F4 resting-pool repair is a physical scope change.  The old floating-pool
scope and its qualification/production records are therefore rejected by
identity checks throughout this file.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Callable, Mapping


# The source tree owns imports.  ``lab_root`` below is only the asset root
# supplied to GenCase/worker specs; it must not replace this frozen source
# root on sys.path.
SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from scripts import core_cfd
from scripts.core_production import next_batch, register_scope


SCHEMA = "core.production.proposal.v1"
FAMILY = "F4"
SCOPE_ID = "F4_drop_resting_pool_x_v2"
REVISION_ID = "F4_resting_pool_13plus2_v2"
RECIPE_ID = "F4_resting_pool_mdbc_native_v2"
LAMINAR_SCOPE_ID = "F4_drop_resting_pool_laminar_nu1e6_x_v1"
SCOPE_PROTOCOLS = {
    SCOPE_ID: {"revision_id": REVISION_ID, "recipe_id": RECIPE_ID,
               "job_prefix": "f4-resting-pool-production"},
    LAMINAR_SCOPE_ID: {
        "revision_id": "F4_resting_pool_laminar_13plus2_v1",
        "recipe_id": "F4_resting_pool_laminar_nu1e6_mdbc_v1",
        "job_prefix": "f4-laminar-production",
        "physical_kinematic_viscosity_m2_s": 1e-6,
        "viscosity_formulation": "laminar"},
}
PARAMETER_NAME = "drop_left_x_m"
PRODUCTION_DP_M = 0.0075
QUALIFICATION_MATRIX_RELATIVE = Path(
    "campaigns/core-v1/cfd/prepared/F4_resting_pool_qualification_v2"
)
PRODUCTION_PREPARED_RELATIVE = Path(
    "campaigns/core-v1/cfd/prepared/F4_resting_pool_production_v2"
)
PROPOSAL_RELATIVE = Path(
    "campaigns/core-v1/cfd/f4-resting-pool-production-proposal.json"
)


class VerificationError(ValueError):
    """A source or receipt failed a fail-closed identity/hash check."""


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def _load(path: Path) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.exists():
        raise VerificationError(f"required JSON is missing: {path}")
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise VerificationError(f"invalid JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise VerificationError(f"JSON object required: {path}")
    return value


def _resolve_reference(value: Any, *, base: Path, source_root: Path) -> Path:
    if not isinstance(value, str) or not value:
        raise VerificationError("evidence reference path is missing")
    path = Path(value).expanduser()
    if not path.is_absolute():
        # Runtime receipts normally carry absolute paths.  Relative paths are
        # interpreted against the matrix's parent first, then the asset root.
        candidate = (base / path).resolve()
        path = candidate if candidate.exists() else (source_root / path).resolve()
    return path.resolve()


def _verify_reference(ref: Mapping[str, Any], *, base: Path, source_root: Path, label: str) -> tuple[Path, str]:
    path = _resolve_reference(ref.get("path"), base=base, source_root=source_root)
    expected = ref.get("sha256")
    if not isinstance(expected, str) or len(expected) != 64:
        raise VerificationError(f"{label} has no sha256 reference: {path}")
    if not path.exists():
        raise VerificationError(f"{label} evidence is missing: {path}")
    actual = _sha256(path)
    if actual != expected:
        raise VerificationError(f"{label} hash mismatch: {path}")
    return path, actual


def _new_scope_guard(scope_id: Any) -> None:
    if scope_id not in SCOPE_PROTOCOLS:
        raise VerificationError(
            f"scope identity is {scope_id!r}; only explicitly registered resting-pool scopes may enter production"
        )
    if "drop_pool_x_v1" in str(scope_id) or scope_id == "F4_drop_pool_x_v1":
        raise VerificationError("old floating-pool F4 scope cannot be reused")


def _matrix_paths(matrix_root: Path) -> tuple[Path, Path, Path]:
    matrix_root = Path(matrix_root).resolve()
    return matrix_root / "design.json", matrix_root / "prepared-matrix.json", matrix_root / "static-validation.json"


def inspect_qualification_matrix(matrix_root: Path) -> dict[str, Any]:
    """Verify the immutable v2 matrix and return its source hashes.

    The static report is checked against both source files, and every prepared
    row is checked again for scope, geometry, native mass policy, and preflight
    status.  This prevents a mutable prepared file from being hidden behind an
    unchanged matrix manifest hash.
    """
    design_path, matrix_path, static_path = _matrix_paths(matrix_root)
    design = _load(design_path)
    matrix = _load(matrix_path)
    static = _load(static_path)
    _new_scope_guard(design.get("scope_id"))
    protocol = SCOPE_PROTOCOLS[design["scope_id"]]
    if design.get("revision_id") != protocol["revision_id"] or design.get("schema") != "core.cfd.v1":
        raise VerificationError("qualification matrix design identity/schema mismatch")
    if matrix.get("schema") != "core.cfd.v1" or matrix.get("qualification_claim") != "none":
        raise VerificationError("qualification prepared matrix is not a claim-free v2 matrix")
    if not matrix.get("complete") or len(matrix.get("cells", [])) != 15:
        raise VerificationError("qualification matrix is not the complete registered 13+2 denominator")
    design_sha = _sha256(design_path)
    matrix_sha = _sha256(matrix_path)
    if matrix.get("design_sha256") != design_sha:
        raise VerificationError("prepared matrix design hash mismatch")
    if static.get("schema") != "core.cfd.static.v1":
        raise VerificationError("static validation schema mismatch")
    if static.get("design_sha256") != design_sha or static.get("prepared_matrix_sha256") != matrix_sha:
        raise VerificationError("static validation source hash mismatch")
    if static.get("static_quality_pass") is not True or static.get("preflight_pass") is not True:
        raise VerificationError("qualification matrix static/preflight gate is not passing")
    if static.get("qualification_claim") != "none" or static.get("mass_rescaling") is not False:
        raise VerificationError("qualification matrix mass/claim policy is not frozen")
    if design.get("prior_scope_qualification_inherited") is not False:
        raise VerificationError("v2 design does not explicitly reject inherited qualification")
    if design.get("continuum_geometry", {}).get("pool") != {
        "low": [0.0, 0.0, 0.0], "size": [1.2, 0.4, 0.18]
    }:
        raise VerificationError("qualification design is not the resting-pool geometry")

    rows = matrix["cells"]
    case_ids: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise VerificationError("prepared matrix row is not an object")
        prepared_path = _resolve_reference(row.get("prepared"), base=Path(matrix_root).parent, source_root=SOURCE_ROOT)
        prepared = _load(prepared_path)
        cfg = prepared.get("config", {})
        _new_scope_guard(cfg.get("scope_id"))
        if cfg.get("scope_id") != design["scope_id"]:
            raise VerificationError(f"qualification row belongs to another scope: {prepared_path}")
        if design["scope_id"] == LAMINAR_SCOPE_ID and any(
            cfg.get(key) != protocol[key] for key in (
                "physical_kinematic_viscosity_m2_s", "viscosity_formulation")):
            raise VerificationError(f"qualification row physical viscosity mismatch: {prepared_path}")
        if cfg.get("family") != FAMILY or cfg.get("stage") != "qualification":
            raise VerificationError(f"qualification row has wrong family/stage: {prepared_path}")
        if cfg.get("case_id") != row.get("case_id") or cfg.get("case_id") in case_ids:
            raise VerificationError(f"qualification row identity mismatch: {prepared_path}")
        case_ids.add(str(cfg.get("case_id")))
        if prepared.get("preflight_pass") is not True:
            raise VerificationError(f"qualification row preflight failed: {prepared_path}")
        if prepared.get("mass_preflight", {}).get("mass_gate_pass") is not True:
            raise VerificationError(f"qualification row mass gate failed: {prepared_path}")
        if cfg.get("pool") != {"low": [0.0, 0.0, 0.0], "size": [1.2, 0.4, 0.18], "mkfluid": 0}:
            raise VerificationError(f"qualification row uses non-resting pool: {prepared_path}")
    if len(case_ids) != 15:
        raise VerificationError("qualification matrix case denominator is not 15 unique rows")
    return {
        "root": str(Path(matrix_root).resolve()),
        "design": design,
        "matrix": matrix,
        "static": static,
        "design_path": str(design_path.resolve()),
        "matrix_path": str(matrix_path.resolve()),
        "static_path": str(static_path.resolve()),
        "design_sha256": design_sha,
        "matrix_sha256": matrix_sha,
        "static_sha256": _sha256(static_path),
        "case_ids": sorted(case_ids),
    }


def production_design(matrix: Mapping[str, Any]) -> dict[str, Any]:
    """Register the fresh 32-point scalar production scope in memory."""
    design = matrix["design"]
    _new_scope_guard(design.get("scope_id"))
    cells = design.get("cells", [])
    values = [float(cell["parameter"]["value"]) for cell in cells]
    ranges = {tuple(float(x) for x in cell["parameter"]["candidate_range"]) for cell in cells}
    if len(ranges) != 1 or len(values) != 15:
        raise VerificationError("qualification scalar range/denominator is not frozen")
    lower, upper = next(iter(ranges))
    qualification_points = sorted(set(values))
    if len(qualification_points) != 5:
        raise VerificationError("expected five physical qualification points")
    registered = register_scope(
        FAMILY, design["scope_id"], PARAMETER_NAME, lower, upper, qualification_points
    )
    for row in registered["cases"]:
        row["parameter_range"] = [lower, upper]
    registered.update(
        {
            "revision_id": SCOPE_PROTOCOLS[design["scope_id"]]["revision_id"],
            "recipe_id": SCOPE_PROTOCOLS[design["scope_id"]]["recipe_id"],
            "recipe": design.get("recipe"),
            "production_resolution_m": PRODUCTION_DP_M,
            "continuum_geometry": deepcopy(design.get("continuum_geometry")),
            "registered_window": deepcopy(design.get("registered_window")),
            "qualification_design_sha256": matrix["design_sha256"],
            "qualification_matrix_sha256": matrix["matrix_sha256"],
            "qualification_static_sha256": matrix["static_sha256"],
            "qualification_points_source": "15-cell v2 design physical drop_left_x_m values",
            "qualification_inheritance": False,
        }
    )
    return registered


def _verify_case_evidence(
    receipt: Mapping[str, Any], *, matrix: Mapping[str, Any], matrix_root: Path, source_root: Path
) -> None:
    """Verify hashes for all receipt evidence that is present.

    An incomplete receipt may legitimately contain only completed cells.  A
    receipt that claims T1 completion must contain and verify every cell.
    """
    expected = {str(x) for x in matrix["case_ids"]}
    cells = receipt.get("cells", [])
    if not isinstance(cells, list):
        raise VerificationError("qualification receipt cells must be a list")
    seen: set[str] = set()
    for cell in cells:
        if not isinstance(cell, dict):
            raise VerificationError("qualification receipt cell is not an object")
        case_id = cell.get("case_id")
        if case_id not in expected or case_id in seen:
            raise VerificationError(f"qualification receipt has unknown/duplicate case: {case_id}")
        seen.add(case_id)
        for field in ("audit", "observations"):
            ref = cell.get(field)
            if not isinstance(ref, dict):
                raise VerificationError(f"qualification receipt cell {case_id} lacks {field} reference")
            path, _ = _verify_reference(ref, base=matrix_root, source_root=source_root, label=f"{case_id} {field}")
            evidence = _load(path)
            if field == "audit":
                # Qualification products are emitted by core_cfd and carry
                # core.cfd.v1.  core.case_audit.v1 is also accepted for a
                # later normalized receipt, while identity remains required.
                if evidence.get("schema") not in {"core.cfd.v1", "core.case_audit.v1"} or evidence.get("case_id") != case_id:
                    raise VerificationError(f"qualification audit identity mismatch: {path}")
                if receipt.get("T1_numerical") is True and not all(
                    evidence.get(key) is True for key in
                    ("hard_integrity_pass", "source_mass_gate_pass", "event_window_complete")
                ):
                    raise VerificationError(f"T1 receipt contradicts underlying case gates: {path}")
    calibration = receipt.get("observation_calibration")
    if isinstance(calibration, dict) and calibration.get("path") is not None:
        path, _ = _verify_reference(
            calibration, base=matrix_root, source_root=source_root, label="observation calibration"
        )
        calibration_doc = _load(path)
        if calibration_doc.get("schema") != "core.observation_calibration.v1":
            raise VerificationError(f"observation calibration schema mismatch: {path}")
        if receipt.get("T1_numerical") is True and calibration_doc.get("passed") is not True:
            raise VerificationError("T1 receipt claims completion with a failed observation calibration")
    elif receipt.get("T1_numerical") is True:
        raise VerificationError("T1 receipt claims completion without observation calibration evidence")
    if receipt.get("T1_numerical") is True:
        checks = receipt.get("checks", {})
        required = ("static_matrix", "matrix_complete", "all_case_hard_mass_event_gates",
                    "spatial", "independent_checks", "time_and_output", "observation_calibrated")
        if not isinstance(checks, dict) or not all(checks.get(key) is True for key in required):
            raise VerificationError("T1 receipt lacks passing scientific gate matrix")
        if receipt.get("matrix_complete") is not True or len(seen) != 15:
            raise VerificationError("T1 receipt claims completion without the full 15-cell evidence set")
        if receipt.get("missing") or receipt.get("failures"):
            raise VerificationError("T1 receipt claims completion while retaining missing/failed cells")


def verify_qualification_receipt(
    receipt_path: Path, matrix: Mapping[str, Any], *, source_root: Path = SOURCE_ROOT
) -> dict[str, Any]:
    """Load a v2 qualification receipt only after source/evidence hash checks."""
    path = Path(receipt_path).resolve()
    receipt = _load(path)
    _new_scope_guard(receipt.get("scope_id"))
    if receipt.get("scope_id") != matrix["design"]["scope_id"]:
        raise VerificationError("qualification receipt belongs to another registered scope")
    if receipt.get("schema") != "core.qualification.v1" or receipt.get("family") != FAMILY:
        raise VerificationError("qualification receipt schema/family mismatch")
    if receipt.get("design_sha256") != matrix["design_sha256"]:
        raise VerificationError("qualification receipt design hash does not match v2 matrix")
    for key in ("prepared_matrix_sha256", "matrix_sha256"):
        if key in receipt and receipt.get(key) != matrix["matrix_sha256"]:
            raise VerificationError("qualification receipt matrix hash does not match v2 matrix")
    _verify_case_evidence(
        receipt,
        matrix=matrix,
        matrix_root=Path(matrix["root"]),
        source_root=Path(source_root).resolve(),
    )
    checks = receipt.get("checks")
    if checks is not None and not isinstance(checks, dict):
        raise VerificationError("qualification receipt checks must be an object")
    return {
        **deepcopy(receipt),
        "_receipt_path": str(path),
        "_receipt_sha256": _sha256(path),
        "_matrix_sha256": matrix["matrix_sha256"],
        "_hash_verified": True,
    }


def _empty_qualification(scope_id: str = SCOPE_ID) -> dict[str, Any]:
    return {
        "schema": "core.qualification.v1",
        "family": FAMILY,
        "scope_id": scope_id,
        "T1_numerical": False,
        "matrix_complete": False,
        "_hash_verified": False,
    }


def load_production_audits(path: Path | None, *, design: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Load executed, content-bound audits; inline success flags are not evidence.

    Each manifest row references execution, prepared, audit and trajectory files
    with their SHA256.  The worker receipt must bind all three product files.
    Failed scientific audits are retained so the scope pauses with its original
    denominator, while incomplete or inconsistent evidence is rejected.
    """
    if path is None:
        return {}
    document = _load(Path(path))
    if "audits" in document:
        raw = document["audits"]
        if isinstance(raw, list):
            if any(not isinstance(row, dict) for row in raw):
                raise VerificationError("production audit row must be an object")
            keys = [str(row.get("case_id")) for row in raw]
            if len(set(keys)) != len(keys):
                raise VerificationError("duplicate production audit case")
            raw = dict(zip(keys, raw))
        if not isinstance(raw, dict):
            raise VerificationError("production audit manifest audits must be a mapping/list")
    else:
        raw = document
    for key in ("family", "scope_id"):
        if key in document:
            expected = design[key]
            if document.get(key) != expected:
                raise VerificationError(f"production audit manifest {key} belongs to another scope")
    cases = {row["case_id"]: row for row in design["cases"]}
    result: dict[str, dict[str, Any]] = {}
    for key, value in raw.items():
        if key not in cases or not isinstance(value, dict):
            raise VerificationError(f"production audit is outside the fixed 32-case denominator: {key}")
        if value.get("case_id") != key:
            raise VerificationError(f"production audit key/identity mismatch: {key}")
        refs = {}
        for label in ("execution", "prepared", "audit", "trajectory"):
            ref = value.get(label)
            if not isinstance(ref, dict):
                raise VerificationError(f"production {key} requires {label} evidence")
            refs[label] = _verify_reference(
                ref, base=Path(path).resolve().parent, source_root=SOURCE_ROOT,
                label=f"production {key} {label}")
        execution = _load(refs["execution"][0])
        if (execution.get("schema") != "core.execution_receipt.v1"
                or execution.get("execution_status") != "succeeded"
                or execution.get("returncode") != 0
                or execution.get("timeout") is not False
                or execution.get("missing_outputs") != []):
            raise VerificationError(f"production execution is incomplete: {key}")
        artifacts = execution.get("artifact_index", [])
        attempt_root = refs["execution"][0].parent
        for label in ("prepared", "audit", "trajectory"):
            target, expected = refs[label]
            matches = [entry for entry in artifacts
                       if isinstance(entry, dict)
                       and isinstance(entry.get("path"), str)
                       and (attempt_root / entry["path"]).resolve() == target
                       and entry.get("sha256") == expected]
            if len(matches) != 1:
                raise VerificationError(f"production {label} is not bound to execution: {key}")
        prepared = _load(refs["prepared"][0])
        cfg = prepared.get("config", {})
        if (cfg.get("case_id") != key or cfg.get("family") != design["family"]
                or cfg.get("scope_id") != design["scope_id"]
                or cfg.get("stage") != "production"
                or cfg.get("qualification_only") is not False):
            raise VerificationError(f"production lineage/scope mismatch: {key}")
        registered = cases[key]
        if (cfg.get("parameter", {}).get("value") != registered.get("parameter")
                or cfg.get("split") != registered.get("split")
                or cfg.get("production_index") != registered.get("index")
                or cfg.get("recipe_id") != design.get("recipe_id")
                or cfg.get("lineage_group_id") != key
                or cfg.get("physical_case_id") != key):
            raise VerificationError(f"production parameter/split/recipe binding mismatch: {key}")
        protocol = SCOPE_PROTOCOLS.get(design["scope_id"], {})
        if any(cfg.get(field) != protocol[field] for field in (
                "physical_kinematic_viscosity_m2_s", "viscosity_formulation")
                if field in protocol):
            raise VerificationError(f"production physical viscosity binding mismatch: {key}")
        audit = _load(refs["audit"][0])
        if audit.get("case_id") != key or audit.get("schema") != core_cfd.SCHEMA:
            raise VerificationError(f"production native audit identity mismatch: {key}")
        structural = audit.get("structural", {})
        structural_path = Path(structural.get("path", ""))
        if structural_path.resolve() != refs["trajectory"][0]:
            raise VerificationError(f"production audit refers to another trajectory: {key}")
        # core_cfd.audit scans every saved frame and the entire particle axis.
        # Derive admission from that actual report, never the manifest's flags.
        result[key] = {
            "schema": "core.case_audit.v1", "case_id": key,
            "hard_integrity_pass": all(audit.get(field) is True for field in (
                "hard_integrity_pass", "source_mass_gate_pass",
                "event_window_complete", "requested_horizon_reached")),
            "full_temporal_scan": structural.get("full_scan") is True,
            "full_particle_axis": structural.get("full_scan") is True,
            "evidence": {label: {"path": str(ref[0]), "sha256": ref[1]}
                         for label, ref in refs.items()},
        }
    return result


def production_case_config(row: Mapping[str, Any], matrix: Mapping[str, Any]) -> dict[str, Any]:
    """Build one CFD config for a registered v2 scalar point."""
    scope_id = matrix["design"]["scope_id"]
    _new_scope_guard(scope_id)
    protocol = SCOPE_PROTOCOLS[scope_id]
    if row.get("family") != FAMILY or row.get("scope_id") != scope_id:
        raise VerificationError("production row does not belong to the fresh F4 resting-pool scope")
    if row.get("qualification_only") is not False or row.get("stage") != "production":
        raise VerificationError("production row has qualification-only/stage contamination")
    parameter = float(row["parameter"])
    lower, upper = (float(x) for x in row["parameter_range"])
    q = (parameter - lower) / (upper - lower)
    config = core_cfd.f4_config(PRODUCTION_DP_M, q=.5, recipe="mdbc_native", stage="development")
    config.update(
        {
            "scope_id": scope_id,
            "revision_id": protocol["revision_id"],
            "case_id": row["case_id"],
            "recipe_id": protocol["recipe_id"],
            "stage": "production",
            "qualification_claim": "none",
            "qualified": False,
            "qualification_only": False,
            "parameter": {
                "name": PARAMETER_NAME,
                "value": parameter,
                "q": q,
                "candidate_range": [lower, upper],
            },
            "pool": {"low": [0.0, 0.0, 0.0], "size": [1.2, 0.4, 0.18], "mkfluid": 0},
            "drop": {
                "low": [parameter, 0.12, 0.4],
                "size": [0.26, 0.16, 0.14],
                "mkfluid": 1,
            },
            "time_max_s": float(matrix["design"]["registered_window"]["initial_time_max_s"]),
            "output_interval_s": float(matrix["design"]["registered_window"]["output_interval_s"]),
            "design_cell": "production",
            "split": row["split"],
            "production_index": int(row["index"]),
            "first_batch": bool(row["first_batch"]),
            "physical_case_id": f"{scope_id}_DEV_{int(row['index']):02d}",
            "lineage_group_id": f"{scope_id}_DEV_{int(row['index']):02d}",
            "horizon": core_cfd.event_horizon(
                {"low": [0.0, 0.0, 0.0], "size": [1.2, 0.4, 0.18]},
                {"low": [parameter, 0.12, 0.4], "size": [0.26, 0.16, 0.14]},
            ),
        }
    )
    config["source_scope_qualification_inherited"] = False
    for key in ("physical_kinematic_viscosity_m2_s", "viscosity_formulation"):
        if key in protocol:
            config[key] = protocol[key]
    config["production_resolution_m"] = PRODUCTION_DP_M
    return config


def _production_job_spec(
    prepared_path: Path,
    lab_root: Path,
    row: Mapping[str, Any],
    *,
    batch_status: str,
    qualification: Mapping[str, Any],
    production_design_sha256: str,
) -> dict[str, Any]:
    prepared_path = Path(prepared_path).resolve()
    prepared = _load(prepared_path)
    config = prepared.get("config", {})
    solver = Path(prepared.get("solver_binary", "")).resolve()
    if not solver.exists():
        raise VerificationError(f"prepared production case solver is missing: {solver}")
    protocol = SCOPE_PROTOCOLS[row["scope_id"]]
    job_id = f"{protocol['job_prefix']}-dev-{int(row['index']):02d}"
    python = Path(lab_root).resolve() / ".venv/bin/python"
    return {
        "schema": "core.cfd.job.v1",
        "job_id": job_id,
        "logical_id": job_id,
        "attempt_role": "production",
        "category": "production_first_8" if batch_status == "first_8" else "production_remaining_24",
        "host": "ada",
        "source_lab": str(Path(lab_root).resolve()),
        "cwd": str(Path(lab_root).resolve()),
        "argv": [
            str(python),
            # Keep this as the live lab path so core_runtime.freeze_job can
            # replace it with the hash-verified source snapshot before a
            # worker starts.  Imports in this runner itself still come from
            # SOURCE_ROOT above.
            str((Path(lab_root).resolve() / "scripts/core_cfd.py").resolve()),
            "--lab-root",
            str(Path(lab_root).resolve()),
            "run",
            "--prepared",
            str(prepared_path),
            "--output",
            "{attempt_dir}/product",
        ],
        "required_outputs": [
            "product/result.json",
            "product/trajectory.h5",
            "product/audit.json",
            "product/observations.json",
        ],
        "resources": core_cfd._resource_estimate(PRODUCTION_DP_M, canary=False),
        "timeout_seconds": 18000,
        "depends_on": [],
        "qualification_claim": "none; production evidence pending",
        "worker_contract": "core_runtime worker; scheduler supplies one CUDA UUID and solver uses -gpu:0",
        "input_files": [
            {"path": str(prepared_path), "sha256": _sha256(prepared_path)},
            {"path": str(solver), "sha256": _sha256(solver)},
        ],
        "prepared_case_id": config.get("case_id"),
        "registered_window_s": config.get("time_max_s"),
        "scope_id": row["scope_id"],
        "revision_id": protocol["revision_id"],
        "family": FAMILY,
        "production_index": int(row["index"]),
        "registered_parameter_name": PARAMETER_NAME,
        "registered_parameter": float(row["parameter"]),
        "split": row["split"],
        "first_batch": bool(row["first_batch"]),
        "batch_status": batch_status,
        "qualification_receipt_sha256": qualification.get("_receipt_sha256"),
        "qualification_design_sha256": qualification.get("design_sha256"),
        "qualification_matrix_sha256": qualification.get("_matrix_sha256"),
        "production_design_sha256": production_design_sha256,
    }


def _batch_decision(
    registered: Mapping[str, Any], qualification: Mapping[str, Any], audits: Mapping[str, Any]
) -> dict[str, Any]:
    if qualification.get("_hash_verified") is not True:
        return {
            "status": "scope_review_required",
            "ready": [],
            "failed": ["qualification:receipt_hash_unverified"],
            "missing": [row["case_id"] for row in registered["cases"]],
            "registered_denominator": 32,
        }
    decision = next_batch(dict(registered), dict(qualification), dict(audits))
    decision.setdefault("registered_denominator", 32)
    if qualification.get("matrix_complete") is True and qualification.get("T1_numerical") is not True:
        # ``core_production.next_batch`` treats every non-T1 receipt as
        # awaiting.  Once the complete matrix has a negative T1 result, the
        # scope is failed and must retain its denominator for review.
        decision.update(
            status="scope_review_required",
            ready=[],
            failed=["qualification:T1_numerical"],
            missing=decision.get("missing", []),
        )
    return decision


def prepare_batch(
    ready_rows: list[Mapping[str, Any]],
    *,
    matrix: Mapping[str, Any],
    lab_root: Path,
    prepared_root: Path,
    batch_status: str,
    qualification: Mapping[str, Any],
    production_design_sha256: str,
    prepare_fn: Callable[[dict[str, Any], Path, Path], dict[str, Any]] = core_cfd.prepare,
) -> dict[str, Any]:
    """Prepare the selected cases and write proposal-local job specs.

    A preparation exception records a failed scope and stops the batch.  No
    job is returned as submit-ready after a partial preparation failure.
    """
    prepared_root = Path(prepared_root).resolve()
    prepared_root.mkdir(parents=True, exist_ok=True)
    prepared_rows: list[dict[str, Any]] = []
    try:
        for row in ready_rows:
            index = int(row["index"])
            case_dir = prepared_root / f"DEV_{index:02d}"
            config = production_case_config(row, matrix)
            if case_dir.exists() and any(case_dir.iterdir()):
                prepared = _load(case_dir / "prepared.json")
                if prepared.get("config") != config or not prepared.get("inputs"):
                    raise VerificationError(f"existing production preparation differs: {case_dir}")
                for name, expected in prepared["inputs"].items():
                    if _sha256(Path(name)) != expected:
                        raise VerificationError(f"existing production input changed: {name}")
            else:
                prepared = prepare_fn(config, Path(lab_root).resolve(), case_dir)
            if prepared.get("preflight_pass") is not True:
                raise VerificationError(f"production static preflight failed: {case_dir}")
            actual = prepared.get("config", {})
            if (
                actual.get("scope_id") != matrix["design"]["scope_id"]
                or actual.get("stage") != "production"
                or actual.get("qualification_only") is not False
                or actual.get("pool") != config["pool"]
                or actual.get("case_id") != row["case_id"]
            ):
                raise VerificationError(f"prepared production case identity/geometry mismatch: {case_dir}")
            prepared_path = case_dir / "prepared.json"
            if not prepared_path.exists():
                raise VerificationError(f"prepared production record is missing: {prepared_path}")
            prepared_rows.append(
                {
                    "index": index,
                    "case_id": row["case_id"],
                    "parameter": row["parameter"],
                    "split": row["split"],
                    "prepared": str(prepared_path.resolve()),
                    "prepared_sha256": _sha256(prepared_path),
                }
            )
    except Exception as exc:
        return {
            "status": "scope_review_required",
            "prepared": prepared_rows,
            "ready": [],
            "failed": [f"preparation:{type(exc).__name__}:{exc}"],
            "registered_denominator": 32,
            "batch_status": batch_status,
        }

    protocol = SCOPE_PROTOCOLS[matrix["design"]["scope_id"]]
    jobs_dir = prepared_root.parent / (protocol["job_prefix"] + "-jobs")
    jobs_dir.mkdir(parents=True, exist_ok=True)
    jobs: list[dict[str, Any]] = []
    try:
        for row, prepared_row in zip(ready_rows, prepared_rows):
            spec = _production_job_spec(
                Path(prepared_row["prepared"]),
                Path(lab_root),
                row,
                batch_status=batch_status,
                qualification=qualification,
                production_design_sha256=production_design_sha256,
            )
            path = jobs_dir / f"{spec['job_id']}.json"
            if path.exists():
                if _load(path) != spec:
                    raise VerificationError(f"production job proposal changed: {path}")
            else:
                _write_json(path, spec)
            jobs.append({"job_id": spec["job_id"], "path": str(path.resolve()), "sha256": _sha256(path)})
    except Exception as exc:
        return {
            "status": "scope_review_required",
            "prepared": prepared_rows,
            "ready": [],
            "jobs": [],
            "failed": [f"job_spec:{type(exc).__name__}:{exc}"],
            "registered_denominator": 32,
            "batch_status": batch_status,
        }
    manifest = {
        "schema": "core.production.batch.v1",
        "scope_id": matrix["design"]["scope_id"],
        "revision_id": protocol["revision_id"],
        "batch_status": batch_status,
        "case_count": len(prepared_rows),
        "registered_denominator": 32,
        "prepared": prepared_rows,
        "jobs": jobs,
        "execution_status": "prepared_only",
        "central_ledger_mutation": 0,
    }
    manifest_path = prepared_root / f"{batch_status}.manifest.json"
    _write_json(manifest_path, manifest)
    return {"status": batch_status, "prepared": prepared_rows, "jobs": jobs, "manifest": str(manifest_path.resolve()), "ready": [x["case_id"] for x in ready_rows], "failed": [], "registered_denominator": 32, "batch_status": batch_status}


def build_proposal(
    *,
    matrix_root: Path,
    lab_root: Path,
    output: Path,
    qualification_path: Path | None = None,
    audits_path: Path | None = None,
    prepared_root: Path | None = None,
    source_root: Path = SOURCE_ROOT,
    prepare_cases: bool = True,
) -> dict[str, Any]:
    """Build and persist one submission proposal without submitting it."""
    matrix = inspect_qualification_matrix(Path(matrix_root))
    registered = production_design(matrix)
    production_design_hash = _canonical_sha256(registered)
    qualification = _empty_qualification(registered["scope_id"])
    errors: list[str] = []
    if qualification_path is not None:
        try:
            qualification = verify_qualification_receipt(
                Path(qualification_path), matrix, source_root=Path(source_root)
            )
        except VerificationError as exc:
            errors.append(str(exc))
    audits: dict[str, dict[str, Any]] = {}
    if not errors:
        try:
            audits = load_production_audits(audits_path, design=registered)
        except VerificationError as exc:
            errors.append(str(exc))
    decision: dict[str, Any]
    if errors:
        decision = {
            "status": "scope_review_required",
            "ready": [],
            "failed": ["verification:" + error for error in errors],
            "missing": [row["case_id"] for row in registered["cases"]],
            "registered_denominator": 32,
        }
    elif qualification_path is None:
        decision = {
            "status": "awaiting_T1",
            "ready": [],
            "failed": [],
            "missing": [row["case_id"] for row in registered["cases"]],
            "registered_denominator": 32,
        }
    else:
        decision = _batch_decision(registered, qualification, audits)

    proposal: dict[str, Any] = {
        "schema": SCHEMA,
        "created_at": _stamp(),
        "family": FAMILY,
        "scope_id": registered["scope_id"],
        "revision_id": registered["revision_id"],
        "parameter_name": PARAMETER_NAME,
        "execution_status": "proposal_only",
        "central_ledger_mutation": 0,
        "old_scope_reused": False,
        "qualification_inherited": False,
        "qualification_matrix": {
            "root": matrix["root"],
            "design_path": matrix["design_path"],
            "matrix_path": matrix["matrix_path"],
            "static_path": matrix["static_path"],
            "design_sha256": matrix["design_sha256"],
            "matrix_sha256": matrix["matrix_sha256"],
            "static_sha256": matrix["static_sha256"],
        },
        "production_design": registered,
        "production_design_sha256": production_design_hash,
        "qualification_receipt": {
            "path": str(Path(qualification_path).resolve()) if qualification_path is not None else None,
            "sha256": qualification.get("_receipt_sha256"),
            "hash_verified": bool(qualification.get("_hash_verified")),
            "T1_numerical": bool(qualification.get("T1_numerical")),
            "matrix_complete": bool(qualification.get("matrix_complete")),
        },
        "batch_decision": decision,
        "registered_denominator": 32,
        "audited_case_count": len(audits),
        "prepared_batch": None,
    }
    if prepare_cases and not errors and decision.get("ready") and decision.get("status") in {"first_8", "remaining_24"}:
        rows_by_id = {row["case_id"]: row for row in registered["cases"]}
        ready_rows = [rows_by_id[case_id] for case_id in decision["ready"]]
        target = (Path(prepared_root) if prepared_root is not None else
                  Path(lab_root).resolve() / "campaigns/core-v1/cfd/prepared" /
                  (SCOPE_PROTOCOLS[registered["scope_id"]]["job_prefix"] + "-prepared"))
        batch = prepare_batch(
            ready_rows,
            matrix=matrix,
            lab_root=Path(lab_root),
            prepared_root=target,
            batch_status=str(decision["status"]),
            qualification=qualification,
            production_design_sha256=production_design_hash,
        )
        proposal["prepared_batch"] = batch
        if batch.get("status") == "scope_review_required":
            decision = dict(decision)
            decision.update(status="scope_review_required", ready=[], failed=batch.get("failed", []))
            proposal["batch_decision"] = decision
    _write_json(Path(output), proposal)
    return proposal


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-root", type=Path, default=SOURCE_ROOT)
    parser.add_argument("--source-root", type=Path, default=SOURCE_ROOT)
    parser.add_argument("--matrix-root", type=Path, default=None)
    parser.add_argument("--qualification", type=Path)
    parser.add_argument("--audits", type=Path)
    parser.add_argument("--prepared-root", type=Path)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--no-prepare", action="store_true")
    args = parser.parse_args()
    lab_root = args.lab_root.resolve()
    matrix_root = (args.matrix_root or (lab_root / QUALIFICATION_MATRIX_RELATIVE)).resolve()
    output = (args.output or (lab_root / PROPOSAL_RELATIVE)).resolve()
    proposal = build_proposal(
        matrix_root=matrix_root,
        lab_root=lab_root,
        output=output,
        qualification_path=args.qualification,
        audits_path=args.audits,
        prepared_root=args.prepared_root,
        source_root=args.source_root.resolve(),
        prepare_cases=not args.no_prepare,
    )
    print(
        json.dumps(
            {
                "status": proposal["batch_decision"]["status"],
                "ready": proposal["batch_decision"].get("ready", []),
                "failed": proposal["batch_decision"].get("failed", []),
                "registered_denominator": proposal["registered_denominator"],
                "proposal": str(output),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
