"""Fail-closed diagnosis for the F3 coarse setup-variant decision.

This test is read-only.  It binds the tracked terminal summaries and the
current worker/scheduler bytes, then proves that the existing registered H2
and H1 candidates are historical negative diagnostics.  It intentionally does
not create a scheduler spec, attempt namespace, queue entry, or workload.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


LAB = Path(__file__).resolve().parents[1]
REPORT = LAB / "reports/F3-MATERIAL-COARSE-SETUP-VARIANT-DIAGNOSIS-2026-09-29.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _report() -> dict[str, object]:
    return json.loads(REPORT.read_text(encoding="utf-8"))


def test_diagnosis_is_fail_closed_and_does_not_propose_a_scheduler_variant() -> None:
    value = _report()

    assert value["schema"] == "core.material.f3.coarse.setup_variant_diagnosis.v1"
    assert value["status"] == "blocked_fail_closed_no_safe_variant"
    assert value["proposed_scheduler_spec"] is None
    assert value["candidate_review"]["decision"] == "no_new_scheduler_spec"
    assert value["scope"]["qualification_claim"] == "none"
    assert value["scope"]["credit"] == 0

    admission = value["external_admission"]
    assert admission == {
        "fresh_root_receipt_required": True,
        "scheduler_host_io_receipt_required": True,
        "cross_bind_current_source_and_inputs": True,
        "one_shot_namespace_required": True,
        "launch_authority_minted_by_diagnosis": False,
        "fresh_namespace_created": False,
        "submit_called": False,
        "workload_started": False,
        "gpu_started": False,
    }
    assert value["side_effects"] == {
        "queue_mutations": 0,
        "registry_mutations": 0,
        "ledger_mutations": 0,
        "denominator_mutations": 0,
        "gate_mutations": 0,
        "completion_mutations": 0,
        "plan_mutations": 0,
    }


def test_s2_s4_terminal_invariants_identify_the_common_reliability_source() -> None:
    value = _report()
    shared = value["terminal_comparison"]["shared"]
    s2 = value["terminal_comparison"]["s2"]
    s4 = value["terminal_comparison"]["s4"]

    assert shared["source_sha256"] == "3d178d8c5e6ee4057a10a384c9289df5723bcabbfe58850803cf54996c4a9575"
    assert shared["seed_count"] == 512
    assert shared["neighbour_variant"] == "baseline24"
    assert shared["neighbours"] == 24
    assert shared["regularization_m"] == 0.004
    assert shared["maximum_support_distance_m"] == 0.03
    assert shared["native_frame_count"] == 836
    assert shared["transition_count"] == 835
    assert shared["committed_frame"] == 835
    assert shared["mass_closed"] is True
    assert shared["unknown_fraction_monotone"] is True
    assert shared["unknown_fraction_max"] == 0.0625
    assert shared["unknown_gate_pass"] is False

    assert s2["substeps"] == 2
    assert s4["substeps"] == 4
    assert s2["source_rows"] == s4["source_rows"]
    assert [row["first_unreliable_frame"] for row in s2["source_rows"]] == [245, 335]
    assert [row["unknown_fraction_max"] for row in s2["source_rows"]] == [0.0625, 0.04296875]
    assert value["diagnosis"]["common_unknown_origin"] == "monotone_support_reliability_predicate"
    assert value["diagnosis"]["exact_component_status"] == "not_attributable_from_existing_terminal_receipts"


def test_registered_h2_and_h1_history_blocks_unsafe_new_setup_spec() -> None:
    value = _report()
    h2 = value["candidate_review"]["h2_k48"]
    h1 = value["candidate_review"]["h1_affine_bound"]

    assert h2["already_registered"] is True
    assert h2["neighbours"] == 48
    assert h2["same_source_substeps2_unknown_fraction_max"] == 0.046875
    assert h2["unknown_gate_pass"] is False
    assert h2["safe_new_spec"] is False

    assert h1["already_registered"] is True
    assert h1["neighbours"] == 24
    assert h1["same_source_substeps2_unknown_fraction_max"] == 0.06640625
    assert h1["unknown_gate_pass"] is False
    assert h1["safe_new_spec"] is False


def test_current_source_worker_scheduler_and_history_bindings_are_byte_closed() -> None:
    value = _report()
    bindings = value["input_bindings"]
    for item in bindings.values():
        path = LAB / item["path"]
        assert path.is_file(), item["path"]
        assert _sha(path) == item["sha256"], item["path"]

    worker = (LAB / "scripts/core_material.py").read_text(encoding="utf-8")
    neighbours = (LAB / "scripts/f3_material_neighbors.py").read_text(encoding="utf-8")
    engineering = (LAB / "scripts/f3_material_engineering.py").read_text(encoding="utf-8")
    assert "state[\"reliable\"] = usable" in worker
    assert "active\n        & g0\n        & g1" in worker
    assert "unsupported query stays in the output with NaN velocity" in neighbours
    assert "neighbours=24" in engineering
    assert "regularization_m=.004" in engineering
    assert "maximum_support_distance=.03" in engineering
    assert "no survivor renormalization" in engineering
