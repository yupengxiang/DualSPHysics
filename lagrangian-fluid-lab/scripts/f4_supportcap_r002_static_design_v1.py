#!/usr/bin/env python3
"""Build a static, zero-credit F4 r002 temporal-alignment design receipt.

This module does not open the native trajectory, execute the tracer, start a
solver/worker, or authorize another canary.  It specifies a new prospective
attempt that starts the same 512 independent tracers against native row 0 and
advances them through rows 0..41, so the row-40 -> row-41 comparison uses the
advected tracer state rather than the original t=0 coordinates.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from scripts import f4_supportcap_affine_query_bound_candidate_v3 as candidate


LAB = Path(__file__).resolve().parents[1]
R001_ID = "f4-supportcap-affine-query-bound-v3-cpu-native-canary-r001"
R002_ID = "f4-supportcap-affine-query-bound-v3-cpu-native-canary-r002"
ATTRIBUTION = Path("campaigns/core-v1/material/evidence") / f"{R001_ID}-failure-attribution-v1.json"
CANDIDATE_DIR = Path("campaigns/core-v1/material/candidates/f4-supportcap-affine-query-bound-v3")
R001_DIR = Path("campaigns/core-v1/material/evidence") / R001_ID
RECEIPT = CANDIDATE_DIR / "r002-static-design-v1/recipe.json"
SCHEMA = "core.material.f4.supportcap_r002_static_temporal_alignment_design.v1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _repo_path(path: Path) -> str:
    return str(path.relative_to(LAB)) if path.is_absolute() else str(path)


def _binding(path: Path, role: str) -> dict[str, Any]:
    absolute = (LAB / path).resolve() if not path.is_absolute() else path.resolve()
    if not absolute.is_file():
        raise FileNotFoundError(absolute)
    return {
        "path": _repo_path(absolute),
        "role": role,
        "bytes": absolute.stat().st_size,
        "sha256": _sha256(absolute),
    }


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads((LAB / path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def validate_alignment_contract(contract: dict[str, Any]) -> None:
    """Reject any recipe that recreates r001's t=0/row-40 mismatch."""
    expected = {
        "initial_native_frame": 0,
        "last_native_frame_inclusive": 41,
        "target_transition": [40, 41],
        "expected_saved_rows": 42,
        "advect_initial_seeds_before_target_transition": True,
        "query_original_t0_seed_positions_at_row40": False,
    }
    mismatches = {
        key: (contract.get(key), value)
        for key, value in expected.items()
        if contract.get(key) != value
    }
    if mismatches:
        raise ValueError(f"F4 r002 temporal-alignment contract is invalid: {mismatches}")


def _parent_bindings(attribution: dict[str, Any]) -> list[dict[str, Any]]:
    # Revalidate the attribution's bounded evidence files, but deliberately do
    # not hash/read the full native HDF5 here. Its immutable digest is inherited
    # from the already-completed read-only r001 attribution.
    result: list[dict[str, Any]] = []
    for item in attribution.get("bindings", []):
        path = Path(str(item["path"]))
        observed = _binding(path, str(item["role"]))
        if observed["bytes"] != item["bytes"] or observed["sha256"] != item["sha256"]:
            raise ValueError(f"immutable r001 parent changed: {path}")
        result.append(observed)
    if not result:
        raise ValueError("r001 attribution has no immutable evidence bindings")
    return result


def build_recipe() -> dict[str, Any]:
    attribution = _read_json(ATTRIBUTION)
    if (
        attribution.get("status") != "read_only_setup_mismatch_strongly_supported"
        or attribution.get("historical_attempt_id") != R001_ID
        or attribution.get("historical_attempt_status") != "failed_one_attempt_zero_credit"
        or attribution.get("historical_attempt_modified") is not False
        or attribution.get("canary_reexecuted") is not False
        or attribution.get("qualification_credit") != 0
    ):
        raise ValueError("r001 attribution is not the expected immutable failed attempt")
    minimum = attribution.get("minimum_next_step", {})
    if (
        minimum.get("kind") != "new static candidate/root review only; no r001 retry"
        or minimum.get("new_runtime_authorization_required_before_any_future_native_canary") is not True
    ):
        raise ValueError("r001 attribution does not authorize this static-only next step")

    card = _read_json(CANDIDATE_DIR / "candidate-card-v3.json")
    review = _read_json(CANDIDATE_DIR / "terra-high-root-review-v4.json")
    r001_result = _read_json(R001_DIR / "result.json")
    if (
        card.get("candidate_id") != candidate.CANDIDATE_ID
        or card.get("status") != "proposal_only_root_review_required"
        or review.get("status") != "static_review_completed_canary_denied"
        or review.get("authorized_one_cpu_only") is not False
    ):
        raise ValueError("current F4 candidate/review is not the expected no-runtime parent")

    alignment = {
        "initial_native_frame": 0,
        "last_native_frame_inclusive": 41,
        "target_transition": [40, 41],
        "expected_saved_rows": 42,
        "advect_initial_seeds_before_target_transition": True,
        "query_original_t0_seed_positions_at_row40": False,
        "r001_mismatch_corrected_by": "use state saved at row 40 after native-reference advection from row 0",
        "interpolation": "preserve the registered per-interval native x/v interpolation and RK2 tracer integration",
    }
    validate_alignment_contract(alignment)

    source = attribution["source_read_provenance"]
    if source.get("native_time_rows_read") != [40, 41]:
        raise ValueError("r001 source-window provenance changed")
    r001_binding = r001_result.get("binding", {})
    physical_definition = r001_binding.get("f4_definition", {})
    if (
        r001_binding.get("source_sha256") != source.get("sha256")
        or physical_definition.get("q") != 0.5
        or physical_definition.get("dp_m") != 0.0075
        or physical_definition.get("family_id") != "F4"
    ):
        raise ValueError("r001 does not bind the expected registered F4 physical/event definition")
    event_definition = physical_definition.get("event_definition", {})
    post_return = event_definition.get("post_return_window", {})
    if post_return.get("initial_horizon_s") != 4.34 or post_return.get("maximum_extended_horizon_s") != 8.68:
        raise ValueError("registered F4 event horizons differ from the immutable r001 definition")
    fixed_gate = dict(card["fixed_gate"])
    for key, value in candidate.FIXED_GATE.items():
        if fixed_gate.get(key) != value:
            raise ValueError(f"candidate card fixed gate differs from implementation for {key}")
    if fixed_gate.get("unknown_fraction_limit") != 0.01:
        raise ValueError("candidate card unknown-fraction gate changed")
    source_path = str(source["path"])
    output_namespace = Path("campaigns/core-v1/material/evidence") / R002_ID
    if (LAB / output_namespace).exists():
        raise FileExistsError(f"fresh r002 output namespace already exists: {output_namespace}")
    output_path = str(output_namespace / "trace.h5")
    command = [
        ".venv/bin/python", "-m", "scripts.f4_tallwall120_material",
        "--source", source_path,
        "--output", output_path,
        "--q", "0.5", "--dp-m", "0.0075", "--seeds", "512",
        "--substeps", "2", "--neighbour-variant", candidate.CANDIDATE_ID,
        "--stop-after", "41",
    ]

    parents = _parent_bindings(attribution)
    # The native trajectory is referenced by its already-recorded digest; it is
    # intentionally not opened or rehashed by this static design generator.
    candidate_binding = _binding(CANDIDATE_DIR / "candidate-card-v3.json", "static candidate parent")
    reviewer_binding = _binding(CANDIDATE_DIR / "terra-high-root-review-v4.json", "prior Terra High static review")
    tracer_binding = _binding(Path("scripts/f4_tallwall120_material.py"), "existing full-source material tracer")
    candidate_impl_binding = _binding(Path(candidate.__file__).resolve(), "unchanged registered v3 sampler")
    r001_executor_binding = _binding(
        Path("scripts/f4_supportcap_affine_query_bound_cpu_canary_execute_v1.py"),
        "historical r001 two-frame executor; not reused",
    )
    test_binding = _binding(
        Path("tests/test_f4_supportcap_r002_static_design_v1.py"), "static design tests"
    )

    return {
        "schema": SCHEMA,
        "record_id": "f4-supportcap-affine-query-bound-v3-r002-static-design-v1",
        "status": "static_temporal_alignment_design_candidate_for_independent_review",
        "review_scope": "static design only; no execution or qualification",
        "historical_attempt": {
            "attempt_id": R001_ID,
            "status": attribution["historical_attempt_status"],
            "modified": False,
            "retried": False,
            "trace_sha256": attribution["trace_provenance"]["sha256"],
            "failure_classification": attribution["failure_attribution"]["classification"],
        },
        "prospective_attempt": {
            "attempt_id": R002_ID,
            "fresh_output_namespace": output_path,
            "not_created": True,
            "command_not_run": command,
            "alignment": alignment,
            "denominator": 512,
            "q": 0.5,
            "dp_m": 0.0075,
            "substeps": 2,
            "candidate_id": candidate.CANDIDATE_ID,
            "support_cap": candidate.NEIGHBOURS,
            "error_estimator": candidate.ERROR_ESTIMATOR,
            "maximum_support_distance_m": candidate.MAXIMUM_SUPPORT_DISTANCE_M,
            "fixed_gate": fixed_gate,
            "all_gates_and_event_censoring_unchanged": True,
            "failure_denominator_retained": True,
            "event_observation_scope": {
                "purpose": "temporal-alignment prefix diagnostic only",
                "end_time_s": attribution["trace_provenance"]["time_s"][-1],
                "initial_event_horizon_s": post_return["initial_horizon_s"],
                "maximum_extended_event_horizon_s": post_return["maximum_extended_horizon_s"],
                "event_horizon_complete": False,
                "unobserved_event_policy": event_definition["unobserved_event_policy"],
                "residence_right_censored_if_unresolved": event_definition["residence"]["right_censored_if_unresolved"],
                "event_qualification_claim": "none; this prefix cannot qualify contact, propagation, return, or residence",
            },
        },
        "unchanged_registered_f4_physics_and_events": {
            "source_definition": physical_definition["source_definition"],
            "destination_definition": physical_definition["destination_definition"],
            "event_definition": event_definition,
            "stage": physical_definition["stage"],
        },
        "source_identity": {
            "path": source_path,
            "sha256": source["sha256"],
            "sha256_inherited_from": _repo_path(ATTRIBUTION),
            "opened_or_rehashed_by_this_design": False,
            "planned_native_rows_inclusive": [0, 41],
            "observed_r001_query_time_s": attribution["failure_attribution"]["query_time_s"],
        },
        "execution_authority": {
            "static_design_authorized": True,
            "independent_static_review_complete": False,
            "native_preflight_authorized": False,
            "cpu_canary_authorized": False,
            "solver_authorized": False,
            "gpu_authorized": False,
            "worker_or_queue_authorized": False,
            "new_explicit_runtime_authorization_required": True,
            "T1_numerical": False,
            "T2_macro": False,
            "T2_path": False,
            "qualification_credit": 0,
        },
        "design_assertions": [
            "initialize the original independent geometric seeds only against native row 0",
            "advance the independent tracer state across every native interval 0->1 through 40->41",
            "evaluate row 40->41 from the row-40 advected state, never from the original t=0 coordinates",
            "retain all 512 seeds and every registered reliability, support-distance, event, and censoring rule",
            "use a new output namespace; do not resume, overwrite, or otherwise alter r001",
            "a corrected time origin does not predict or guarantee passing any other fixed gate",
        ],
        "bindings": [
            _binding(ATTRIBUTION, "read-only r001 failure attribution"),
            *parents,
            candidate_binding,
            reviewer_binding,
            _binding(R001_DIR / "result.json", "r001 registered physical/event definition reference"),
            tracer_binding,
            candidate_impl_binding,
            r001_executor_binding,
            _binding(Path(__file__).resolve(), "static design generator"),
            test_binding,
        ],
        "execution_controls": {
            "native_hdf5_opened": False,
            "native_hdf5_rehashed": False,
            "trace_runner_started": False,
            "solver_started": False,
            "gpu_started": False,
            "worker_started": False,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "historical_r001_modified": False,
        },
    }


def write_recipe() -> Path:
    path = LAB / RECEIPT
    if path.exists():
        raise FileExistsError(f"refusing to overwrite static-design receipt: {path}")
    recipe = build_recipe()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(recipe, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write the new static receipt once")
    args = parser.parse_args()
    if args.write:
        print(_repo_path(write_recipe()))
    else:
        print(json.dumps(build_recipe(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
