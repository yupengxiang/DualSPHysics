from __future__ import annotations

import json
from pathlib import Path

from scripts.core_runtime import validate_spec
from scripts.f2_static_full_cup_boundary_repair_runtime import materialize
from scripts.f2_static_full_cup_runtime import make_job


ROOT = Path(__file__).resolve().parents[1]
REPAIR = ROOT / "campaigns/core-v1/cfd/f2-static-full-cup-boundary-repair-h1-cell0-v2/prepared.json"
CANDIDATE = ROOT / "campaigns/core-v1/cfd/f2-static-full-cup-volume-hold-candidate-v1.json"
ADMISSION = ROOT / "campaigns/core-v1/cfd/f2-static-full-cup-qualification-admission-v1.json"
REVIEW = ROOT / "campaigns/core-v1/cfd/f2-static-full-cup-boundary-repair-h1-runtime-root-review-v1.json"


def _materialize(tmp_path: Path) -> Path:
    output = tmp_path / "h1-runtime"
    value = materialize(
        lab=ROOT,
        repair_prepared=REPAIR,
        candidate=CANDIDATE,
        admission=ADMISSION,
        root_review=REVIEW,
        output=output,
    )
    assert value["preflight_pass"] is True
    assert value["qualified"] is False
    return output / "prepared.json"


def test_h1_runtime_view_binds_repair_and_forbids_registration(tmp_path: Path) -> None:
    prepared_path = _materialize(tmp_path)
    value = json.loads(prepared_path.read_text())
    assert value["schema"] == "core.f2.static_full_cup.runtime_prepared.v1"
    assert value["repair_id"] == "F2_static_full_cup_boundary_mdbc_h1_v1"
    assert value["root_review_decision"] == "approved_for_runtime_smoke"
    assert value["solver_arguments"] == ["-mdbc_noslip:1"]
    assert value["solver_launch_authorized"] is True
    assert value["registry_mutation_authorized"] is False
    assert value["qualification_claim"].startswith("none;")
    assert Path(value["source_prepared"]["path"]).resolve() == REPAIR.resolve()
    assert Path(value["root_review"]["path"]).resolve() == REVIEW.resolve()


def test_h1_runtime_job_is_scheduler_valid_and_single_cell(tmp_path: Path) -> None:
    prepared_path = _materialize(tmp_path)
    spec = make_job(
        lab=ROOT,
        prepared_path=prepared_path,
        output=tmp_path / "job.json",
        job_id="f2-h1-runtime-test-cell-00",
        host="ada",
    )
    validate_spec(spec)
    assert spec["host"] == "ada"
    assert spec["cell_index"] == 0
    assert spec["qualification_claim"] == "none"
    assert spec["qualification_only"] is True
    assert spec["registered_window_s"] == 0.60
    assert any(item["path"] == str(REVIEW.resolve()) for item in spec["input_files"])
