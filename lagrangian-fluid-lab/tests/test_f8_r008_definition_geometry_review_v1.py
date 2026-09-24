from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts import f8_r008_definition_geometry_review_v1 as review


def test_review_receipt_binds_geometry_audit_and_preserves_runtime_boundary() -> None:
    receipt = review.build_receipt()
    assert receipt["status"] == "static_definition_geometry_passed_runtime_geometry_unverified"
    assert receipt["reviewer"]["model"] == "gpt-5.6-terra"
    assert receipt["reviewer"]["reasoning_effort"] == "high"
    assert receipt["reviewer"]["verdict"] == "PASS"
    assert receipt["reviewed_scope"]["all_47_frozen_definition_geometries"] is True
    assert receipt["reviewed_scope"]["generated_particle_counts_or_runtime_boundnor_vectors"] is False
    assert receipt["dp_distribution_m"] == {"0.0060": 5, "0.0075": 39, "0.0090": 3}
    assert receipt["static_audit"]["definition_count"] == 47
    assert receipt["execution_authority"]["gencase"] is False
    assert receipt["execution_authority"]["T1_numerical"] is False
    assert receipt["execution_authority"]["qualification_credit"] == 0
    bindings = {item["path"]: item for item in receipt["evidence"]}
    for path in (
        "scripts/f8_r008_definition_geometry_audit_v1.py",
        "tests/test_f8_r008_definition_geometry_audit_v1.py",
        "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/definition-control-pack-v1/receipt.json",
        "scripts/f8_input_materialization_v1.py",
    ):
        payload = (review.LAB / path).read_bytes()
        assert bindings[path]["bytes"] == len(payload)
        assert bindings[path]["sha256"] == hashlib.sha256(payload).hexdigest()


def test_geometry_review_receipt_is_write_once_and_verifiable(tmp_path: Path) -> None:
    target = tmp_path / "receipt.json"
    review.write_receipt(target)
    assert review.verify_receipt(target)["reviewer"]["verdict"] == "PASS"
    with pytest.raises(FileExistsError, match="refusing to overwrite immutable"):
        review.write_receipt(target)
