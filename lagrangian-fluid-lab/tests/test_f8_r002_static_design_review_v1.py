from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import f8_r002_static_design_review_v1 as review_module


ROOT = Path(__file__).resolve().parents[1]


def test_r002_static_design_is_fresh_zero_credit_and_nonexecuting() -> None:
    # The review recorded target absence before the separately-authorized
    # materialization.  Rebuilding it afterwards must fail closed; verify the
    # immutable historical receipt instead.
    review = json.loads(review_module.OUTPUT.read_text(encoding="utf-8"))
    assert review["status"] == "r002_static_design_review_passed_inputs_not_authorized"
    assert review["static_constraint_gaps"] == []
    assert review["scope_id"] == "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R002"
    assert review["qualification_claim"] == "none"
    assert review["qualification_credit"] == 0
    assert review["r002_namespace"]["all_targets_absent_at_review"] is True
    assert review["precommitted_input_bytes"]["materialized"] is False
    assert review["next_authorization_required"]["kind"] == "one-time r002 static input materialization only"
    assert all(value is False for key, value in review["execution_controls"].items()
               if key.endswith(("written", "invoked", "started")))
    assert all(review["execution_controls"][key] == 0 for key in (
        "queue_mutation", "registry_mutation", "ledger_mutation", "denominator_mutation"))


def test_r002_proves_finite_walls_and_new_control_copy_path() -> None:
    review = json.loads(review_module.OUTPUT.read_text(encoding="utf-8"))
    proof = review["finite_wall_proof"]
    assert proof["shape_mode"] == "dp | bound"
    assert proof["lower_wall_z_interval_m"][1] == proof["fluid_z_interval_m"][0]
    assert proof["upper_wall_z_interval_m"][0] == proof["fluid_z_interval_m"][1]
    assert proof["lower_wall_z_interval_m"][0] < proof["lower_wall_z_interval_m"][1]
    assert proof["upper_wall_z_interval_m"][0] < proof["upper_wall_z_interval_m"][1]
    copy = review["control_dependency_copy_proof"]
    assert copy["definition_relative_reference"].endswith("_r002_acceleration.csv")
    assert "/generated/acceleration/" in copy["required_generated_copy"]
    assert copy["r001_path_explicitly_forbidden"] not in copy["definition_relative_reference"]
    assert "positive" in " ".join(review["expected_cpu_preflight_hard_gates"])


def test_committed_receipt_is_hash_closed_and_immutable(tmp_path: Path) -> None:
    review = json.loads(review_module.OUTPUT.read_text(encoding="utf-8"))
    assert review["status"] == "r002_static_design_review_passed_inputs_not_authorized"
    for item in review["bindings"]:
        # This test may evolve to exercise later fail-closed transitions.
        if item["path"] == "tests/test_f8_r002_static_design_review_v1.py":
            continue
        path = ROOT / item["path"]
        assert path.is_file()
        assert path.stat().st_size == item["bytes"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]
    target = tmp_path / "receipt.json"
    review_module.write_review(target)
    with pytest.raises(FileExistsError, match="immutable F8 r002 static review"):
        review_module.write_review(target)
