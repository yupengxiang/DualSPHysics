from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts/ds_data02_stage2_f3_s2_fine_native_motive_audit_v2.py"
spec = importlib.util.spec_from_file_location("f3_s2_fine_native_motive_v2", SCRIPT)
assert spec and spec.loader
MODULE = importlib.util.module_from_spec(spec)
spec.loader.exec_module(MODULE)


ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
REQUEST = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/f3-s2-middle-external-v5-root-forward-162-001.json")
RECEIPT = ROOT / "families/F3/F3_S2_MATCHED_MIDDLE_SAME_CFL_ROOT_162/f3-s2-matched-middle-same-cfl-v5-root-162-001/execution-receipt.json"
PROOF = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F3_DP006_MIDDLE_EXTERNAL_ACTUAL_NATIVE_ROOT_VERIFICATION_162.json")


def _sha(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _actual_expected() -> dict[str, str]:
    request = json.loads(REQUEST.read_text(encoding="utf-8"))
    return {
        "case_id": request["case_id"],
        "attempt_id": request["attempt_id"],
        "family_id": request["family_id"],
        "physical_case_id": request["physical_case_id"],
        "output_root": request["storage_scope"]["output_root"],
        "request_sha256": _sha(REQUEST),
    }


def test_actual_external_v5_receipt_and_proof_join_exactly() -> None:
    expected = _actual_expected()
    result = MODULE.validate_external_v5_receipt(
        RECEIPT,
        expected_request_path=REQUEST,
        expected_request_sha256=expected["request_sha256"],
        expected_case_id=expected["case_id"],
        expected_attempt_id=expected["attempt_id"],
        expected_family_id=expected["family_id"],
        expected_physical_case_id=expected["physical_case_id"],
        expected_output_root=Path(expected["output_root"]),
        proof_path=PROOF,
    )
    assert result["receipt_status"] == "COMPLETED_DEVELOPMENT_UNKNOWN"
    assert result["execution_returncode"] == 0
    assert result["request_chain"]["case_id"] == expected["case_id"]
    assert result["filesystem_output_root"] == expected["output_root"]
    assert result["proof"]["sha256"] == _sha(PROOF)


def test_wrong_request_sha_is_rejected_even_when_receipt_is_completed() -> None:
    expected = _actual_expected()
    with pytest.raises(MODULE.FineMotiveBinderError, match="request SHA"):
        MODULE.validate_external_v5_receipt(
            RECEIPT,
            expected_request_path=REQUEST,
            expected_request_sha256="0" * 64,
            expected_case_id=expected["case_id"],
            expected_attempt_id=expected["attempt_id"],
            expected_family_id=expected["family_id"],
            expected_physical_case_id=expected["physical_case_id"],
            expected_output_root=Path(expected["output_root"]),
            proof_path=PROOF,
        )


def test_wrong_case_or_output_root_is_rejected() -> None:
    expected = _actual_expected()
    with pytest.raises(MODULE.FineMotiveBinderError, match="embedded request case_id"):
        MODULE.validate_external_v5_receipt(
            RECEIPT,
            expected_request_path=REQUEST,
            expected_request_sha256=expected["request_sha256"],
            expected_case_id="F3_WRONG_CASE",
            expected_attempt_id=expected["attempt_id"],
            expected_family_id=expected["family_id"],
            expected_physical_case_id=expected["physical_case_id"],
            expected_output_root=Path(expected["output_root"]),
            proof_path=PROOF,
        )
    with pytest.raises(MODULE.FineMotiveBinderError, match="output root"):
        MODULE.validate_external_v5_receipt(
            RECEIPT,
            expected_request_path=REQUEST,
            expected_request_sha256=expected["request_sha256"],
            expected_case_id=expected["case_id"],
            expected_attempt_id=expected["attempt_id"],
            expected_family_id=expected["family_id"],
            expected_physical_case_id=expected["physical_case_id"],
            expected_output_root=Path(expected["output_root"]).parent / "wrong-attempt",
            proof_path=PROOF,
        )


def test_wrong_attempt_is_rejected_even_when_case_and_output_match(tmp_path: Path) -> None:
    expected = _actual_expected()
    with pytest.raises(MODULE.FineMotiveBinderError, match="embedded request attempt_id"):
        MODULE.validate_external_v5_receipt(
            RECEIPT,
            expected_request_path=REQUEST,
            expected_request_sha256=expected["request_sha256"],
            expected_case_id=expected["case_id"],
            expected_attempt_id="wrong-attempt",
            expected_family_id=expected["family_id"],
            expected_physical_case_id=expected["physical_case_id"],
            expected_output_root=Path(expected["output_root"]),
            proof_path=PROOF,
        )
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    receipt["attempt_id"] = f"{expected['family_id']}/{expected['case_id']}/wrong-attempt"
    bad_receipt = tmp_path / "wrong-attempt-receipt.json"
    bad_receipt.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(MODULE.FineMotiveBinderError, match="receipt attempt_id"):
        MODULE.validate_external_v5_receipt(
            bad_receipt,
            expected_request_path=REQUEST,
            expected_request_sha256=expected["request_sha256"],
            expected_case_id=expected["case_id"],
            expected_attempt_id=expected["attempt_id"],
            expected_family_id=expected["family_id"],
            expected_physical_case_id=expected["physical_case_id"],
            expected_output_root=Path(expected["output_root"]),
            proof_path=None,
        )


def test_receipt_adapter_preserves_external_v5_chain_and_exposes_v1_shape() -> None:
    expected = _actual_expected()
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    external_ref = {"role": "terminal_receipt", "path": str(RECEIPT), "sha256": _sha(RECEIPT)}
    proof_ref = {"role": "terminal_proof", "path": str(PROOF), "sha256": _sha(PROOF)}
    request_ref = {"role": "root170_request", "path": str(REQUEST), "sha256": expected["request_sha256"]}
    adapter = MODULE.normalized_receipt_adapter(
        external_receipt=receipt,
        external_receipt_ref=external_ref,
        external_proof_ref=proof_ref,
        request_ref=request_ref,
        output_root=expected["output_root"],
        attempt_id=expected["attempt_id"],
    )
    assert adapter["schema"] == MODULE.RECEIPT_ADAPTER_SCHEMA
    assert adapter["status"] == "completed"
    assert adapter["returncode"] == 0
    assert adapter["request"]["path"] == str(REQUEST)
    assert adapter["request"]["sha256"] == expected["request_sha256"]
    assert adapter["output_root"] == expected["output_root"]
    assert adapter["normalized_from"]["receipt"]["sha256"] == _sha(RECEIPT)
    assert adapter["normalized_from"]["proof"]["sha256"] == _sha(PROOF)
    assert adapter["native_content_opened_by_adapter"] is False


def test_v1_terminal_validator_accepts_only_the_normalized_adapter_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = _actual_expected()
    # ROOT162 is the completed external-v5 positive fixture; patch only the
    # V1 case-specific constant so this test exercises receipt shape rather
    # than pretending the ROOT162 attempt is ROOT170.
    monkeypatch.setattr(MODULE._v1, "ROOT170_ATTEMPT_ID", expected["attempt_id"])
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    adapter = MODULE.normalized_receipt_adapter(
        external_receipt=receipt,
        external_receipt_ref={"path": str(RECEIPT), "sha256": _sha(RECEIPT)},
        external_proof_ref={"path": str(PROOF), "sha256": _sha(PROOF)},
        request_ref={"path": str(REQUEST), "sha256": expected["request_sha256"]},
        output_root=expected["output_root"],
        attempt_id=expected["attempt_id"],
    )
    MODULE._v1._validate_terminal_request_chain(
        {},
        {
            "root170_request": REQUEST,
            "root170_request_ref": {"sha256": expected["request_sha256"]},
            "solver_output_root": Path(expected["output_root"]) / "solver_output",
        },
        adapter,
    )


def test_payload_binder_records_stat_without_hashing_content(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = tmp_path / "PartOut_000.obi4"
    payload.write_bytes(b"native payload fixture")
    monkeypatch.setattr(MODULE, "sha256_file", lambda path: (_ for _ in ()).throw(AssertionError("payload content was hashed")))
    record = MODULE.payload_stat_ref(payload, "raw_partout")
    assert record["sha256"] == MODULE.PARENT_GUARD_COMPUTED
    assert record["content_opened_by_binder"] is False
    assert record["bytes"] == len(b"native payload fixture")
