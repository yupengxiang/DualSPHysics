#!/usr/bin/env python3
"""Independent read-only root review for the proposed F5 Core scope.

The review verifies the proposal and its pinned source files.  It authorizes
only preparation of a new Definition and scaled motion file; it has no
GenCase, decoder, solver, GPU, queue, ledger, registry, or matrix entrypoint.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any


LAB = Path(__file__).resolve().parents[1]
PROPOSAL = LAB / "campaigns/core-v1/cfd/f5-wave-runup-third-t1-proposal-audit-v1.json"
OUTPUT = LAB / "campaigns/core-v1/cfd/f5-wave-runup-root-review-v1.json"
TEST = LAB / "tests/test_f5_wave_runup_root_review_v1.py"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def bind(path: Path, role: str) -> dict[str, Any]:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {
        "path": str(path.relative_to(LAB)),
        "sha256": sha256(path),
        "bytes": path.stat().st_size,
        "role": role,
    }


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def build_review() -> dict[str, Any]:
    proposal = load(PROPOSAL)
    assert proposal["schema"] == "core.f5.third_t1.proposal_audit.v1"
    assert proposal["status"] == "proposal_only_root_review_required"
    assert proposal["qualification_claim"] == "none"
    candidate = proposal["candidate"]
    assert candidate["family"] == "F5"
    assert candidate["scope_id"] == "F5_prescribed_wave_runup_x_v1"
    gate = proposal["core_gate"]
    assert gate["current_registered_t1_families"] == ["F3", "F4"]
    assert gate["qualification_credit_added"] == 0
    assert gate["core_gate_changed"] is False

    controls = proposal["execution_controls"]
    for key in (
        "gencase_invoked", "native_decode_invoked", "solver_invoked",
        "gpu_launched", "matrix_materialized", "matrix_submitted",
    ):
        assert controls[key] is False, key
    for key in ("queue_mutation", "central_ledger_mutation", "central_registry_mutation"):
        assert controls[key] == 0, key

    design = proposal["fixed_scope_design"]
    assert design["cell_count"] == 15
    assert design["spatial_cell_count"] == 13
    assert design["temporal_cell_count"] == 2
    assert design["qualification_q"] == [0.0, 0.5, 1.0]
    assert design["held_out_q"] == [0.25, 0.75]
    assert design["resolutions_m"] == [0.01, 0.0075, 0.005]
    assert design["registered_window"]["time_max_s"] == 16.0
    assert design["registered_window"]["event_completion_required"] is True

    identity = proposal["fresh_input_contract"]
    for key in (
        "source_identity_changed", "new_definition_required", "new_motion_file_required",
    ):
        assert identity[key] is True, key
    for key in ("qualification_inheritance", "old_generated_input_reused", "old_trajectory_reused"):
        assert identity[key] is False, key

    official = proposal["evidence"]["official_inputs"]
    assert len(official) == 6
    verified_official = []
    for item in official:
        path = LAB / item["path"]
        assert path.is_file(), path
        assert sha256(path) == item["sha256"], path
        assert path.stat().st_size == item["bytes"], path
        verified_official.append(bind(path, item.get("role", "official F5 source")))

    r3 = proposal["evidence"]["r3_summary"]
    assert r3["execution_status"] == "candidate_only"
    assert r3["formal_release_authorized"] is False
    assert len(r3["runs"]) == 3
    assert [row["dp_m"] for row in r3["runs"]] == [0.03, 0.025, 0.02]
    assert all(row["status"] == "completed" for row in r3["runs"])
    assert all(row["frames"] == 801 for row in r3["runs"])

    return {
        "schema": "core.f5.third_t1.root_review_receipt.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "record_id": "f5-wave-runup-third-t1-root-review-v1",
        "status": "definition_preparation_authorized_solver_closed",
        "review_decision": {
            "candidate_scope_id": candidate["scope_id"],
            "candidate_family": "F5",
            "authorized_now": True,
            "authorized_action": "write_one_fresh_definition_and_scaled_motion_file",
            "authorized_solver": False,
            "authorized_cpu_native_preflight": False,
            "authorized_matrix": False,
            "reason": (
                "the proposal binds a distinct prescribed-piston wave/run-up mechanism and "
                "pinned source provenance, while all existing R3 products remain candidate-only"
            ),
            "next_review_required": "root review after fresh Definition/motion hash closure before any CPU/native preflight",
        },
        "source_review": {
            "official_inputs_verified": True,
            "official_input_count": len(verified_official),
            "official_inputs": verified_official,
            "r3_candidate_only_verified": True,
            "old_generated_products_qualification_reuse": False,
            "external_reference_training_use": False,
        },
        "scientific_contract": {
            "mechanism_class": candidate["mechanism_class"],
            "family_difference": candidate["scientific_difference"],
            "cell_count": design["cell_count"],
            "parameter": design["parameter"],
            "mapping": design["mapping"],
            "resolutions_m": design["resolutions_m"],
            "time_max_s": design["registered_window"]["time_max_s"],
            "output_interval_s": design["registered_window"]["output_interval_s"],
            "event_completion_required": design["registered_window"]["event_completion_required"],
            "fixed_denominator": True,
            "partial_credit": False,
        },
        "forbidden_actions": [
            "reuse R3 generated XML, BI4, HDF5, or trajectory as Core qualification input",
            "run GenCase/native decoder before a second review of fresh input hashes",
            "run solver or GPU work",
            "submit or mutate queue, ledger, registry, or qualification matrix",
            "change event, mass, identity, geometry, cadence, or denominator thresholds after observing results",
            "fit a time shift or use the external reference as particle labels or training targets",
        ],
        "execution_constraints": {
            "read_only_review": True,
            "definition_written_by_review": False,
            "motion_written_by_review": False,
            "gencase_invoked": False,
            "native_decode_invoked": False,
            "solver_invoked": False,
            "gpu_started": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "matrix_mutation": 0,
            "qualification_credit": 0,
            "core_gate_changed": False,
        },
        "hash_bindings": {
            "proposal": bind(PROPOSAL, "F5 proposal-only audit"),
            "implementation": bind(Path(__file__), "F5 root-review implementation"),
            "test": bind(TEST, "F5 root-review regression test"),
        },
    }


def verify(path: Path = OUTPUT) -> dict[str, Any]:
    value = load(path)
    assert value["schema"] == "core.f5.third_t1.root_review_receipt.v1"
    assert value["review_decision"]["authorized_action"] == "write_one_fresh_definition_and_scaled_motion_file"
    assert value["review_decision"]["authorized_solver"] is False
    assert value["review_decision"]["authorized_cpu_native_preflight"] is False
    assert value["execution_constraints"]["qualification_credit"] == 0
    for item in value["hash_bindings"].values():
        bound = LAB / item["path"]
        assert bound.is_file(), bound
        assert bound.stat().st_size == item["bytes"], bound
        assert sha256(bound) == item["sha256"], bound
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    review = build_review()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(review, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    verify(args.output)
    print(json.dumps({"status": review["status"], "output": str(args.output), "sha256": sha256(args.output)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
