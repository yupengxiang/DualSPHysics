#!/usr/bin/env python3
"""Read-only, fail-closed F7 Pump root-review contract v2.

This module is deliberately a *contract reader*, not a campaign runner.  It
recomputes the hashes of the four already-closed route receipts and the three
official Pump source files, checks the compact receipt semantics, and returns a
diagnostic contract.  It never writes a file and has no Definition, GenCase,
native, solver, GPU, queue, registry, ledger, T1, or T2 entry point.

The contract remains blocked even when all immutable references are intact:
the motion/finish-velocity semantics are sampled and uncertified, the causal
trajectory producer and torque provenance are absent, and the material regions
are intentionally not frozen.  This is therefore suitable for a root-review
discussion only; it cannot grant admission or qualification credit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


LAB = Path(__file__).resolve().parents[1]
SCHEMA = "core.f7.pump_recirculation.root_review_contract.v2"


# These paths and digests are the v2 immutable reference baseline.  A changed
# receipt or source must be reviewed explicitly; the reader does not silently
# accept a newly observed hash.
ROUTE_RECEIPTS: dict[str, dict[str, str]] = {
    "F1_F2": {
        "path": "campaigns/core-v1/evidence/"
        "f1-f2-third-t1-route-decision-receipt-v2.json",
        "schema": "core.third_t1.f1_f2.route_decision_receipt.v2",
        "status": "route_closed_no_new_hypothesis",
        "sha256": "6917e62c95e872b73c04142d2f7b9a0ec1088a5e3fe79715e21fb8a2df47211d",
    },
    "F5": {
        "path": "campaigns/core-v1/evidence/"
        "f5-wave-runup-third-t1-route-closed-no-new-hypothesis-v1.json",
        "schema": "core.f5.third_t1.route_closed_no_new_hypothesis.v1",
        "status": "f5_route_closed_no_new_hypothesis",
        "sha256": "b192dadb44706ec8af5246a4fcb09855aeed49b4b49ada5db348eef8a7574e92",
    },
    "F6": {
        "path": "campaigns/core-v1/evidence/"
        "f6-observation-axis-v4-third-t1-route-decision-receipt-v1.json",
        "schema": "core.f6.observation_axis.third_t1.route_decision_receipt.v1",
        "status": "route_closed_no_new_hypothesis",
        "sha256": "9ee53d6f6bc31f8daef66f87bb3952dd49cd09820da0c34e986f0507fd4b1fae",
    },
}

PUMP_SOURCES: dict[str, dict[str, str]] = {
    "xml": {
        "path": "vendor/official/DualSPHysics_v5.4/examples/main/13_Pump/"
        "CasePump_Def.xml",
        "sha256": "746ae80f4c21bca62a01d59ee04d0eaaf3d1af830c36dafef4b684ca8f3c9453",
        "role": "official Pump XML motion and material source",
    },
    "fixed": {
        "path": "vendor/official/DualSPHysics_v5.4/examples/main/13_Pump/"
        "pump_fixed.vtk",
        "sha256": "6148ea8f05a2cf497eb14dd6d7ae03693cafa1c8bd271f74ff1316ba2fbaf616",
        "role": "official fixed Pump geometry source",
    },
    "moving": {
        "path": "vendor/official/DualSPHysics_v5.4/examples/main/13_Pump/"
        "pump_moving.vtk",
        "sha256": "376a6d84164ec1e154486196b4d6e7f647f857ad6cd2cf12fdd268f435753c72",
        "role": "official moving Pump geometry source",
    },
}


def sha256(path: Path) -> str:
    """Return a streaming SHA-256 digest without modifying *path*."""

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def _nested(value: Mapping[str, Any], *keys: str) -> Any:
    current: Any = value
    for key in keys:
        if not isinstance(current, Mapping) or key not in current:
            return None
        current = current[key]
    return current


def _check(
    checks: dict[str, dict[str, Any]],
    name: str,
    actual: Any,
    expected: Any,
) -> None:
    record: dict[str, Any] = {"ok": actual == expected}
    if actual != expected:
        record["actual"] = actual
        record["expected"] = expected
    checks[name] = record


def _route_semantic_checks(name: str, value: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Check only immutable, zero-credit closure semantics of one receipt."""

    checks: dict[str, dict[str, Any]] = {}
    spec = ROUTE_RECEIPTS[name]
    _check(checks, "schema", value.get("schema"), spec["schema"])
    _check(checks, "status", value.get("status"), spec["status"])

    if name == "F1_F2":
        expected = {
            "root_review.root_review_only": ("root_review", "root_review_only", True),
            "root_review.authorized_now": ("root_review", "authorized_now", False),
            "root_review.new_definition_authorized": (
                "root_review",
                "new_definition_authorized",
                False,
            ),
            "root_review.cpu_native_preflight_authorized": (
                "root_review",
                "cpu_native_preflight_authorized",
                False,
            ),
            "root_review.solver_authorized": ("root_review", "solver_authorized", False),
            "root_review.gpu_authorized": ("root_review", "gpu_authorized", False),
            "root_review.queue_mutation": ("root_review", "queue_mutation", 0),
            "root_review.registry_mutation": ("root_review", "registry_mutation", 0),
            "root_review.ledger_mutation": ("root_review", "ledger_mutation", 0),
            "root_review.T1_denominator_mutation": (
                "root_review",
                "T1_denominator_mutation",
                0,
            ),
            "root_review.T2_denominator_mutation": (
                "root_review",
                "T2_denominator_mutation",
                0,
            ),
            "root_review.qualification_credit": (
                "root_review",
                "qualification_credit",
                0,
            ),
            "denominator_preservation.existing_denominators_changed": (
                "denominator_preservation",
                "existing_denominators_changed",
                False,
            ),
            "denominator_preservation.survivor_renormalization": (
                "denominator_preservation",
                "survivor_renormalization",
                False,
            ),
        }
    elif name == "F5":
        expected = {
            "qualification_claim": (None, "qualification_claim", "none"),
            "qualified": (None, "qualified", False),
            "T1_numerical": (None, "T1_numerical", False),
            "T2_numerical": (None, "T2_numerical", False),
            "matrix_credit": (None, "matrix_credit", 0),
            "fixed_denominator.planned_rows": ("fixed_denominator", "planned_rows", 15),
            "fixed_denominator.denominator_mutation": (
                "fixed_denominator",
                "denominator_mutation",
                0,
            ),
            "fixed_denominator.matrix_mutation": (
                "fixed_denominator",
                "matrix_mutation",
                0,
            ),
            "execution_controls.read_only_audit": (
                "execution_controls",
                "read_only_audit",
                True,
            ),
            "execution_controls.definition_written": (
                "execution_controls",
                "definition_written",
                False,
            ),
            "execution_controls.gencase_invoked": (
                "execution_controls",
                "gencase_invoked",
                False,
            ),
            "execution_controls.native_decode_invoked": (
                "execution_controls",
                "native_decode_invoked",
                False,
            ),
            "execution_controls.solver_invoked": (
                "execution_controls",
                "solver_invoked",
                False,
            ),
            "execution_controls.gpu_started": (
                "execution_controls",
                "gpu_started",
                False,
            ),
            "execution_controls.queue_mutation": (
                "execution_controls",
                "queue_mutation",
                0,
            ),
            "execution_controls.registry_mutation": (
                "execution_controls",
                "registry_mutation",
                0,
            ),
            "execution_controls.ledger_mutation": (
                "execution_controls",
                "ledger_mutation",
                0,
            ),
            "execution_controls.qualification_credit": (
                "execution_controls",
                "qualification_credit",
                0,
            ),
        }
    else:
        expected = {
            "root_review.root_review_only": ("root_review", "root_review_only", True),
            "root_review.authorized_now": ("root_review", "authorized_now", False),
            "root_review.new_definition_authorized": (
                "root_review",
                "new_definition_authorized",
                False,
            ),
            "root_review.cpu_native_preflight_authorized": (
                "root_review",
                "cpu_native_preflight_authorized",
                False,
            ),
            "root_review.solver_authorized": ("root_review", "solver_authorized", False),
            "root_review.gpu_authorized": ("root_review", "gpu_authorized", False),
            "root_review.queue_mutation": ("root_review", "queue_mutation", 0),
            "root_review.registry_mutation": ("root_review", "registry_mutation", 0),
            "root_review.ledger_mutation": ("root_review", "ledger_mutation", 0),
            "root_review.matrix_mutation": ("root_review", "matrix_mutation", 0),
            "root_review.T1_denominator_mutation": (
                "root_review",
                "T1_denominator_mutation",
                0,
            ),
            "root_review.T2_denominator_mutation": (
                "root_review",
                "T2_denominator_mutation",
                0,
            ),
            "root_review.qualification_credit": (
                "root_review",
                "qualification_credit",
                0,
            ),
            "denominator_preservation.fifteen_cell_design_preserved": (
                "denominator_preservation",
                "fifteen_cell_design_preserved",
                True,
            ),
            "denominator_preservation.existing_denominators_changed": (
                "denominator_preservation",
                "existing_denominators_changed",
                False,
            ),
        }

    for label, (parent, key, expected_value) in expected.items():
        actual = value.get(key) if parent is None else _nested(value, parent, key)
        _check(checks, label, actual, expected_value)
    return checks


def _reference_binding(
    root: Path,
    *,
    name: str,
    path_text: str,
    expected_hash: str,
    role: str,
    route_spec: bool = False,
) -> dict[str, Any]:
    path = root / path_text
    result: dict[str, Any] = {
        "path": path_text,
        "role": role,
        "expected_sha256": expected_hash,
        "exists": path.is_file(),
        "hash_match": False,
        "usable": False,
    }
    if not path.is_file():
        result["observed_sha256"] = None
        result["error"] = "missing_regular_file"
        return result

    try:
        observed = sha256(path)
        result["observed_sha256"] = observed
        result["bytes"] = path.stat().st_size
        result["hash_match"] = observed == expected_hash
        if route_spec and result["hash_match"]:
            try:
                value = _read_json(path)
                checks = _route_semantic_checks(name, value)
                result["semantic_checks"] = checks
                result["semantic_match"] = all(item["ok"] for item in checks.values())
                result["usable"] = bool(result["semantic_match"])
            except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
                result["semantic_match"] = False
                result["error"] = f"invalid_json:{type(exc).__name__}"
        else:
            result["usable"] = bool(result["hash_match"])
    except OSError as exc:
        result["observed_sha256"] = None
        result["error"] = f"read_error:{type(exc).__name__}"
    return result


def _blockers(
    route_bindings: Mapping[str, Mapping[str, Any]],
    source_bindings: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    blockers: list[str] = []
    for name, binding in route_bindings.items():
        if not binding.get("exists"):
            blockers.append(f"route_receipt_missing:{name}")
        elif not binding.get("hash_match"):
            blockers.append(f"route_receipt_hash_mismatch:{name}")
        elif not binding.get("semantic_match"):
            blockers.append(f"route_receipt_semantics_mismatch:{name}")
    for name, binding in source_bindings.items():
        if not binding.get("exists"):
            blockers.append(f"official_pump_source_missing:{name}")
        elif not binding.get("hash_match"):
            blockers.append(f"official_pump_source_hash_mismatch:{name}")

    # These are intentionally unconditional v2 blockers.  The contract records
    # the gap; it never turns a source-only adapter into runtime evidence.
    blockers.extend(
        [
            "piecewise_motion_is_sampled_not_runtime_verified",
            "finish_velocity_is_sampled_and_uncertified",
            "source_region_is_not_frozen",
            "destination_region_is_not_frozen",
            "return_region_is_not_frozen",
            "residence_region_is_not_frozen",
            "unknown_region_is_not_frozen",
            "body_frame_producer_missing",
            "angular_control_producer_missing",
            "torque_provenance_missing",
            "trajectory_producer_missing",
            "no_definition_or_runtime_evidence_exists",
        ]
    )
    return blockers


def build_contract(repo_root: Path = LAB) -> dict[str, Any]:
    """Build a diagnostic v2 contract using reads and hashes only.

    ``repo_root`` is injectable solely for synthetic tests.  No path supplied
    here is ever opened for writing.
    """

    root = Path(repo_root).resolve()
    route_bindings: dict[str, dict[str, Any]] = {}
    for name, spec in ROUTE_RECEIPTS.items():
        route_bindings[name] = _reference_binding(
            root,
            name=name,
            path_text=spec["path"],
            expected_hash=spec["sha256"],
            role=f"immutable {name} route-closure receipt",
            route_spec=True,
        )

    source_bindings: dict[str, dict[str, Any]] = {}
    for name, spec in PUMP_SOURCES.items():
        source_bindings[name] = _reference_binding(
            root,
            name=name,
            path_text=spec["path"],
            expected_hash=spec["sha256"],
            role=spec["role"],
        )

    routes_bound = all(item.get("usable") is True for item in route_bindings.values())
    sources_bound = all(item.get("usable") is True for item in source_bindings.values())
    blockers = _blockers(route_bindings, source_bindings)

    return {
        "schema": SCHEMA,
        "version": "v2",
        "status": "root_review_only_blocked",
        "mode": "diagnostic_only",
        "diagnostic_only": True,
        "root_review_only": True,
        "fail_closed": True,
        "candidate_id": "F7_pump_prescribed_internal_rotor_recirculation_v1",
        "reference_integrity": {
            "route_closure_receipts_bound": routes_bound,
            "official_pump_sources_bound": sources_bound,
            "all_hash_and_semantic_checks_pass": routes_bound and sources_bound,
            "route_closure_receipts": route_bindings,
            "official_pump_sources": source_bindings,
        },
        "motion_contract": {
            "piecewise_segments": {
                "declared_from_official_xml": True,
                "evaluation_status": "sampled",
                "runtime_verified": False,
            },
            "finish_velocity": {
                "status": "sampled_uncertified",
                "sampled": True,
                "certified": False,
                "runtime_verified": False,
            },
        },
        "proposal_denominator": {
            "planned_rows": 15,
            "executed": 0,
            "passed": 0,
            "failed": 0,
            "unattempted": 15,
            "credit": 0,
            "matrix_mutation": 0,
            "survivor_renormalization": False,
        },
        "material_regions": {
            "source": {"frozen": False, "status": "not_frozen"},
            "destination": {"frozen": False, "status": "not_frozen"},
            "return": {"frozen": False, "status": "not_frozen"},
            "residence": {"frozen": False, "status": "not_frozen"},
            "unknown": {"frozen": False, "status": "not_frozen"},
        },
        "causal_runtime_contract": {
            "body_frame_producer": {"present": False, "status": "missing"},
            "angular_control_producer": {"present": False, "status": "missing"},
            "torque_provenance": {"present": False, "status": "missing"},
            "trajectory_producer": {"present": False, "status": "missing"},
        },
        "permissions": {
            "definition": False,
            "gencase": False,
            "native": False,
            "solver": False,
            "GPU": False,
            "queue": 0,
            "registry": 0,
            "ledger": 0,
        },
        "qualification": {
            "claim": "none",
            "credit": 0,
            "T1": False,
            "T2": False,
            "admission": False,
        },
        "blockers": blockers,
    }


def verify(repo_root: Path = LAB) -> dict[str, Any]:
    """Compatibility alias for callers that use the repository audit pattern."""

    return build_contract(repo_root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=LAB,
        help="repository root to inspect (read-only; useful for synthetic tests)",
    )
    args = parser.parse_args(argv)
    print(json.dumps(build_contract(args.root), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
