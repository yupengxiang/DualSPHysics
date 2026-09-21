from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import f2_static_full_cup_boundary_repair_h2_runtime_root_review_v1 as review
from scripts import f2_static_full_cup_boundary_repair_h2_runtime_v1 as runtime


ROOT = Path(__file__).resolve().parents[1]
PREPARED = ROOT / "campaigns/core-v1/cfd/f2-static-full-cup-boundary-repair-h2-runtime-v1/prepared.json"


def test_runtime_root_review_is_one_cell_and_zero_credit() -> None:
    result = review.verify()
    assert result["ok"] is True
    value = json.loads(review.OUTPUT.read_text())
    assert value["authorized_cell_indices"] == [0]
    assert value["authorization"]["registry_mutation"] is False
    assert value["authorization"]["qualification_credit"] == 0
    assert value["execution_policy"]["same_input_retry"] is False
    assert value["execution_policy"]["matrix_expansion"] is False


def test_h2_runtime_prepared_manifest_binds_fresh_input_and_no_registry() -> None:
    value = json.loads(PREPARED.read_text())
    assert value["schema"] == "core.f2.static_full_cup.runtime_prepared.v1"
    assert value["repair_id"] == runtime.REPAIR_ID
    assert value["config"]["case_id"] == runtime.CASE_ID
    assert value["config"]["recipe"] == "mdbc_native"
    assert value["solver_arguments"] == ["-mdbc_noslip:1"]
    assert value["preflight_pass"] is True
    assert value["qualified"] is False
    assert value["qualification_claim"].startswith("none;")
    assert value["registry_mutation_authorized"] is False
    assert value["matrix_expansion_authorized"] is False
    assert value["sampling"]["expected_fluid_particles"] == 23100
    assert value["mass_preflight"]["mass_gate_pass"] is True
    assert value["config"]["initial_condition"]["support_clearance_m"] == pytest.approx(0.039)
    assert all(Path(path).is_file() for path in value["inputs"])


def test_h2_make_job_is_a_spec_only_operation(tmp_path: Path) -> None:
    spec_path = tmp_path / "job.json"
    value = runtime.make_job(
        prepared_path=PREPARED,
        output=spec_path,
        job_id="f2-static-full-cup-boundary-repair-h2-cell0-canary-v1",
        host="ada",
    )
    assert value["category"] == "static_hold_canary"
    assert value["qualification_claim"] == "none"
    assert value["registry_mutation_authorized"] is False
    assert value["prepared_case_id"] == runtime.CASE_ID
    assert value["argv"][1].endswith("f2_static_full_cup_runtime.py")
    assert spec_path.is_file()
