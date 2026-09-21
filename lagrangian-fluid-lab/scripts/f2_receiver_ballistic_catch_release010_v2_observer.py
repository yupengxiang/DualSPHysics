#!/usr/bin/env python3
"""Build the static receiver/contact and destination observer contract.

This module only defines how a future trajectory would be observed.  It does
not open a trajectory, run a decoder, launch a solver, or assign qualification
credit.  Missing identities stay a hard-integrity failure and are never
silently counted as spill.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


LAB = Path(__file__).resolve().parents[1]
BASE = LAB / "campaigns/core-v1/cfd/f2-static-receiver-ballistic-catch-release010-v2"
OUTPUT = BASE / "observer-contract-v2.json"
CANDIDATE = LAB / "campaigns/core-v1/cfd/f2-pour-catch-candidate-card-v2.json"

SCHEMA = "core.f2.receiver_ballistic_catch.observer_contract.v2"
SCOPE_ID = "F2_receiver_ballistic_catch_release_speed_v2_x_v1"
REVISION_ID = "F2_receiver_ballistic_catch_release_speed_v2"
CASE_ID = "CORE_F2_RECEIVER_BALLISTIC_CATCH_RELEASE010_q0p50000000_dp0p007500000000_anchor"
DP_M = 0.0075
INITIAL_MASS_KG = 7.776
TIME_MAX_S = 1.5
OUTPUT_INTERVAL_S = 0.005
CONTACT_FRACTION = 0.01
SPILL_FRACTION = 0.01
CONTACT_SUSTAINED_S = 0.20
MASS_SUM_TOLERANCE = 1.0e-8


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ref(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size, "role": role}


def load(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _receiver_endpoint(q: float, label: str) -> dict[str, Any]:
    center_y = -0.12 + 0.24 * q
    low_y = center_y - 0.18
    high_y = center_y + 0.18
    return {
        "q": q,
        "label": label,
        "receiver_center_y_m": center_y,
        "receiver_closed_box_m": {
            "low": [0.35, low_y, 0.08],
            "high": [0.85, high_y, 0.58],
            "closed_faces": ["bottom", "left", "right", "front", "back"],
            "open_faces": ["top"],
        },
        "observer_interior_m": {
            "low": [0.35 + DP_M, low_y + DP_M, 0.08 + DP_M],
            "high": [0.85 - DP_M, high_y - DP_M, 0.58 - DP_M],
            "clearance_m": DP_M,
        },
        "source_centerline_y_m": 0.0,
        "placement_semantics": "receiver centerline only; source geometry and release velocity remain fixed",
    }


def build_contract(output: Path = OUTPUT) -> dict[str, Any]:
    output = Path(output).resolve()
    candidate = load(CANDIDATE)
    if candidate.get("candidate_id") != "F2_receiver_ballistic_catch_release_speed010_v2":
        raise ValueError("candidate card identity mismatch")
    if candidate.get("matrix_credit") != 0 or candidate.get("qualification_claim") != "none":
        raise ValueError("candidate card opened qualification credit")
    topology = candidate.get("topology", {})
    if any(topology.get(key) is not False for key in ("aperture_or_crest", "moving_cup", "submerged_slot")):
        raise ValueError("candidate topology is not distinct from the closed routes")
    if output.exists():
        raise FileExistsError(f"observer contract already exists: {output}")

    endpoints = [
        _receiver_endpoint(0.0, "qualification_low_endpoint"),
        _receiver_endpoint(0.25, "held_out_low_midpoint"),
        _receiver_endpoint(0.5, "anchor_center_endpoint"),
        _receiver_endpoint(0.75, "held_out_high_midpoint"),
        _receiver_endpoint(1.0, "qualification_high_endpoint"),
    ]
    rows = candidate["planned_matrix"]["rows"]
    required_cases = [row["case_id"] for row in rows if row["design_cell"] in {"spatial", "held_out"}]

    contract = {
        "schema": SCHEMA,
        "status": "observer_contract_static_root_review_pending",
        "family": "F2",
        "scope_id": SCOPE_ID,
        "revision_id": REVISION_ID,
        "anchor_case_id": CASE_ID,
        "qualification_claim": "none",
        "matrix_credit": 0,
        "geometry_contract": {
            "outer_tank": {
                "low_m": [0.0, -0.45, 0.0],
                "high_m": [1.25, 0.45, 0.80],
                "closed_faces": ["bottom", "left", "right", "front", "back"],
                "open_faces": ["top"],
                "endpoint_tolerance_m": 1.0e-8,
            },
            "receiver_basin": {
                "x_low_m": 0.35,
                "x_high_m": 0.85,
                "z_low_m": 0.08,
                "z_high_m": 0.58,
                "y_mapping": "center_y_m = -0.12 + 0.24*q; size_y_m = 0.36",
                "closed_faces": ["bottom", "left", "right", "front", "back"],
                "open_faces": ["top"],
                "endpoint_tolerance_m": 1.0e-8,
                "interior_clearance_m": DP_M,
            },
            "runtime_domain": {
                "low_m": [-0.15, -0.55, -0.15],
                "high_m": [1.40, 0.55, 1.05],
            },
        },
        "receiver_contact": {
            "mass_basis": "initial native fluid mass",
            "initial_mass_kg": INITIAL_MASS_KG,
            "interior_definition": "active fluid position inside the q-specific one-dp-clear receiver interior AABB",
            "minimum_mass_fraction": CONTACT_FRACTION,
            "minimum_mass_kg": INITIAL_MASS_KG * CONTACT_FRACTION,
            "first_contact": "first saved frame at or above the threshold after the source descends from its initial height",
            "sustained_contact_required": True,
            "sustained_duration_s": CONTACT_SUSTAINED_S,
            "open_top_is_not_closed_wall_violation": True,
            "closed_face_endpoint_or_chord_violation": "hard integrity failure, independent of contact event",
        },
        "retained_vs_spill": {
            "frame_scope": "only after first receiver contact; final allocation requires the full registered horizon",
            "retained": "active fluid mass inside the q-specific one-dp-clear receiver interior",
            "spill_or_residual": "active fluid mass outside that receiver interior but still inside the outer tank/runtime domain after contact",
            "escaped": "active fluid mass outside the runtime domain or outside a closed outer-tank face; never relabel as spill",
            "transit": "mass before first contact or before terminal allocation; diagnostic only and never a pass",
            "missing_identity": "a fluid ID present in the initial native set but absent from a frame; hard integrity failure, never spill",
            "mass_partition": ["retained", "spill_or_residual", "escaped", "transit", "missing_identity"],
            "terminal_reporting": {
                "retained_fraction": "retained_mass / initial_mass",
                "spill_or_residual_fraction": "spill_or_residual_mass / initial_mass",
                "escaped_fraction": "escaped_mass / initial_mass",
                "partition_sum_tolerance": MASS_SUM_TOLERANCE,
                "allocation_complete": "retained + spill_or_residual + escaped equals initial active mass within tolerance and no missing IDs",
                "event_window_complete": "full 1.5 s horizon reached after contact and allocation is reported",
            },
            "spill_diagnostic_threshold": SPILL_FRACTION,
            "spill_threshold_is_not_a_credit_rule": True,
        },
        "q_endpoint_contract": {
            "parameter": "receiver_center_y_m",
            "mapping": "receiver_center_y_m = -0.12 + 0.24*q",
            "endpoints": endpoints,
            "required_spatial_q": [0.0, 0.5, 1.0],
            "held_out_q": [0.25, 0.75],
            "required_case_ids": required_cases,
            "source_centerline_fixed": True,
            "endpoint_comparison": "report contact, retained, spill_or_residual, escaped, transit, and missing-ID fractions separately for every q",
            "partial_capture_semantics": "q changes only receiver lateral placement; partial capture is an observed destination allocation, never an inferred pass",
        },
        "hard_integrity_before_event": [
            "native IDs unique and aligned with generated XML",
            "all active position, velocity, density, and mass arrays finite",
            "zero active fluid IDs missing from any required frame",
            "zero closed outer-tank endpoint violations and saved chord crossings",
            "zero closed receiver-basin endpoint violations and saved chord crossings",
            "zero valid fluid positions outside the declared runtime domain",
            "native source mass relative error <= 0.025 with no mass rescaling",
            "full 1.5 s registered horizon reached",
        ],
        "denominator_policy": {
            "planned_rows": 15,
            "executed_rows": 0,
            "qualification_credit": 0,
            "event_censoring_is_zero_credit": True,
            "same_input_retry": False,
            "survivor_renormalization": False,
            "failure_rows_retained": True,
        },
        "fresh_input_boundary": {
            "old_v1_definition_reused": False,
            "old_v1_generated_xml_reused": False,
            "old_v1_native_bi4_reused": False,
            "old_v1_trajectory_reused": False,
            "old_v1_output_stem_reused": False,
            "submerged_slot_assets_reused": False,
            "observer_only": True,
            "forbidden_sources": [
                "campaigns/core-v1/cfd/f2-static-receiver-ballistic-catch-v1/**",
                "campaigns/core-v1/runtime/attempts/f2-static-receiver-ballistic-catch-q05-anchor-*/*",
                "campaigns/core-v1/cfd/f2-distributed-slot-transfer-v1/**",
                "campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/**",
            ],
        },
        "execution_controls": {
            "trajectory_opened": False,
            "native_decoder_invoked": False,
            "solver_invoked": False,
            "gpu_launched": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "T1_denominator_mutation": 0,
            "T2_denominator_mutation": 0,
            "qualification_credit": 0,
        },
        "hash_bindings": {
            "candidate_card": ref(CANDIDATE, "v2 conditional candidate card"),
            "implementation": ref(Path(__file__).resolve(), "observer contract implementation"),
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(contract, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return contract


def verify_contract(path: Path = OUTPUT) -> dict[str, Any]:
    value = load(Path(path))
    if value.get("schema") != SCHEMA or value.get("status") != "observer_contract_static_root_review_pending":
        raise ValueError("observer contract schema/status mismatch")
    if value.get("matrix_credit") != 0 or value.get("qualification_claim") != "none":
        raise ValueError("observer contract opened qualification credit")
    contact = value.get("receiver_contact", {})
    if contact.get("minimum_mass_fraction") != CONTACT_FRACTION or contact.get("sustained_duration_s") != CONTACT_SUSTAINED_S:
        raise ValueError("receiver-contact contract changed")
    allocation = value.get("retained_vs_spill", {})
    if allocation.get("missing_identity") != "a fluid ID present in the initial native set but absent from a frame; hard integrity failure, never spill":
        raise ValueError("missing IDs may not be relabelled as spill")
    endpoints = value.get("q_endpoint_contract", {}).get("endpoints", [])
    if [item.get("q") for item in endpoints] != [0.0, 0.25, 0.5, 0.75, 1.0]:
        raise ValueError("q endpoint ladder changed")
    for key, item in value.get("hash_bindings", {}).items():
        path = Path(item["path"])
        if not path.is_file() or item.get("sha256") != sha256(path) or item.get("bytes") != path.stat().st_size:
            raise ValueError(f"stale observer binding: {key}")
    controls = value.get("execution_controls", {})
    for key in ("trajectory_opened", "native_decoder_invoked", "solver_invoked", "gpu_launched"):
        if controls.get(key) is not False:
            raise ValueError(f"observer execution opened: {key}")
    for key in ("queue_mutation", "ledger_mutation", "registry_mutation", "T1_denominator_mutation", "T2_denominator_mutation", "qualification_credit"):
        if controls.get(key) != 0:
            raise ValueError(f"observer mutation opened: {key}")
    return {"status": "ok", "schema": value["schema"], "candidate_id": "F2_receiver_ballistic_catch_release_speed010_v2", "q_endpoints": len(endpoints), "matrix_credit": 0}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("write")
    p.add_argument("--output", type=Path, default=OUTPUT)
    p = sub.add_parser("verify")
    p.add_argument("--contract", type=Path, default=OUTPUT)
    args = parser.parse_args()
    result = build_contract(args.output) if args.command == "write" else verify_contract(args.contract)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
