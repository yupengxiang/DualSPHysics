from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts import f8_r008_native_fluid_table_bundle_review_v1 as review


def test_review_archive_binds_bundle_integration_and_keeps_execution_gates_closed() -> None:
    receipt = review.build_receipt()
    assert receipt["schema"] == review.SCHEMA
    assert receipt["status"] == "static_implementation_review_passed_no_execution_or_t1_credit"
    assert receipt["reviewer"]["model"] == "gpt-5.6-terra"
    assert receipt["reviewer"]["reasoning_effort"] == "high"
    assert receipt["reviewer"]["verdict"] == "PASS"
    assert receipt["reviewed_scope"]["revalidated_B_C_D_provenance_chain"] is True
    assert receipt["reviewed_scope"]["frozen_definition_and_control_source_bytes"] is True
    assert receipt["reviewed_scope"]["solver_or_T1_adjudication"] is False
    assert receipt["execution_authority"] == {
        "solver": False,
        "worker": False,
        "gpu": False,
        "queue": False,
        "T1_numerical": False,
        "qualification_credit": 0,
    }
    bindings = {item["path"]: item for item in receipt["evidence"]}
    for path in (
        "scripts/f8_r008_native_fluid_table_bundle_verifier_v1.py",
        "tests/test_f8_r008_native_fluid_table_bundle_verifier_v1.py",
        "scripts/f8_r008_native_fluid_table_v2.py",
        "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/native-fluid-table-schema-v2/design-review-v2/receipt.json",
        "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/per-case-provenance-implementation-review-v2/receipt.json",
    ):
        payload = (review.LAB / path).read_bytes()
        assert bindings[path]["bytes"] == len(payload)
        assert bindings[path]["sha256"] == hashlib.sha256(payload).hexdigest()


def test_review_archive_is_write_once_and_verifiable(tmp_path: Path) -> None:
    target = tmp_path / "receipt.json"
    review.write_receipt(target)
    assert review.verify_receipt(target)["reviewer"]["verdict"] == "PASS"
    with pytest.raises(FileExistsError, match="refusing to overwrite immutable"):
        review.write_receipt(target)
