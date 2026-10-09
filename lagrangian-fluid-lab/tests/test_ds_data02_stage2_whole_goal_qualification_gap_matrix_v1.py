from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_whole_goal_qualification_gap_matrix_v1.py"
spec = importlib.util.spec_from_file_location("whole_goal_gap_matrix_v1", SCRIPT)
assert spec and spec.loader
MODULE = importlib.util.module_from_spec(spec)
spec.loader.exec_module(MODULE)


def _current(family: str = "F1", physical: str = "CASE") -> dict:
    return {
        "current_index": 0,
        "family_id": family,
        "physical_case_id": physical,
    }


def _v29(*, native: bool = False, known_q: bool = False, family: str = "F1", physical: str = "CASE") -> dict:
    q = {key: ("KNOWN" if known_q else "UNKNOWN") for key in ("QN", "QE", "QI", "physical_fate", "dynamical_impact")}
    result = {
        "case_key": f"{family}/{physical}",
        "current": {"family_id": family, "physical_case_id": physical},
        "qualification_dimensions": {
            "error_qualification": q,
            "finite_fields": {"audit_status": "SCIENTIFIC_AUDIT_FIELD_FAILURES_EMPTY", "field_failures": []},
        },
        "native_omission": None,
    }
    if native:
        result["native_omission"] = {
            "native_count": 2,
            "native_motive": "position",
            "source_closure": {"status": "FULL_PROBE_SOURCE_CLOSED"},
            "source_visible_mass": {"missing_source_visible_fraction_lower_bound": 0.001},
            "saved_censoring": {"first_missing_window_s": [0.1, 0.2]},
        }
    return result


def _v30(*, family: str = "F1", physical: str = "CASE") -> dict:
    return {
        "case_key": f"{family}/{physical}",
        "error_qualification": {key: "UNKNOWN" for key in ("QN", "QE", "QI", "physical_fate", "dynamical_impact")},
        "quality_scope": {"status": "ELIGIBLE_STRICT_ANCHOR_TASK_SCOPE"},
    }


def test_case_record_separates_native_identity_from_scientific_qualification() -> None:
    row = MODULE._case_record(_current(), _v29(native=True), _v30())
    assert row["record_status"] == "evidence_verified"
    assert row["omission_scope"]["status"] == "evidence_verified"
    assert row["omission_scope"]["native_motive"] == "position"
    assert row["qualification_gap"]["QI"] == "UNKNOWN"
    assert row["qualification_gap"]["physical_fate"] == "UNKNOWN"


def test_case_record_marks_non_native_case_explicitly_not_applicable() -> None:
    row = MODULE._case_record(_current(), _v29(), _v30())
    assert row["omission_scope"]["status"] == "not_applicable"
    assert row["omission_scope"]["native_count"] == 0
    assert row["qualification_gap"]["QN"] == "UNKNOWN"


def test_case_record_rejects_identity_or_qualification_contradictions() -> None:
    known = MODULE._case_record(_current(), _v29(known_q=True), _v30())
    assert known["record_status"] == "contradicted"
    assert "v29_qualification_not_UNKNOWN" in known["case_explanation"]["issues"]

    wrong_key = MODULE._case_record(_current(), _v29(family="F2"), _v30())
    assert wrong_key["record_status"] == "contradicted"
    assert "v29_family_mismatch" in wrong_key["case_explanation"]["issues"]


def _sentinel_inputs(count: int = 14) -> tuple[dict, dict]:
    rows = []
    requests = []
    for index in range(count):
        family = f"F{index // 2 + 1}"
        sid = f"{family}-S{index % 2 + 1}"
        rows.append({
            "sentinel_id": sid,
            "family_id": family,
            "physical_case_id": f"{family}-CASE-{index}",
            "evidence": [{"file": {"path": f"/tmp/evidence-{index}.json", "sha256": "a" * 64}}],
            "terminal_state": {"status": "COMPLETED", "category": "SOURCE_ONLY", "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}},
        })
        requests.append({
            "sentinel_id": sid,
            "state": "SOURCE_READY_PARENT_REVIEW",
            "request_id": f"request-{index}",
            "task_kind": "audit",
            "qualification_after_task": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        })
    return {"schema": MODULE.SENTINEL_SCHEMA, "sentinels": rows}, {"schema": MODULE.SENTINEL_NEXT_SCHEMA, "requests": requests}


def test_sentinel_matrix_requires_exact_two_per_family() -> None:
    status, next_requests = _sentinel_inputs()
    rows, by_family = MODULE._sentinel_matrix(status, next_requests)
    assert len(rows) == 14
    assert all(len(by_family[family]) == 2 for family in MODULE.FAMILIES)

    status_bad, next_bad = _sentinel_inputs(12)
    with pytest.raises(MODULE.MatrixError, match="exactly 14"):
        MODULE._sentinel_matrix(status_bad, next_bad)


def test_prepared_request_is_checkout_portable_and_payload_free() -> None:
    request_path = ROOT / "campaigns/ds-data-02/stage2/requests/whole-goal-qualification-gap-matrix-v1-root-prepared-175-001/whole-goal-qualification-gap-matrix-v1-request.json"
    request = json.loads(request_path.read_text(encoding="utf-8"))
    command_worker = Path(request["command"][1])
    assert request["launch_allowed"] is True
    assert request["read_policy"]["trajectory_h5_opened"] is False
    assert request["read_policy"]["part_bi4_opened"] is False
    assert request["input_sha256"][str(command_worker)]
    assert all(Path(path).suffix.lower() not in MODULE.FORBIDDEN_SUFFIXES for path in request["input_files"])
