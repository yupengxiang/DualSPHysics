from __future__ import annotations

import json
from pathlib import Path

from scripts.core_runtime import validate_spec
from scripts.f2_static_full_cup_runtime import make_job, materialize_runtime_prepared


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "campaigns/core-v1/cfd/f2-static-full-cup-matrix-prepared-v4/cells/00-CORE_F2_static_full_cup_volume_q0p00000000_dp0p010000000000_spatial/prepared.json"
CANDIDATE = ROOT / "campaigns/core-v1/cfd/f2-static-full-cup-volume-hold-candidate-v1.json"
ADMISSION = ROOT / "campaigns/core-v1/cfd/f2-static-full-cup-qualification-admission-v1.json"
REVIEW = ROOT / "campaigns/core-v1/cfd/f2-static-full-cup-runtime-root-review-smoke-v1.json"


def _materialize(tmp_path: Path) -> Path:
    output = tmp_path / "runtime"
    value = materialize_runtime_prepared(
        lab=ROOT,
        source_prepared=SOURCE,
        candidate_card=CANDIDATE,
        admission=ADMISSION,
        root_review=REVIEW,
        output=output,
        cell_index=0,
    )
    assert value["preflight_pass"] is True
    assert value["qualified"] is False
    return output / "prepared.json"


def test_runtime_view_binds_v4_cell_and_forbids_registration(tmp_path: Path) -> None:
    prepared_path = _materialize(tmp_path)
    value = json.loads(prepared_path.read_text())
    assert value["schema"] == "core.f2.static_full_cup.runtime_prepared.v1"
    assert value["cell_index"] == 0
    assert value["source_prepared"]["sha256"] == value["source_prepared_sha256"]
    assert value["root_review_decision"] == "approved_for_runtime_smoke"
    assert value["solver_launch_authorized"] is True
    assert value["registry_mutation_authorized"] is False
    assert value["config"]["time_max_s"] == 0.60
    assert value["config"]["output_interval_s"] == 0.02
    assert value["mass_preflight"]["mass_gate_pass"] is True
    bound = {Path(path).resolve() for path in value["inputs"]}
    assert CANDIDATE.resolve() in bound
    assert ADMISSION.resolve() in bound
    assert REVIEW.resolve() in bound


def test_make_job_is_scheduler_valid_and_candidate_only(tmp_path: Path) -> None:
    prepared_path = _materialize(tmp_path)
    spec_path = tmp_path / "job.json"
    spec = make_job(
        lab=ROOT,
        prepared_path=prepared_path,
        output=spec_path,
        job_id="f2-runtime-test-cell-00",
        host="ada",
    )
    validate_spec(spec)
    assert spec["host"] == "ada"
    assert spec["qualification_claim"] == "none"
    assert spec["qualification_only"] is True
    assert spec["cell_index"] == 0
    assert spec["registered_window_s"] == 0.60
    assert any(item["path"] == str(REVIEW.resolve()) for item in spec["input_files"])
    assert not any("registry" in key.lower() and value for key, value in spec.items() if isinstance(value, bool))


def test_runtime_preparation_does_not_create_solver_receipts(tmp_path: Path) -> None:
    prepared_path = _materialize(tmp_path)
    assert not (prepared_path.parent / "trajectory.h5").exists()
    assert not (prepared_path.parent / "result.json").exists()
    assert json.loads(prepared_path.read_text())["qualification_claim"].startswith("none;")
