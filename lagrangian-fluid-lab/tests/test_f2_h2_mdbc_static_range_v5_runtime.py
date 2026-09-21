from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import f2_h2_mdbc_static_range_v5_runtime as runtime
from scripts import f2_h2_mdbc_static_range_v5_canary_evidence as evidence


LAB = Path(__file__).resolve().parents[1]
SOURCE = LAB / (
    "campaigns/core-v1/cfd/f2-h2-mdbc-static-range-qualification-v5/"
    "prepared-20260920-v5-all/cells/11-CORE_F2_H2_mdbc_static_range_v5_q0p75000000_"
    "dp0p007500000000_spatial_held_out/prepared.json"
)
CANDIDATE = LAB / "campaigns/core-v1/cfd/f2-h2-mdbc-static-range-qualification-candidate-v5.json"
MATRIX = LAB / (
    "campaigns/core-v1/cfd/f2-h2-mdbc-static-range-qualification-v5/"
    "prepared-20260920-v5-all/matrix-preparation.json"
)
ADMISSION = LAB / "campaigns/core-v1/cfd/f2-h2-mdbc-static-range-qualification-v5-runtime-admission-v2.json"
REVIEW = LAB / "campaigns/core-v1/cfd/f2-h2-mdbc-static-range-qualification-v5-runtime-root-review-cell11-v2.json"
ANCHOR = LAB / "campaigns/core-v1/cfd/prepared/F2_H2_mdbc_boundary_repair_canary_v2/prepared.json"


def test_runtime_view_binds_v5_cell_and_preserves_zero_credit(tmp_path: Path) -> None:
    value = runtime.materialize_runtime_prepared(
        lab=LAB, source_prepared=SOURCE, candidate=CANDIDATE, matrix=MATRIX,
        admission=ADMISSION, root_review=REVIEW, anchor=ANCHOR,
        output=tmp_path / "runtime", cell_index=11,
    )
    assert value["schema"] == runtime.RUNTIME_SCHEMA
    assert value["config"]["scope_id"] == runtime.SCOPE_ID
    assert value["config"]["case_id"].endswith("spatial_held_out")
    assert value["sampling"]["expected_fluid_particles"] == 56898
    assert value["sampling"]["fluid_boxes"][2]["counts"] == [42, 29, 16]
    assert value["mass_preflight"]["mass_gate_pass"] is True
    assert value["preflight_pass"] is True
    assert value["qualification_claim"].startswith("none")
    assert value["registry_mutation_authorized"] is False
    assert value["ledger_mutation_authorized"] is False
    assert value["config"]["time_max_s"] == 0.60
    assert json.loads((tmp_path / "runtime" / "prepared.json").read_text())["cell_index"] == 11


def test_runtime_view_rejects_changed_admission_binding(tmp_path: Path) -> None:
    bad = tmp_path / "bad-admission.json"
    payload = json.loads(ADMISSION.read_text())
    payload["source_preparation"]["sha256"] = "0" * 64
    bad.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="admission source_preparation"):
        runtime.materialize_runtime_prepared(
            lab=LAB, source_prepared=SOURCE, candidate=CANDIDATE, matrix=MATRIX,
            admission=bad, root_review=REVIEW, anchor=ANCHOR,
            output=tmp_path / "runtime", cell_index=11,
        )


def test_make_job_is_qualification_only_and_hash_bound(tmp_path: Path) -> None:
    runtime.materialize_runtime_prepared(
        lab=LAB, source_prepared=SOURCE, candidate=CANDIDATE, matrix=MATRIX,
        admission=ADMISSION, root_review=REVIEW, anchor=ANCHOR,
        output=tmp_path / "runtime", cell_index=11,
    )
    spec = runtime.make_job(
        lab=LAB, prepared_path=tmp_path / "runtime" / "prepared.json",
        output=tmp_path / "job.json", job_id="f2-h2-v5-cell11-runtime-smoke-001",
    )
    assert spec["schema"] == runtime.JOB_SCHEMA
    assert spec["cell_index"] == 11
    assert spec["qualification_only"] is True
    assert spec["qualification_claim"] == "none"
    assert spec["registered_window_s"] == 0.60
    assert any(item["path"].endswith("f2_h2_mdbc_static_range_v5_runtime.py") for item in spec["input_files"])
    assert json.loads((tmp_path / "job.json").read_text())["prepared_sha256"] == runtime.digest(tmp_path / "runtime" / "prepared.json")


def test_run_refuses_registry_enabled_runtime(tmp_path: Path) -> None:
    runtime.materialize_runtime_prepared(
        lab=LAB, source_prepared=SOURCE, candidate=CANDIDATE, matrix=MATRIX,
        admission=ADMISSION, root_review=REVIEW, anchor=ANCHOR,
        output=tmp_path / "runtime", cell_index=11,
    )
    path = tmp_path / "runtime" / "prepared.json"
    payload = json.loads(path.read_text())
    payload["registry_mutation_authorized"] = True
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="registry mutation"):
        runtime.run(lab=LAB, prepared_path=path, output=tmp_path / "product")


def test_canary_evidence_is_explicitly_zero_credit(tmp_path: Path) -> None:
    attempt = tmp_path / "attempt"
    product = attempt / "product"
    product.mkdir(parents=True)
    prepared = {"scope_id": evidence.SCOPE_ID}
    (product / "prepared.json").write_text(json.dumps(prepared))
    audit = {
        "hard_integrity_pass": True, "requested_horizon_reached": True,
        "endpoint_violation_particle_frames": 0, "saved_chord_crossing_count": 0,
        "structural": {"structural_pass": True, "frame_count": 2,
                        "particle_count": 3, "time_end_s": 0.6,
                        "initial_mass_kg": 1.0, "final_mass_kg": 1.0,
                        "mass_change_max_relative": 0.0},
        "event_window_complete": False, "event_window_status": "not_assessed",
    }
    (product / "audit.json").write_text(json.dumps(audit))
    result = {"scope_id": evidence.SCOPE_ID, "qualification_claim": "none; execution receipt",
              "case_id": "v5-test", "cell_index": 11,
              "runtime_prepared_sha256": "x", "structural": audit["structural"]}
    (product / "result.json").write_text(json.dumps(result))
    (product / "trajectory.h5").write_bytes(b"synthetic")
    receipt = {"execution_status": "succeeded", "returncode": 0,
               "allocation": {"gpu_index": 3}, "usage": {"wall_seconds": 1.0}}
    (attempt / "result.json").write_text(json.dumps(receipt))
    job = tmp_path / "job.json"
    review = tmp_path / "review.json"
    job_payload = {"scope_id": evidence.SCOPE_ID, "qualification_claim": "none",
                   "prepared_sha256": runtime.digest(product / "prepared.json"),
                   "job_id": "synthetic"}
    review_payload = {"scope_id": evidence.SCOPE_ID, "qualification_claim": "none", "registry_mutation": 0}
    review.write_text(json.dumps(review_payload))
    job_payload["root_review_sha256"] = runtime.digest(review)
    job.write_text(json.dumps(job_payload))
    out = tmp_path / "evidence.json"
    value = evidence.collect(attempt_dir=attempt, job_spec=job, root_review=review, output=out)
    assert value["matrix_credit"] == 0
    assert value["hard_integrity"]["pass"] is True
    assert value["execution_constraints"]["registry_mutation"] == 0
