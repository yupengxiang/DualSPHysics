from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f3_s2_initial_support_audit_v2.py"
SPEC = importlib.util.spec_from_file_location("f3_s2_initial_support_v2", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_control_summary_is_finite_and_receipt_bound(tmp_path: Path) -> None:
    control = tmp_path / "CaseSloshingAccData.csv"
    control.write_text(
        "#Time;LinearAccX;LinearAccY\n"
        "0;0;-9.81\n"
        "0.5;1.0;-9.81\n",
        encoding="utf-8",
    )
    bound = MODULE.record(control)
    summary = MODULE.control_summary(control, bound)
    assert summary["sha256"] == hashlib.sha256(control.read_bytes()).hexdigest()
    assert summary["row_count"] == 2
    assert summary["time_first_s"] == 0.0
    assert summary["time_last_s"] == 0.5
    receipt = {"request": {"input_sha256": {"/source/CaseSloshingAccData.csv": bound["sha256"]}}}
    binding = MODULE.receipt_control_binding(receipt, bound, "fixture")
    assert binding["sha256"] == bound["sha256"]
    assert binding["path_count"] == 1


def test_receipt_control_digest_mismatch_is_rejected(tmp_path: Path) -> None:
    control = tmp_path / "CaseSloshingAccData.csv"
    control.write_text("#Time;A\n0;1\n", encoding="utf-8")
    bound = MODULE.record(control)
    receipt = {"request": {"input_sha256": {"/source/CaseSloshingAccData.csv": "0" * 64}}}
    with pytest.raises(ValueError):
        MODULE.receipt_control_binding(receipt, bound, "fixture")


def test_receipt_conflicting_control_digests_are_rejected(tmp_path: Path) -> None:
    control = tmp_path / "CaseSloshingAccData.csv"
    control.write_text("#Time;A\n0;1\n", encoding="utf-8")
    bound = MODULE.record(control)
    receipt = {
        "request": {
            "input_sha256": {
                "/source/prepared/CaseSloshingAccData.csv": bound["sha256"],
                "/source/legacy/CaseSloshingAccData.csv": "1" * 64,
            }
        }
    }
    with pytest.raises(ValueError, match="conflicting"):
        MODULE.receipt_control_binding(receipt, bound, "fixture")


def test_forward_request_keeps_deferred_vtk_unhashed() -> None:
    path = ROOT / (
        "campaigns/ds-data-02/stage2/requests/"
        "f3-s2-initial-support-audit-v2-root-forward-079-001/"
        "f3-s2-initial-support-audit-v2-request.json"
    )
    request = json.loads(path.read_text(encoding="utf-8"))
    assert request["deferred_input_file_count"] == 6
    assert all(item["sha256"] == "PARENT_GUARD_COMPUTED" for item in request["deferred_input_stats"].values())
    assert all(Path(item["path"]).suffix.lower() == ".vtk" for item in request["deferred_input_stats"].values())
    assert all(Path(item).suffix.lower() not in {".vtk", ".bi4", ".h5"} for item in request["input_files"])
    assert request["guard_policy"]["v8_deferred_fields_consumed"] is False
