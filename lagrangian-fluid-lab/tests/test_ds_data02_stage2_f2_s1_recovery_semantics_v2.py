from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_s1_recovery_semantics_v2.py"
spec = importlib.util.spec_from_file_location("f2_recovery_semantics_v2", SCRIPT)
assert spec and spec.loader
MODULE = importlib.util.module_from_spec(spec)
spec.loader.exec_module(MODULE)


ACTUAL_DIR = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/"
    "STAGE2_F2_S1_TRAJECTORY_LABELS_RECOVERY_V2/"
    "f2-s1-trajectory-labels-recovery-v2-root-forward-001"
)
REPORT = ACTUAL_DIR / "f2-s1-trajectory-labels-recovery-v2.json"
RECEIPT = ACTUAL_DIR / "execution-receipt.json"


@pytest.mark.skipif(not REPORT.is_file() or not RECEIPT.is_file(), reason="actual F2 recovery product is not mounted")
def test_actual_recovery_requires_exact_producer_and_does_not_open_h5(tmp_path: Path) -> None:
    output = tmp_path / "recovery-v2.json"
    result = MODULE.build(REPORT, RECEIPT, output)
    assert result["status"] == "PASS_RECOVERY_SEMANTICS_EXACT_PRODUCER_RECEIPT_BOUND"
    assert result["producer_binding"]["output_root"] == str(ACTUAL_DIR.resolve())
    assert result["producer_binding"]["stable_source_binding_count"] >= 7
    assert result["read_scope"]["this_worker_opened_h5"] is False


@pytest.mark.skipif(not REPORT.is_file() or not RECEIPT.is_file(), reason="actual F2 recovery product is not mounted")
def test_completed_wrong_case_receipt_without_output_object_is_rejected(tmp_path: Path) -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    # The historical v1 accepted a completed receipt with no output object.
    # Keep the same completed status/return code but substitute another case's
    # request identity; v2 must reject it before any semantic credit.
    wrong = copy.deepcopy(receipt)
    wrong_request = copy.deepcopy(receipt["request"])
    wrong_request["case_id"] = "STAGE2_OTHER_COMPLETED_CASE"
    wrong_request["attempt_id"] = "other-completed-attempt"
    wrong["request"] = wrong_request
    wrong["output_root"] = str(ACTUAL_DIR.resolve())
    wrong_path = tmp_path / "wrong-completed-receipt.json"
    wrong_path.write_text(json.dumps(wrong, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(MODULE.RecoverySemanticsError, match="case identity"):
        MODULE.validate_producer_receipt(REPORT, report, wrong_path, wrong)


@pytest.mark.skipif(not REPORT.is_file() or not RECEIPT.is_file(), reason="actual F2 recovery product is not mounted")
def test_v2_request_has_no_h5_inputs_and_binds_runtime_and_worker_roots(tmp_path: Path) -> None:
    request_path = tmp_path / "request.json"
    request = MODULE.make_request(
        REPORT,
        RECEIPT,
        request_path,
        runtime_root=Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics"),
        worker_root=Path("/home/jade/.codex/worktrees/ds-data-02-stage2-forensics/DualSPHysics"),
    )
    assert request["launch_allowed"] is True
    assert request["request_schema"] == "ds02.stage2.f2-s1-recovery-semantics-v2-request.v1"
    assert not [path for path in request["input_files"] if Path(path).suffix.lower() in {".h5", ".hdf5", ".bi4", ".bi2", ".bi1"}]
    assert all(Path(path).is_file() for path in request["input_files"])


def test_synthetic_receipt_without_output_root_is_rejected() -> None:
    report = {
        "schema": MODULE.REPORT_SCHEMA,
        "status": "TRAJECTORY_LABELS_RECOVERED_FROM_COMPLETED_H5",
        "physical_case_id": "P",
        "case_key": "F2/P",
        "source_contract": {
            "current": {"path": "/tmp/CURRENT.json", "sha256": "a" * 64},
            "trajectory_hdf5": {"path": "/tmp/source.h5", "sha256": "b" * 64},
            "contract": {"current": {"path": "/tmp/CURRENT.json", "sha256": "a" * 64}},
        },
        "output_hdf5": {"path": "/tmp/labels.h5", "sha256": "c" * 64},
        "recovery": {"source_trajectory_h5_opened": False, "source_trajectory_h5_rehashed": False, "input_h5_sha256": "c" * 64},
        "read_policy": {"h5_opened": True, "trajectory_content_opened": True},
    }
    # Validate the producer gate directly after the report helper would have
    # accepted the report shape.  A completed status alone earns no credit.
    receipt = {"schema": MODULE.RECEIPT_SCHEMA, "status": "completed", "returncode": 0, "request": {}}
    with pytest.raises(MODULE.RecoverySemanticsError, match="request"):
        MODULE.validate_producer_receipt(Path("/tmp/report.json"), report, Path("/tmp/execution-receipt.json"), receipt)
