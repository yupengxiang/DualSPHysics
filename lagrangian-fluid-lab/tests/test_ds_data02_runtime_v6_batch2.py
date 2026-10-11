from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_runtime_v6_batch2.py"
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("runtime_v6_batch2_test_module", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _ledger(data_root: Path) -> dict:
    return {
        "schema": "ds02.resource-ledger.v1",
        "deadline_utc": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
        "limits": {
            "gpu_seconds": 10_000_000,
            "cpu_core_seconds": 10_000_000,
            "new_storage_bytes": 100 * 1024**3,
            "qualification_attempts": 100,
            "production_attempts": 100,
            "storage_policy": "home_free_floor",
            "home_min_free_bytes": 100,
            "home_path": str(data_root),
        },
        "charges": [
            {
                "id": "legacy/old/charge-001",
                "gpu_seconds": 2.0,
                "cpu_core_seconds": 3.0,
                "new_storage_bytes": 4,
                "status": "completed",
            },
            {
                "id": "F1/UF_M1_BASELINE/solver-001",
                "gpu_seconds": 5.0,
                "cpu_core_seconds": 7.0,
                "new_storage_bytes": 8,
                "status": "completed",
            },
        ],
        "reservations": [],
        "attempts": [
            {"id": "legacy/old/charge-001", "kind": "cpu", "status": "completed"},
            {"id": "F1/UF_M1_BASELINE/solver-001", "kind": "qualification", "status": "completed"},
        ],
    }


def _admission(tmp_path: Path, *, ledger: dict | None = None) -> tuple[Path, Path, dict, dict]:
    data_root = tmp_path / "data-root"
    (data_root / "runtime").mkdir(parents=True)
    ledger = ledger or _ledger(data_root)
    _write_json(data_root / "runtime" / "resource-ledger.json", ledger)

    evidence = {}
    for milestone in ("M1", "M2", "M3"):
        receipt_path = tmp_path / f"{milestone.lower()}-receipt.json"
        _write_json(receipt_path, {"status": "completed", "receipt": milestone})
        path = tmp_path / f"{milestone.lower()}-complete.json"
        _write_json(
            path,
            {
                "schema": MODULE.MILESTONE_EVIDENCE_SCHEMA,
                "milestone": milestone,
                "status": "complete",
                "acceptance_status": "accepted",
                "receipts": [
                    {
                        "path": str(receipt_path),
                        "sha256": MODULE._sha256_file(receipt_path),
                        "status": "completed",
                    }
                ],
            },
        )
        evidence[milestone] = {
            "status": "complete",
            "acceptance_status": "accepted",
            "path": str(path),
            "sha256": MODULE._sha256_file(path),
        }
    cost_path = tmp_path / "m1-m3-cost-audit.json"

    request_path = tmp_path / "m4-request.json"
    request = {
        "family_id": "F1",
        "case_id": "UF_M4_CASE",
        "attempt_id": "solver-001",
        "output_storage": "home",
    }
    _write_json(request_path, request)

    prior_charged_ids = sorted(row["id"] for row in ledger["charges"])
    prior_usage = MODULE._usage(ledger["charges"])
    _write_json(
        cost_path,
        {
            "schema": MODULE.COST_AUDIT_SCHEMA,
            "status": "complete",
            "acceptance_status": "accepted",
            "charged_ids": prior_charged_ids,
            "prior_usage": prior_usage,
        },
    )

    admission = {
        "schema": MODULE.ADMISSION_SCHEMA,
        "status": "admitted",
        "issuer": "root",
        "immutable": True,
        "batch_index": 2,
        "previous_batch_index": 1,
        "evidence": evidence,
        "cost_audit": {
            "status": "complete",
            "acceptance_status": "accepted",
            "path": str(cost_path),
            "sha256": MODULE._sha256_file(cost_path),
        },
        "batch_limits": {
            "gpu_seconds": MODULE.BATCH_GPU_SECONDS,
            "cpu_core_seconds": MODULE.BATCH_CPU_CORE_SECONDS,
            "solver_attempts": MODULE.BATCH_SOLVER_ATTEMPTS,
            "additional_storage_bytes": 10 * 1024**3,
        },
        "parent_ledger_path": str(data_root / "runtime" / "resource-ledger.json"),
        "parent_limits": ledger["limits"].copy(),
        "parent_deadline_utc": ledger["deadline_utc"],
        "prior_charged_ids": prior_charged_ids,
        "prior_charge_row_sha256": {
            row["id"]: MODULE._row_hash(row) for row in ledger["charges"]
        },
        "prior_attempt_ids": sorted(row["id"] for row in ledger["attempts"]),
        "prior_attempt_row_sha256": {
            row["id"]: MODULE._row_hash(row) for row in ledger["attempts"]
        },
        "prior_reservation_ids": [],
        "prior_usage": prior_usage,
        "prior_charges_sha256": MODULE._rows_projection_hash(ledger["charges"]),
    }
    admission["payload_sha256"] = MODULE._payload_hash(admission)
    admission_path = tmp_path / "root-m4-batch-admission.json"
    _write_json(admission_path, admission)
    return admission_path, data_root, admission, ledger


def _grant(tmp_path: Path, admission_path: Path, admission: dict, request_path: Path) -> Path:
    grant = {
        "schema": MODULE.GRANT_SCHEMA,
        "status": "granted",
        "issuer": "root",
        "immutable": True,
        "batch_index": 2,
        "admission_path": str(admission_path),
        "admission_payload_sha256": admission["payload_sha256"],
        "request_path": str(request_path),
        "request_sha256": MODULE._sha256_file(request_path),
        "attempt_id": "F1/UF_M4_CASE/solver-001",
    }
    grant["payload_sha256"] = MODULE._payload_hash(grant)
    grant_path = tmp_path / "root-m4-request-grant.json"
    _write_json(grant_path, grant)
    return grant_path


def _reservation(*, attempt_id: str = "F1/UF_M4_CASE/solver-001", **updates: object) -> dict:
    result = {
        "id": attempt_id,
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 1,
        "gpu_seconds": 0,
        "cpu_core_seconds": 1,
        "new_storage_bytes": 1,
        "output_storage": "home",
    }
    result.update(updates)
    return result


def test_missing_incomplete_and_tampered_admissions_fail_closed(tmp_path: Path) -> None:
    admission_path, data_root, admission, _ = _admission(tmp_path)
    with pytest.raises(MODULE.BatchAdmissionError, match="regular|file"):
        MODULE.validate_admission(tmp_path / "missing.json", data_root=data_root)

    incomplete = json.loads(admission_path.read_text())
    incomplete["evidence"]["M3"]["status"] = "pending"
    incomplete["payload_sha256"] = MODULE._payload_hash(incomplete)
    _write_json(admission_path, incomplete)
    with pytest.raises(MODULE.BatchAdmissionError, match="not complete"):
        MODULE.validate_admission(admission_path, data_root=data_root)

    tampered = dict(admission)
    tampered["batch_limits"] = dict(admission["batch_limits"], additional_storage_bytes=11)
    # Keep the original payload digest: a field edit cannot become a new root admission.
    _write_json(admission_path, tampered)
    with pytest.raises(MODULE.BatchAdmissionError, match="payload hash"):
        MODULE.validate_admission(admission_path, data_root=data_root)


def test_evidence_content_tamper_is_rejected(tmp_path: Path) -> None:
    admission_path, data_root, admission, _ = _admission(tmp_path)
    evidence_path = Path(admission["evidence"]["M2"]["path"])
    evidence_path.write_text('{"status":"complete","tampered":true}\n')
    with pytest.raises(MODULE.BatchAdmissionError, match="M2 evidence hash"):
        MODULE.validate_admission(admission_path, data_root=data_root)


def test_complete_certificate_cannot_hide_pending_bound_receipt(tmp_path: Path) -> None:
    admission_path, data_root, admission, _ = _admission(tmp_path)
    certificate_path = Path(admission["evidence"]["M1"]["path"])
    certificate = json.loads(certificate_path.read_text())
    receipt_path = Path(certificate["receipts"][0]["path"])
    _write_json(receipt_path, {"status": "pending", "receipt": "M1"})
    certificate["receipts"][0]["sha256"] = MODULE._sha256_file(receipt_path)
    _write_json(certificate_path, certificate)
    admission["evidence"]["M1"]["sha256"] = MODULE._sha256_file(certificate_path)
    admission["payload_sha256"] = MODULE._payload_hash(admission)
    _write_json(admission_path, admission)
    with pytest.raises(MODULE.BatchAdmissionError, match="bound receipt is not terminal"):
        MODULE.validate_admission(admission_path, data_root=data_root)


def test_later_storage_bound_is_finite_and_below_operational_ceiling(tmp_path: Path) -> None:
    admission_path, data_root, admission, _ = _admission(tmp_path)
    admission["batch_limits"]["additional_storage_bytes"] = MODULE.MAX_ADDITIONAL_STORAGE_BYTES + 1
    admission["payload_sha256"] = MODULE._payload_hash(admission)
    _write_json(admission_path, admission)
    with pytest.raises(MODULE.BatchAdmissionError, match="hard bound"):
        MODULE.validate_admission(admission_path, data_root=data_root)


def test_historical_charge_or_parent_limit_erosion_is_rejected(tmp_path: Path) -> None:
    _, data_root, admission, ledger = _admission(tmp_path)
    ledger["charges"][0]["cpu_core_seconds"] = 99
    with pytest.raises(MODULE.BatchAdmissionError, match="historical charge baseline"):
        MODULE._check_batch2(ledger, _reservation(), {"output_storage": "home"}, admission)

    _, data_root, admission, ledger = _admission(tmp_path / "limits")
    ledger["limits"]["gpu_seconds"] += 1
    with pytest.raises(MODULE.BatchAdmissionError, match="parent limit changed"):
        MODULE._check_batch2(ledger, _reservation(), {"output_storage": "home"}, admission)


def test_batch2_rejects_foreign_heavy_concurrency_and_keeps_parent_guard(tmp_path: Path) -> None:
    _, data_root, admission, ledger = _admission(tmp_path)
    ledger["reservations"].append(
        _reservation(
            attempt_id="F2/UF_OTHER/foreign",
            kind="cpu",
            cpu_task_kind="conversion",
            gpu_seconds=20,
            cpu_core_seconds=20,
        )
    )
    with pytest.raises(RuntimeError, match="single heavy-task queue"):
        MODULE._check_batch2(
            ledger,
            _reservation(kind="qualification", cpu_task_kind=None, gpu_seconds=1),
            {"output_storage": "home"},
            admission,
        )


def test_batch2_incremental_caps_and_terminal_overrun_are_enforced(tmp_path: Path) -> None:
    _, data_root, admission, ledger = _admission(tmp_path)
    ledger["charges"].append(
        {
            "id": "F1/UF_M4_EXISTING/solver-001",
            "gpu_seconds": MODULE.BATCH_GPU_SECONDS,
            "cpu_core_seconds": 0,
            "new_storage_bytes": 0,
            "status": "completed",
        }
    )
    with pytest.raises(RuntimeError, match="gpu_seconds"):
        MODULE._check_batch2(
            ledger,
            _reservation(gpu_seconds=1),
            {"output_storage": "home"},
            admission,
        )

    ledger["charges"][-1]["gpu_seconds"] = 0
    ledger["charges"][-1]["new_storage_bytes"] = admission["batch_limits"]["additional_storage_bytes"]
    with pytest.raises(RuntimeError, match="new_storage_bytes"):
        MODULE._check_batch2(ledger, _reservation(), {"output_storage": "home"}, admission)

    overrun = MODULE._terminal_batch2(
        ledger,
        _reservation(),
        gpu_seconds=MODULE.BATCH_GPU_SECONDS + 1,
        cpu_core_seconds=0,
        storage_bytes=admission["batch_limits"]["additional_storage_bytes"] + 1,
        admission=admission,
    )
    assert overrun is not None
    assert "batch2" in overrun
    assert "gpu_seconds" in overrun["batch2"]
    assert "new_storage_bytes" in overrun["batch2"]


def test_terminal_parent_overrun_includes_all_historical_rows(tmp_path: Path) -> None:
    _, data_root, admission, ledger = _admission(tmp_path)
    # The UF baseline is 7 GPU seconds (2 legacy + 5 UF).  Lowering the live
    # parent limit must surface that historical use in the terminal audit;
    # accounting only post-admission rows would incorrectly report no parent
    # overrun here.
    ledger["limits"]["gpu_seconds"] = 6
    admission["parent_limits"]["gpu_seconds"] = 6
    overrun = MODULE._terminal_batch2(
        ledger,
        _reservation(),
        gpu_seconds=0,
        cpu_core_seconds=0,
        storage_bytes=0,
        admission=admission,
    )
    assert overrun is not None
    assert overrun["parent"]["gpu_seconds"]["used_before"] == 7


def test_request_binding_is_exact_and_no_admission_means_no_run(tmp_path: Path) -> None:
    admission_path, data_root, admission, _ = _admission(tmp_path)
    request_path = tmp_path / "m4-request.json"
    grant_path = _grant(tmp_path, admission_path, admission, request_path)
    request = json.loads(request_path.read_text())
    request["attempt_id"] = "solver-002"
    _write_json(request_path, request)
    with pytest.raises(MODULE.BatchAdmissionError, match="request changed|request hash mismatch"):
        MODULE.run_request(
            request_path,
            data_root=data_root,
            batch_admission=admission_path,
            batch_grant=grant_path,
        )
    with pytest.raises(MODULE.BatchAdmissionError, match="required"):
        MODULE.run_request(request_path, data_root=data_root)


def test_request_grant_is_immutable_and_admission_bound(tmp_path: Path) -> None:
    admission_path, data_root, admission, _ = _admission(tmp_path)
    request_path = tmp_path / "m4-request.json"
    grant_path = _grant(tmp_path, admission_path, admission, request_path)
    grant = json.loads(grant_path.read_text())
    grant["admission_payload_sha256"] = "0" * 64
    _write_json(grant_path, grant)
    with pytest.raises(MODULE.BatchAdmissionError, match="grant payload hash"):
        MODULE.validate_request_grant(
            grant_path,
            admission_path=admission_path,
            admission=admission,
            request_path=request_path,
        )


def test_home_floor_parent_policy_does_not_reactivate_nominal_byte_cap(tmp_path: Path) -> None:
    _, data_root, admission, ledger = _admission(tmp_path)
    # The real ledger may show historical bytes above its nominal legacy byte
    # field while home_free_floor is the active policy.  Batch admission must
    # preserve that policy and let v6's live statvfs guard decide.
    ledger["limits"]["new_storage_bytes"] = 1
    admission["parent_limits"]["new_storage_bytes"] = 1
    reservation = _reservation(new_storage_bytes=1)
    MODULE._check_batch2(ledger, reservation, {"output_storage": "home"}, admission)


def test_nas_headroom_is_checked_without_local_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, data_root, admission, ledger = _admission(tmp_path)
    monkeypatch.setattr(MODULE.v6, "_nas_available", lambda: MODULE.v6.NAS_HEADROOM_FLOOR_BYTES)
    reservation = _reservation(output_storage="upstream_nas", new_storage_bytes=1)
    with pytest.raises(RuntimeError, match="NAS headroom"):
        MODULE._check_batch2(ledger, reservation, {"output_storage": "upstream_nas"}, admission)


def test_history_preservation_allows_float_resummation_order(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path / 'data-root')
    for name, cpu in [('z', 1_000_000.0), ('b', 0.1), ('a', 0.2)]:
        ledger['charges'].append({'id': 'legacy/float/' + name, 'cpu_core_seconds': cpu,
                                  'gpu_seconds': 0.0, 'new_storage_bytes': 0,
                                  'status': 'completed'})
    _, _, admission, actual = _admission(tmp_path, ledger=ledger)
    reordered = MODULE._usage(sorted(actual['charges'], key=lambda row: row['id']))
    assert reordered['cpu_core_seconds'] != admission['prior_usage']['cpu_core_seconds']
    MODULE._baseline_rows_match(actual, admission)
    actual['charges'][-1]['cpu_core_seconds'] += 0.001
    with pytest.raises(MODULE.BatchAdmissionError, match='historical charge baseline changed'):
        MODULE._baseline_rows_match(actual, admission)
