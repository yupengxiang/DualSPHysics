from __future__ import annotations

import importlib.util
import json
import hashlib
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_whole_goal_qualification_gap_matrix_v2.py"
spec = importlib.util.spec_from_file_location("whole_goal_gap_matrix_v2", SCRIPT)
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


def _v30(*, family: str = "F1", physical: str = "CASE", lifecycle: str | None = None) -> dict:
    return {
        "case_key": f"{family}/{physical}",
        "error_qualification": {key: "UNKNOWN" for key in ("QN", "QE", "QI", "physical_fate", "dynamical_impact")},
        "quality_scope": {"status": "ELIGIBLE_STRICT_ANCHOR_TASK_SCOPE"},
        "finite_field_scope": {"lifecycle": lifecycle} if lifecycle is not None else {},
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
    assert all(row["next_request"]["status"] == "weak" for row in rows)
    assert all(row["next_request"]["temporality"] == "HISTORIC_FROZEN_INDEX_NOT_CURRENT_SCHEDULER" for row in rows)

    status_bad, next_bad = _sentinel_inputs(12)
    with pytest.raises(MODULE.MatrixError, match="exactly 14"):
        MODULE._sentinel_matrix(status_bad, next_bad)

    duplicate_status, duplicate_next = _sentinel_inputs()
    duplicate_status["sentinels"][1]["sentinel_id"] = duplicate_status["sentinels"][0]["sentinel_id"]
    with pytest.raises(MODULE.MatrixError, match="duplicate or missing sentinel IDs"):
        MODULE._sentinel_matrix(duplicate_status, duplicate_next)


def test_finite_scope_missing_is_not_reported_as_verified() -> None:
    v29 = _v29()
    del v29["qualification_dimensions"]["finite_fields"]
    row = MODULE._case_record(_current(), v29, _v30())
    assert row["finite_field_scope"]["status"] == "missing"
    assert row["lifecycle_scope"]["status"] == "missing"

    exposed = MODULE._case_record(_current(), _v29(), _v30(lifecycle="CLOSED_ZERO_NONFINITE_AND_NONPOSITIVE_MASS_DENSITY"))
    assert exposed["lifecycle_scope"]["status"] == "evidence_verified"


def _write_json(path: Path, value: dict) -> Path:
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return path


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _minimal_cli_manifest(tmp_path: Path) -> Path:
    current_path = ROOT / "campaigns/ds-data-02/stage2/CURRENT336.json"
    current = json.loads(current_path.read_text(encoding="utf-8"))
    rows = []
    for index, item in enumerate(current["cases"]):
        family = item["family_id"]
        physical = item["physical_case_id"]
        rows.append({"case_key": f"{family}/{physical}", "current": {"family_id": family, "physical_case_id": physical}, "qualification_dimensions": {"error_qualification": {key: "UNKNOWN" for key in MODULE.Q_KEYS}, "finite_fields": {"audit_status": "SCIENTIFIC_AUDIT_FIELD_FAILURES_EMPTY", "field_failures": []}}, "native_omission": {"native_count": 1, "native_motive": "position", "source_closure": {"status": "FULL_PROBE_SOURCE_CLOSED"}} if index < 118 else None})
    v29 = _write_json(tmp_path / "v29.json", {"schema": MODULE.V29_SCHEMA, "cases": rows})
    v30 = _write_json(tmp_path / "v30.json", [{"case_key": row["case_key"], "error_qualification": {key: "UNKNOWN" for key in MODULE.Q_KEYS}, "quality_scope": {"status": "ELIGIBLE_STRICT_ANCHOR_TASK_SCOPE"}} for row in rows])
    v30_data = json.loads(v30.read_text(encoding="utf-8"))
    v30.write_text(json.dumps({"schema": MODULE.V30_SCHEMA, "cases": v30_data}, sort_keys=True), encoding="utf-8")
    v27_product = _write_json(tmp_path / "v27-product.json", {"schema": MODULE.V27_SCHEMA, "family_cards": {family: {} for family in MODULE.FAMILIES}, "case_inventory": rows})
    v27_manifest = _write_json(tmp_path / "v27-manifest.json", {"schema": MODULE.V27_MANIFEST_SCHEMA, "cards": {family: {} for family in MODULE.FAMILIES}, "case_inventory": rows})
    v24 = _write_json(tmp_path / "v24.json", {"schema": MODULE.V24_SCHEMA, "cards": [{"family_id": family} for family in MODULE.FAMILIES]})
    v25 = _write_json(tmp_path / "v25.json", {"schema": MODULE.V25_SCHEMA, "components": [{"component_id": f"v24-anchor-{family}"} for family in MODULE.FAMILIES]})
    quality = _write_json(tmp_path / "quality.json", {"schema": MODULE.QUALITY_SCHEMA, "family_cards": [{"family_id": family, "quality_checks_closed": True, "task_eligibility": {key: "UNKNOWN" for key in ("QI", "QN", "QE")}} for family in MODULE.FAMILIES]})
    access = _write_json(tmp_path / "access.json", {"schema": MODULE.ACCESS_SCHEMA})
    detail = _write_json(tmp_path / "detail.json", {"schema": MODULE.DETAIL_SCHEMA, "case_count": 336, "detail_cards": [{} for _ in range(336)]})
    sentinel = []
    next_requests = []
    for index in range(14):
        family = f"F{index // 2 + 1}"
        sid = f"{family}-S{index % 2 + 1}"
        sentinel.append({"sentinel_id": sid, "family_id": family, "physical_case_id": f"{family}-CASE-{index}", "evidence": [{"file": {"path": str(tmp_path / f'evidence-{index}.json'), "sha256": 'a' * 64}}], "terminal_state": {"status": "COMPLETED", "category": "SOURCE_ONLY", "scientific_qualification": {key: "UNKNOWN" for key in ("QI", "QN", "QE")}}})
        next_requests.append({"sentinel_id": sid, "request_id": f"request-{index}", "state": "SOURCE_READY_PARENT_REVIEW", "task_kind": "audit", "qualification_after_task": {key: "UNKNOWN" for key in ("QI", "QN", "QE")}})
    sentinel_status = _write_json(tmp_path / "sentinel-status.json", {"schema": MODULE.SENTINEL_SCHEMA, "sentinels": sentinel})
    sentinel_next = _write_json(tmp_path / "sentinel-next.json", {"schema": MODULE.SENTINEL_NEXT_SCHEMA, "requests": next_requests})
    refs = {"current336": current_path, "v29_product": v29, "v27_product": v27_product, "v27_manifest": v27_manifest, "v30_product": v30, "v24_cards": v24, "v25_split": v25, "quality_report": quality, "access_report": access, "detail_report": detail, "sentinel_status": sentinel_status, "sentinel_next": sentinel_next, "native_loader": SCRIPT, "native_evaluator": SCRIPT, "v28_product": access, "v29_manifest": access, "v29_receipt": access, "v29_request": access, "v29_proof": access, "v30_manifest": access, "v30_receipt": access, "v30_request": access, "v30_proof": access, "v27_receipt": access, "v27_request": access, "v27_proof": access, "v24_request": access, "v24_proof": access, "v25_manifest": access, "v25_request": access, "v25_proof": access, "quality_receipt": access, "quality_request": access, "quality_proof": access, "access_receipt": access, "access_request": access, "access_proof": access, "detail_receipt": access, "detail_request": access, "detail_proof": access, "sentinel_reference": access, "sentinel_terminal_matrix": access, "sentinel_control_audit": access, "v28_request": access, "v28_proof": access, "v28_worker": SCRIPT, "v29_worker": SCRIPT, "v30_worker": SCRIPT}
    source_refs = []
    for key, path in refs.items():
        stat = path.stat()
        source_refs.append({"key": key, "role": key, "path": str(path), "bytes": stat.st_size, "sha256": _digest(path), "source_scope": "PYTHON_SOURCE_ONLY" if path.suffix == ".py" else "JSON_ONLY"})
    manifest = {"schema": MODULE.MANIFEST_SCHEMA, "source_refs": source_refs, "source_index": {"current336": {"path": str(current_path), "sha256": MODULE.CURRENT336_SHA256}}}
    return _write_json(tmp_path / "manifest.json", manifest)


def test_real_cli_build_subcommand_success_and_wrong_current_sha_rejection(tmp_path: Path) -> None:
    manifest = _minimal_cli_manifest(tmp_path)
    output = tmp_path / "matrix.json"
    success = subprocess.run(["/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python", str(SCRIPT), "build", "--manifest", str(manifest), "--output", str(output)], capture_output=True, text=True)
    assert success.returncode == 0, success.stderr
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["schema"] == MODULE.MATRIX_SCHEMA
    assert result["coverage"]["case_count"] == 336
    assert result["coverage"]["native_omission_cases"] == 118

    broken = json.loads(manifest.read_text(encoding="utf-8"))
    current_ref = next(ref for ref in broken["source_refs"] if ref["key"] == "current336")
    current_ref["sha256"] = "0" * 64
    broken["source_index"]["current336"]["sha256"] = "0" * 64
    broken_manifest = _write_json(tmp_path / "broken-manifest.json", broken)
    rejected = subprocess.run(["/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python", str(SCRIPT), "build", "--manifest", str(broken_manifest), "--output", str(tmp_path / "rejected.json")], capture_output=True, text=True)
    assert rejected.returncode != 0
    assert "digest changed" in rejected.stderr


def test_prepared_request_is_checkout_portable_and_payload_free() -> None:
    request_path = ROOT / "campaigns/ds-data-02/stage2/requests/whole-goal-qualification-gap-matrix-v2-root-prepared-176-001/whole-goal-qualification-gap-matrix-v2-request.json"
    request = json.loads(request_path.read_text(encoding="utf-8"))
    command_worker = Path(request["command"][1])
    assert request["launch_allowed"] is True
    assert request["cpu_task_kind"] == "audit"
    assert request["command"][2] == "build"
    assert request["command"][3] == "--manifest"
    assert request["read_policy"]["trajectory_h5_opened"] is False
    assert request["read_policy"]["part_bi4_opened"] is False
    assert request["input_sha256"][str(command_worker)]
    assert all(Path(path).suffix.lower() not in MODULE.FORBIDDEN_SUFFIXES for path in request["input_files"])
