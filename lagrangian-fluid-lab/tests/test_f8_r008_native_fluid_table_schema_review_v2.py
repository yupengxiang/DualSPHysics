from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts import f8_r008_native_fluid_table_schema_review_v2 as review


def test_review_archive_binds_final_implementation_and_preserves_execution_boundary() -> None:
    receipt = review.build_receipt()
    assert receipt["status"] == "static_implementation_review_passed_no_execution_or_t1_credit"
    assert receipt["reviewer"]["model"] == "gpt-5.6-terra"
    assert receipt["reviewer"]["verdict"] == "PASS"
    assert receipt["reviewed_scope"]["verified_B_C_D_bundle_orchestration"] is False
    assert receipt["execution_authority"]["solver"] is False
    assert receipt["execution_authority"]["T1_numerical"] is False
    assert receipt["execution_authority"]["qualification_credit"] == 0
    bindings = {item["path"]: item for item in receipt["evidence"]}
    for path in (
        "scripts/f8_r008_native_fluid_table_v2.py",
        "tests/test_f8_r008_native_fluid_table_v2.py",
        "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/native-fluid-table-schema-v2/schema.json",
    ):
        payload = (review.LAB / path).read_bytes()
        assert bindings[path]["bytes"] == len(payload)
        assert bindings[path]["sha256"] == hashlib.sha256(payload).hexdigest()


def test_review_receipt_is_write_once_and_verifiable(tmp_path: Path) -> None:
    target = tmp_path / "receipt.json"
    review.write_receipt(target)
    assert review.verify_receipt(target)["reviewer"]["verdict"] == "PASS"
    with pytest.raises(FileExistsError, match="refusing to overwrite immutable"):
        review.write_receipt(target)
