#!/usr/bin/env python3
"""Read-only validator for the F2 static-receiver proposal.

The proposal deliberately stops at a root-review gate.  This module only
reads JSON/markdown/HDF5/XML provenance files and recomputes SHA-256 values;
it has no GenCase, native decoder, solver, GPU, queue, ledger, registry, or
matrix submission entry point.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


LAB = Path(__file__).resolve().parents[1]
PROPOSAL = LAB / "campaigns/core-v1/cfd/f2-static-receiver-ballistic-catch-proposal-v1.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_proposal(path: Path = PROPOSAL) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def _lab_path(relative: str) -> Path:
    path = LAB / relative
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def _check_binding(item: dict[str, Any]) -> None:
    path = _lab_path(item["path"])
    if path.stat().st_size != item["bytes"]:
        raise AssertionError(f"byte count changed: {item['path']}")
    if sha256(path) != item["sha256"]:
        raise AssertionError(f"hash changed: {item['path']}")


def validate_proposal(proposal: dict[str, Any] | None = None) -> dict[str, Any]:
    proposal = proposal or load_proposal()
    assert proposal["schema"] == "core.f2.static_receiver_ballistic_catch.proposal_audit.v1"
    assert proposal["status"] == "proposal_only_root_review_required"
    assert proposal["qualification_claim"] == "none"
    assert proposal["matrix_credit"] == 0

    gate = proposal["core_gate"]
    assert gate["current_registered_t1_families"] == ["F3", "F4"]
    assert gate["third_t1_family_established"] is False
    assert gate["qualification_credit_added"] == 0
    assert gate["core_gate_changed"] is False

    candidate = proposal["candidate"]
    assert candidate["family"] == "F2"
    assert candidate["mechanism_class"] == "stationary_receiver_ballistic_slug_capture"
    assert candidate["scope_id"] == "F2_static_receiver_ballistic_catch_x_v1"

    design = proposal["fixed_scope_design"]
    assert design["cell_count"] == 15
    assert design["spatial_cell_count"] == 13
    assert design["temporal_cell_count"] == 2
    assert design["cell_count"] == design["spatial_cell_count"] + design["temporal_cell_count"]
    assert design["q_values"] == [0.0, 0.25, 0.5, 0.75, 1.0]
    assert design["qualification_q_values"] == [0.0, 0.5, 1.0]
    assert design["held_out_q_values"] == [0.25, 0.75]
    assert design["dp_values_m"] == [0.01, 0.0075, 0.005]
    assert design["temporal_controls"] == ["internal_time", "native_output"]
    assert len(design["planned_rows"]) == 15
    assert [row["index"] for row in design["planned_rows"]] == list(range(15))
    assert {row["status"] for row in design["planned_rows"]} == {"not_started"}

    fresh = proposal["fresh_input_contract"]
    assert fresh["source_identity_changed"] is True
    assert fresh["source_reuse"] is False
    assert fresh["qualification_inheritance"] is False
    assert fresh["old_generated_input_reused"] is False
    assert fresh["old_trajectory_reused"] is False
    assert fresh["new_definition_required"] is True
    assert fresh["new_native_output_required"] is True
    assert fresh["same_input_retry"] is False

    controls = proposal["execution_controls"]
    for key in ("gencase_invoked", "native_decode_invoked", "solver_invoked", "gpu_launched"):
        assert controls[key] is False
    for key in ("queue_mutation", "central_ledger_mutation", "central_registry_mutation"):
        assert controls[key] == 0
    assert controls["matrix_materialized"] is False
    assert controls["matrix_submitted"] is False

    denominator = proposal["denominator"]
    assert denominator == {
        "planned": 15,
        "executed": 0,
        "passed": 0,
        "failed": 0,
        "event_censored": 0,
        "unattempted": 15,
        "credit": 0,
        "same_input_retry": False,
        "survivor_renormalization": False,
    }

    for item in proposal["evidence"]["bindings"]:
        _check_binding(item)

    implementation = proposal["implementation"]
    assert implementation["path"] == "scripts/f2_static_receiver_ballistic_catch_proposal_v1.py"
    assert implementation["sha256"] == sha256(Path(__file__))
    assert implementation["bytes"] == Path(__file__).stat().st_size

    # The proposed namespace must contain design/provenance only.  A future
    # root review may add fresh inputs; this proposal itself must not point at
    # a generated XML, BI4, solver product, trajectory, queue, or job.
    artifacts = proposal["proposal_only_artifacts"]
    assert artifacts == {
        "definition_present": False,
        "generated_native_present": False,
        "solver_product_present": False,
        "trajectory_present": False,
        "job_submitted": False,
    }

    return {
        "status": "ok",
        "proposal": str(PROPOSAL.relative_to(LAB)),
        "binding_count": len(proposal["evidence"]["bindings"]),
        "planned_denominator": denominator["planned"],
        "runtime_calls": {
            "gencase": False,
            "native_decode": False,
            "solver": False,
            "gpu": False,
            "queue": 0,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proposal", type=Path, default=PROPOSAL)
    args = parser.parse_args()
    result = validate_proposal(load_proposal(args.proposal))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
