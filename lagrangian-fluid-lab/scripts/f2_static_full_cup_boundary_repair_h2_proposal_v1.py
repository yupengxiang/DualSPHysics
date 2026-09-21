#!/usr/bin/env python3
"""Record a read-only H2 proposal for the F2 static full-cup scope.

The first static full-cup runtime canary failed with native DBC and a fresh
mDBC repair still failed the same wall-support integrity gate.  This module
does not rerun either input.  It binds those negative records and describes a
new initial-fluid support-clearance hypothesis.  The proposal has no solver,
GPU, queue, ledger, registry, or qualification entry point.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


LAB = Path(__file__).resolve().parents[1]
OUTPUT = LAB / "campaigns/core-v1/cfd/f2-static-full-cup-boundary-repair-h2-proposal-v1.json"
REPORT = LAB / "reports/F2-STATIC-FULL-CUP-BOUNDARY-REPAIR-H2-PROPOSAL-2026-09-21.zh-CN.md"
SCOPE_ID = "F2_static_full_cup_volume_hold_x_v1"
HYPOTHESIS_ID = "F2_static_full_cup_initial_support_clearance_h2_v1"
DENOMINATOR = 15


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def rel(path: Path) -> str:
    return path.resolve().relative_to(LAB.resolve()).as_posix()


def binding(path: Path, role: str) -> dict[str, Any]:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": rel(path), "sha256": sha256(path), "bytes": path.stat().st_size, "role": role}


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def _path(*parts: str) -> Path:
    return LAB.joinpath(*parts)


def _assert_source_facts() -> dict[str, Any]:
    smoke_path = _path("campaigns/core-v1/cfd/f2-static-full-cup-runtime-smoke-negative-evidence-v1.json")
    h1_path = _path("campaigns/core-v1/cfd/f2-static-full-cup-boundary-repair-h1-negative-evidence-v1.json")
    matrix_audit_path = _path("campaigns/core-v1/cfd/f2-static-full-cup-matrix-prepared-v4/matrix-preparation-audit.json")
    candidate_path = _path("campaigns/core-v1/cfd/f2-static-full-cup-volume-hold-candidate-v1.json")
    root_path = _path("campaigns/core-v1/cfd/f2-static-full-cup-boundary-repair-h1-runtime-root-review-v1.json")
    smoke, h1, matrix, candidate, root = map(load, (smoke_path, h1_path, matrix_audit_path, candidate_path, root_path))
    for record in (smoke, h1):
        status = record.get("scientific_status", {})
        if status.get("hard_integrity_pass") is not False or status.get("T1_numerical") is not False:
            raise ValueError("negative runtime evidence is no longer negative")
        if status.get("qualification_claim") != "none":
            raise ValueError("negative evidence carries a qualification claim")
        if status.get("registry_mutation") != 0:
            raise ValueError("negative evidence mutated the registry")
    if smoke.get("decision", {}).get("preserve_failure_denominator") != DENOMINATOR:
        raise ValueError("smoke denominator changed")
    if h1.get("decision", {}).get("preserve_failure_denominator") != DENOMINATOR:
        raise ValueError("H1 denominator changed")
    if h1.get("repair_budget", {}).get("used_hypothesis_classes") != 1:
        raise ValueError("H1 repair budget is not recorded as consumed")
    if matrix.get("prepared_cell_count") != DENOMINATOR or matrix.get("failed_cell_count") != 0:
        raise ValueError("v4 CPU/native matrix closure is not complete")
    if candidate.get("qualified") is not False or candidate.get("qualification_only") is not True:
        raise ValueError("candidate qualification boundary changed")
    if root.get("decision") != "approved_for_runtime_smoke":
        raise ValueError("H1 root review identity changed")
    if root.get("authorization", {}).get("registry_mutation") is not False:
        raise ValueError("H1 root review mutated the registry")
    return {
        "smoke": binding(smoke_path, "native DBC cell-0 negative runtime evidence"),
        "h1": binding(h1_path, "mDBC H1 cell-0 negative runtime evidence"),
        "matrix_audit": binding(matrix_audit_path, "15-cell CPU/native closure audit"),
        "candidate": binding(candidate_path, "static full-cup candidate card"),
        "h1_root_review": binding(root_path, "H1 root review"),
    }


def _continuous_fit_screen() -> dict[str, Any]:
    """Check the proposed source box before any GenCase invocation."""
    rows = []
    for dp in (0.01, 0.0075, 0.005):
        clearance = 3.0 * 1.3 * dp
        width = 0.425 - 2.0 * clearance
        depth = 0.30 - 2.0 * clearance
        area = width * depth
        for q in (0.0, 0.25, 0.5, 0.75, 1.0):
            volume = 0.022950 + 0.001290 * q
            height = volume / area
            top = 0.65 + height
            rows.append({"q": q, "dp_m": dp, "clearance_m": clearance,
                         "source_area_m2": area, "height_m": height, "top_m": top,
                         "clearance_ge_3h": clearance >= 3.0 * 1.3 * dp,
                         "fits_below_cup_top": top <= 1.10})
    return {"rows": rows, "all_continuous_fit": all(r["fits_below_cup_top"] for r in rows),
            "all_clearance_rules_hold": all(r["clearance_ge_3h"] for r in rows),
            "mass_and_native_sampling_pending": True}


def build_contract() -> dict[str, Any]:
    evidence = _assert_source_facts()
    now = datetime.now(timezone.utc).isoformat()
    return {
        "schema": "core.f2.static_full_cup.boundary_repair_h2_proposal.v1",
        "record_id": "f2-static-full-cup-boundary-repair-h2-proposal-v1",
        "created_at_utc": now,
        "family": "F2",
        "scope_id": SCOPE_ID,
        "repair_id": HYPOTHESIS_ID,
        "status": "proposal_only_root_review_required",
        "qualification_claim": "none; independent H2 hypothesis only",
        "qualified": False,
        "T1_numerical": False,
        "matrix_credit": 0,
        "fixed_failure_denominator": {
            "planned": DENOMINATOR,
            "executed": 0,
            "passed": 0,
            "failed": 0,
            "unattempted": DENOMINATOR,
            "survivor_renormalization": False,
            "anchor_trajectory_reuse": False,
        },
        "evidence": evidence,
        "prior_negative_results": {
            "native_dbc_smoke": {
                "first_failure_time_s": 0.02001944020583839,
                "endpoint_violation_particle_frames": 28786,
                "unique_wall_violation_id_count": 1304,
                "saved_chord_crossing_count": 1274,
            },
            "h1_mdbc": {
                "first_failure_time_s": 0.02001456907554933,
                "endpoint_violation_particle_frames": 10433,
                "unique_wall_violation_id_count": 1094,
                "saved_chord_crossing_count": 1263,
            },
            "interpretation": "both runtime canaries are retained hard-integrity negatives; no same-input retry and no matrix expansion are allowed",
        },
        "hypothesis": {
            "class": "H2_initial_fluid_support_clearance",
            "independent_change": "construct a fresh fluid lattice with an explicit 3*hdp*dp clearance from the fixed cup side/bottom faces, while retaining the H1 mDBC boundary formulation",
            "continuous_cup_geometry_unchanged": True,
            "boundary_formulation": "Boundary=2, explicit geometry normals, -mdbc_noslip:1",
            "mass_policy": "native rho*dp^3; no mass rescaling",
            "window_s": 0.6,
            "hdp": 1.3,
            "clearance_rule": "c(dp)=3*hdp*dp",
            "source_box_rule": {
                "cup_low_m": [0.0, -0.15, 0.65],
                "cup_size_m": [0.425, 0.30, 0.45],
                "fluid_low_xy_m": ["c(dp)", "-0.15+c(dp)"],
                "fluid_size_xy_m": ["0.425-2*c(dp)", "0.30-2*c(dp)"],
                "volume_axis": "V(q)=0.022950+0.001290*q m3",
                "fluid_height_rule": "H(q,dp)=V(q)/((0.425-2*c(dp))*(0.30-2*c(dp)))",
                "fluid_bottom_m": 0.65,
            },
            "fresh_identity": {
                "case_id_prefix": "CORE_F2_static_full_cup_volume_supportclearance_h2",
                "revision_id": "F2_static_full_cup_support_clearance_h2_v1",
                "old_definition_reused": False,
                "old_trajectory_reused": False,
            },
            "falsifiers": [
                "any generated fluid point is within c(dp) of a closed cup face",
                "native IDs or fluid count do not match the fresh XML",
                "native mass relative error exceeds the registered 0.03 preparation gate",
                "any BoundNor is zero/nonfinite or any endpoint/chord violation remains",
                "the changed footprint cannot fit the declared cup volume without crossing the open top",
            ],
        },
        "static_fit_screen": _continuous_fit_screen(),
        "authorization": {
            "definition_writer": False,
            "cpu_gencase": False,
            "native_decode": False,
            "solver": False,
            "gpu": False,
            "job_spec_creation": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "qualification_credit": 0,
            "next_review": "separate root review may authorize exactly one fresh CPU/native canary after static fit and mass checks",
        },
        "required_execution_order": [
            "review the literal H2 source-box construction and verify the clearance/volume fit for all 15 rows",
            "write a new Definition and motion file under a new H2 identity",
            "run exactly one CPU GenCase/native decode canary",
            "record a zero-credit pass or retained failure; stop before solver/GPU/matrix queue",
        ],
        "implementation": binding(Path(__file__), "H2 proposal audit implementation"),
        "interpretation_boundary": "proposal-only route audit; no runtime output, T1 qualification, material qualification, registry entry, or Core gate change",
    }


def write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def verify(path: Path) -> dict[str, Any]:
    payload = load(path)
    checks = {
        "schema": payload.get("schema") == "core.f2.static_full_cup.boundary_repair_h2_proposal.v1",
        "status_closed": payload.get("status") == "proposal_only_root_review_required",
        "qualification_closed": payload.get("qualification_claim", "").startswith("none;"),
        "denominator_fixed": payload.get("fixed_failure_denominator", {}).get("planned") == DENOMINATOR,
        "zero_credit": payload.get("matrix_credit") == 0 and payload.get("authorization", {}).get("qualification_credit") == 0,
        "execution_closed": all(payload.get("authorization", {}).get(key) is False for key in ("cpu_gencase", "native_decode", "solver", "gpu", "job_spec_creation")),
        "central_mutations_closed": payload.get("authorization", {}).get("queue_mutation") == 0 and payload.get("authorization", {}).get("ledger_mutation") == 0 and payload.get("authorization", {}).get("registry_mutation") == 0,
        "evidence_present": len(payload.get("evidence", {})) == 5,
    }
    return {"ok": all(checks.values()), "checks": checks}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("build", "verify"))
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    if args.command == "build":
        payload = build_contract()
        write(args.output, payload)
        print(json.dumps({"status": payload["status"], "matrix_credit": payload["matrix_credit"], "output": str(args.output)}, ensure_ascii=False))
        return 0
    result = verify(args.output)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
