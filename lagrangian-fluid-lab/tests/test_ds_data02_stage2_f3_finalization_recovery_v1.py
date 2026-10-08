from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f3_finalization_recovery_v1.py"
FAILED = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3/"
    "STAGE2_F3_FULL836_RAW_ANCHOR_TYPED_COMPARE_V2/"
    "f3-full836-raw-anchor-typed-compare-v2-root-v8-001/execution-receipt.json"
)


def _module():
    spec = importlib.util.spec_from_file_location("f3_recovery_test_module", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _canonical(value: dict) -> str:
    return hashlib.sha256(json.dumps(
        {key: item for key, item in value.items() if key != "sha256"},
        sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str,
    ).encode()).hexdigest()


def test_build_is_metadata_only_and_preserves_failed_receipt(tmp_path: Path) -> None:
    module = _module()
    request_path = tmp_path / "f3-recovery-request.json"
    request = module.build_request(failed_receipt=FAILED, output=request_path)
    assert request["status"] == "READY_FOR_PARENT_IO_SLOT"
    assert request["role"] == "DEVELOPMENT_PHASE_RECOVERY_ONLY"
    assert request["original_failed_receipt"]["status"] == "failed"
    assert request["original_failed_receipt"]["never_upgrade"] is True
    assert request["typed_output"]["content_hash_at_build"] is False
    assert request["completed_phase_evidence"]["raw_tree"]["content_hash_at_build"] is False
    assert request["execution"]["raw_bi4_redecode"] is False
    assert request["qualification"] == module.UNKNOWN
    assert request["sha256"] == _canonical(request)
    prepared = module.prepare(request_path)
    assert prepared["status"] == "READY_FOR_PARENT_IO_SLOT"
    assert prepared["typed_hdf5_opened"] is False
    assert prepared["raw_tree_content_read"] is False
    assert prepared["estimated_content_read_bytes"] > 9_000_000_000


def test_wrong_typed_sha_is_rejected_without_opening_hdf5(tmp_path: Path) -> None:
    module = _module()
    typed = tmp_path / "typed.h5"
    typed.write_bytes(b"typed-fixture")
    with pytest.raises(module.RecoveryError, match="typed HDF5 content SHA"):
        module._verify_typed_content(typed, "0" * 64, typed.stat().st_size)


def test_wrong_current_trajectory_and_raw_tree_sha_fail_closed(tmp_path: Path) -> None:
    module = _module()
    catalog = {"cases": [{
        "family_id": "F3",
        "physical_case_id": "F3_FIXTURE",
        "trajectory": {
            "path": str((tmp_path / "reference.h5").resolve()),
            "producer_declared_sha256": "1" * 64,
        },
    }]}
    with pytest.raises(module.RecoveryError, match="producer SHA"):
        module._find_current_row(catalog, tmp_path / "reference.h5", "2" * 64)

    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "Part_0000.bi4").write_bytes(b"raw-fixture")
    with pytest.raises(module.RecoveryError, match="raw tree before hash"):
        module._verify_raw_tree(raw, "0" * 64)


def test_recovery_run_requires_parent_io_approval(tmp_path: Path) -> None:
    module = _module()
    request_path = tmp_path / "request.json"
    module.build_request(failed_receipt=FAILED, output=request_path)
    with pytest.raises(module.RecoveryError, match="io-slot-approved"):
        module.run(request_path, tmp_path / "report.json", io_slot_approved=False)
