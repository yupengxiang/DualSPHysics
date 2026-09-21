from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.f2_dynamic_third_family_runtime import create_job


def _paths() -> dict[str, Path]:
    root = Path(__file__).resolve().parents[1]
    base = root / "campaigns/core-v1/cfd"
    return {
        "lab": root,
        "prepared": base / "f2-dynamic-third-family-dbc-duration-q0p75-preflight-v1/prepared.json",
        "candidate": base / "f2-dynamic-third-family-dbc-duration-candidate-card-v1.json",
        "matrix": base / "f2-dynamic-third-family-dbc-duration-matrix-v1.json",
        "lineage": base / "f2-dynamic-third-family-dbc-duration-lineage-clarification-v1.json",
        "review": base / "f2-dynamic-third-family-dbc-duration-root-review-first-row-v1.json",
    }


def test_first_row_job_is_hash_bound_and_registry_free(tmp_path: Path) -> None:
    paths = _paths()
    review = paths.pop("review")
    output = tmp_path / "job.json"
    job = create_job(output=output, **paths, review_path=review)
    assert job["job_id"] == "f2-dynamic-third-family-dbc-duration-q0p75-dp0075-canary-001"
    assert job["matrix_index"] == 11
    assert job["parameter_q"] == 0.75
    assert job["parameter_dp_m"] == 0.0075
    assert job["qualification_claim"] == "none"
    assert job["registry_mutation_authorized"] is False
    assert len(job["input_files"]) == 7
    assert all(item["sha256"] and item["bytes"] > 0 for item in job["input_files"])
    saved = json.loads(output.read_text())
    assert saved["required_outputs"] == [
        "product/result.json", "product/trajectory.h5", "product/audit.json", "product/observations.json"
    ]


def test_runtime_adapter_rejects_non_approved_review(tmp_path: Path) -> None:
    paths = _paths()
    review = json.loads(paths.pop("review").read_text())
    review["decision"] = "draft_pending_root_review"
    bad_review = tmp_path / "bad-review.json"
    bad_review.write_text(json.dumps(review))
    output = tmp_path / "job.json"
    with pytest.raises(ValueError, match="does not authorize"):
        create_job(output=output, **paths, review_path=bad_review)
