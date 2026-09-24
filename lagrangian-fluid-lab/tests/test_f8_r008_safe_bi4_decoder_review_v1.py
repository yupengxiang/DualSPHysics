from __future__ import annotations

import ast
import copy
import json
from pathlib import Path

import pytest

from scripts import f8_r008_safe_bi4_decoder_review_v1 as review


LAB = Path(__file__).resolve().parents[1]


def test_review_archive_binds_terra_high_pass_and_keeps_execution_closed() -> None:
    receipt = review.build_receipt()
    assert receipt["reviewer"]["name"] == "Terra High"
    assert receipt["reviewer"]["model"] == "gpt-5.6-terra"
    assert receipt["reviewer"]["reasoning_effort"] == "high"
    assert receipt["reviewer"]["verdict"] == "PASS"
    assert receipt["reviewer"]["reviewer_ran_tests"] is False
    assert all(item["verdict"] == "PASS" for item in receipt["review_findings"])
    assert receipt["readiness_effect"] == {
        "readiness_pass": False,
        "qualification_credit": 0,
        "execution_authority_granted": False,
    }
    controls = receipt["execution_controls"]
    assert all(
        controls[key] is False
        for key in (
            "production_bi4_read",
            "native_decoder_invoked",
            "gencase_invoked",
            "solver_invoked",
            "worker_started",
            "gpu_invoked",
        )
    )
    assert controls["queue_mutation"] == controls["registry_mutation"] == 0


def test_review_receipt_binds_exact_code_tests_and_pinned_writer() -> None:
    receipt = review.build_receipt()
    by_path = {item["path"]: item for item in receipt["evidence"]}
    for path in (
        "scripts/f8_r008_safe_bi4_decoder_v1.py",
        "tests/test_f8_r008_safe_bi4_decoder_v1.py",
        "vendor/official/DualSPHysics_v5.4/src/source/JBinaryData.cpp",
        "vendor/official/DualSPHysics_v5.4/src/source/JBinaryData.h",
    ):
        assert by_path[path]["bytes"] > 0
        assert len(by_path[path]["sha256"]) == 64
    assert receipt["parent_validation"]["decoder_tests"]["passed"] == 17
    assert receipt["parent_validation"]["r008_regression"]["passed"] == 128
    assert receipt["parent_validation"]["r008_regression"]["deselected"] == 5
    assert receipt["parent_validation"]["r008_regression"]["failed"] == 0
    assert "temporary synthetic BI4" in receipt["parent_validation"]["decoder_tests"]["input_scope"]


def test_decoder_does_not_import_native_execution_or_scientific_io_tools() -> None:
    source = (LAB / "scripts/f8_r008_safe_bi4_decoder_v1.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {
        alias.name.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not {"subprocess", "numpy", "h5py"} & imports


def test_review_receipt_verifier_rejects_tampering_and_writer_is_immutable(tmp_path: Path) -> None:
    target = tmp_path / "receipt.json"
    review.write_receipt(target)
    assert review.verify_receipt(target) == json.loads(target.read_text(encoding="utf-8"))
    with pytest.raises(FileExistsError, match="immutable safe BI4 decoder review"):
        review.write_receipt(target)

    changed = copy.deepcopy(review.build_receipt())
    changed["review_findings"][0]["verdict"] = "REVISE"
    target.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="no longer matches reviewed evidence"):
        review.verify_receipt(target)
