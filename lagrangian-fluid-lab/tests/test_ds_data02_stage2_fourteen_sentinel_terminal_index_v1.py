from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_fourteen_sentinel_terminal_index_v1.py"
spec = importlib.util.spec_from_file_location("fourteen_terminal_index_v1", SCRIPT)
assert spec and spec.loader
MODULE = importlib.util.module_from_spec(spec)
spec.loader.exec_module(MODULE)


CURRENT = ROOT / "campaigns/ds-data-02/stage2/CURRENT336.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return path


def _ref(key: str, path: Path, role: str | None = None) -> dict:
    stat = path.stat()
    return {
        "key": key,
        "role": role or key,
        "path": str(path),
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "ctime_ns": stat.st_ctime_ns,
        "st_dev": stat.st_dev,
        "st_ino": stat.st_ino,
        "sha256": _sha(path),
        "source_scope": "JSON_ONLY",
    }


def _make_fixture(tmp_path: Path) -> Path:
    status_rows, next_rows, matrix_rows = [], [], []
    for family_number in range(1, 8):
        for side in (1, 2):
            sid = f"F{family_number}-S{side}"
            physical = f"F{family_number}_CASE_{side}"
            status_rows.append({
                "sentinel_id": sid,
                "family_id": f"F{family_number}",
                "physical_case_id": physical,
                "terminal_state": {"status": "HISTORIC", "category": "DIAGNOSTIC", "scientific_qualification": {key: "UNKNOWN" for key in MODULE.Q_KEYS}},
                "next_guarded_task": {"action": f"next {sid}", "success_condition": f"close {sid}"},
            })
            next_rows.append({"sentinel_id": sid, "family_id": f"F{family_number}", "physical_case_id": physical, "request_id": f"request-{sid}", "state": "SOURCE_READY_PARENT_REVIEW", "task_kind": "audit"})
            matrix_rows.append({"sentinel_id": sid, "family_id": f"F{family_number}", "physical_case_id": physical})
    status = _write(tmp_path / "status.json", {"schema": MODULE.SENTINEL_STATUS_SCHEMA, "sentinels": status_rows})
    nxt = _write(tmp_path / "next.json", {"schema": MODULE.SENTINEL_NEXT_SCHEMA, "requests": next_rows})
    matrix = _write(tmp_path / "terminal-matrix.json", {"schema": MODULE.TERMINAL_MATRIX_SCHEMA, "sentinels": matrix_rows})

    refs: dict[str, Path] = {
        "current336": CURRENT,
        "sentinel_status_v3": status,
        "sentinel_next_v3": nxt,
        "sentinel_terminal_matrix_v3": matrix,
    }
    terminal_bindings = []

    def completed(prefix: str, sid: str, family: str, physical: str, include_sentinel: bool = True) -> dict:
        out = tmp_path / f"out-{prefix}"
        out.mkdir()
        request_path = _write(tmp_path / f"{prefix}-request.json", {"schema": "ds02.request.v1", "family_id": family, "sentinel_id": sid if include_sentinel else None, "physical_case_id": physical if include_sentinel else None, "case_id": f"CASE_{prefix}", "attempt_id": f"ATTEMPT_{prefix}"})
        report_path = _write(out / f"{prefix}-report.json", {"schema": "test.report.v1", "source": prefix})
        receipt_path = _write(out / "execution-receipt.json", {"schema": "ds02.execution-receipt.v1", "request": json.loads(request_path.read_text()), "request_sha256": _sha(request_path), "status": "completed", "output_root": str(out)})
        proof_path = _write(tmp_path / f"{prefix}-proof.json", {"schema": MODULE.ROOT_PROOF_SCHEMA, "utc": "2026-10-09T00:00:00+00:00", "status": f"VERIFIED_ACTUAL_{prefix}", "request": str(request_path), "request_sha256": _sha(request_path), "receipt": str(receipt_path), "receipt_sha256": _sha(receipt_path), "report": str(report_path), "report_sha256": _sha(report_path), "guarded_receipt_status": "completed", "parent_reservation_released": True, "goal_complete": False})
        for key, path in ((f"{prefix}_request", request_path), (f"{prefix}_receipt", receipt_path), (f"{prefix}_report", report_path), (f"{prefix}_proof", proof_path)):
            refs[key] = path
        binding = {"sentinel_id": sid, "expected_family_id": family, "expected_physical_case_id": physical, "expected_request_case_id": f"CASE_{prefix}", "expected_attempt_id": f"ATTEMPT_{prefix}", "proof_key": f"{prefix}_proof", "request_key": f"{prefix}_request", "receipt_key": f"{prefix}_receipt", "report_key": f"{prefix}_report", "terminal_credit": include_sentinel}
        if not include_sentinel:
            binding.pop("sentinel_id")
            binding["sentinel_ids"] = ["F6-S1", "F6-S2"]
        return binding

    terminal_bindings.append(completed("f1", "F1-S1", "F1", "F1_CASE_1"))
    terminal_bindings.append(completed("f3", "F3-S2", "F3", "F3_CASE_2"))
    scope = completed("f6", "F6-S1", "infra", "F6_SCOPE", include_sentinel=False)
    pending_request = _write(tmp_path / "running-request.json", {"schema": "ds02.request.v1", "family_id": "F3", "sentinel_id": "F3-S2", "physical_case_id": "F3_CASE_2", "case_id": "CASE_RUNNING", "attempt_id": "ATTEMPT_RUNNING"})
    pending_checkpoint = _write(tmp_path / "running-checkpoint.json", {"schema": MODULE.RUNNING_SCHEMA, "utc": "2026-10-09T01:00:00+00:00", "status": "ACTUAL_RUNNING_F3_FINE_NOT_TERMINAL", "request": str(pending_request), "request_sha256": _sha(pending_request)})
    refs["running_request"] = pending_request
    refs["running_checkpoint"] = pending_checkpoint
    upstream = completed("upstream", "F1-S2", "infra", "F1_SCOPE", include_sentinel=False)
    refs_for_manifest = [_ref(key, path) for key, path in refs.items()]
    manifest = {
        "schema": MODULE.MANIFEST_SCHEMA,
        "current_binding": {"sha256": MODULE.CURRENT336_SHA256, "case_count": 336},
        "source_refs": refs_for_manifest,
        "terminal_bindings": terminal_bindings,
        "running_bindings": [{"sentinel_id": "F3-S2", "checkpoint_key": "running_checkpoint", "request_key": "running_request", "expected_request_case_id": "CASE_RUNNING", "expected_attempt_id": "ATTEMPT_RUNNING"}],
        "scope_only_completed_bindings": [scope],
        "upstream_matrix_binding": {"proof_key": "upstream_proof", "request_key": "upstream_request", "receipt_key": "upstream_receipt"},
    }
    manifest_path = tmp_path / "manifest.json"
    return _write(manifest_path, manifest)


def test_completed_and_running_attempts_are_separate(tmp_path: Path) -> None:
    result = MODULE.build_index(_make_fixture(tmp_path))
    assert result["coverage"]["sentinel_count"] == 14
    assert result["coverage"]["terminal_credit_sentinels"] == 2
    assert result["coverage"]["nonterminal_attempt_count"] == 1
    assert result["coverage"]["scope_only_completed_proof_count"] == 1
    f3 = next(row for row in result["sentinels"] if row["sentinel_id"] == "F3-S2")
    assert f3["terminal_credit"] is True
    assert len(f3["terminal_attempts"]) == 1
    assert f3["nonterminal_attempts"][0]["terminal_credit"] is False
    assert result["semantic_correction"]["native_omission_cases"] == 118
    assert result["semantic_correction"]["lifecycle_missing_exposure_rows"] == 290
    assert result["semantic_correction"]["non_native_rows"] == "NOT_REPORTED"


def test_case_attempt_receipt_mismatch_is_rejected(tmp_path: Path) -> None:
    manifest = _make_fixture(tmp_path)
    value = json.loads(manifest.read_text())
    value["terminal_bindings"][0]["expected_request_case_id"] = "WRONG_CASE"
    manifest.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(MODULE.IndexError, match="case/attempt mismatch"):
        MODULE.build_index(manifest)


def test_running_checkpoint_cannot_be_given_terminal_credit(tmp_path: Path) -> None:
    manifest = _make_fixture(tmp_path)
    value = json.loads(manifest.read_text())
    checkpoint_ref = next(ref for ref in value["source_refs"] if ref["key"] == "running_checkpoint")
    checkpoint = json.loads(Path(checkpoint_ref["path"]).read_text())
    checkpoint["status"] = "completed"
    Path(checkpoint_ref["path"]).write_text(json.dumps(checkpoint), encoding="utf-8")
    checkpoint_ref.update(_ref("running_checkpoint", Path(checkpoint_ref["path"])))
    manifest.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(MODULE.IndexError, match="no longer explicitly nonterminal"):
        MODULE.build_index(manifest)


def test_manifest_rejects_duplicate_source_keys(tmp_path: Path) -> None:
    manifest = _make_fixture(tmp_path)
    value = json.loads(manifest.read_text())
    value["source_refs"].append(dict(value["source_refs"][0]))
    manifest.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(MODULE.IndexError, match="duplicate source reference key"):
        MODULE.build_index(manifest)
