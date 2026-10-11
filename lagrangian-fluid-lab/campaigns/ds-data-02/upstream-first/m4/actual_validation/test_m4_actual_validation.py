from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys

import pytest


M4_ROOT = Path(__file__).resolve().parents[1]
if str(M4_ROOT) not in sys.path:
    sys.path.insert(0, str(M4_ROOT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import m4_portable_adapter as portable  # noqa: E402
from test_m4_portable_adapter import _fixture  # noqa: E402

import m4_actual_validation as worker  # noqa: E402


PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
WRAPPER = M4_ROOT / "m4_isolated_validate.py"


def _receipt(root: Path, interface: Path) -> Path:
    source_hdf5 = interface.parent / "normalized.h5"
    case_id = json.loads(interface.read_text(encoding="utf-8"))["case_id"]
    path = root / "enrichment-receipt.json"
    worker._write_json(
        path,
        {
            "schema": worker.ENRICHMENT_RECEIPT_SCHEMA,
            "status": "completed",
            "case_id": case_id,
            "credit_status": "not_credited",
            "physical_fate_inferred": False,
            "outputs": {
                "interface": worker._binding(interface),
                "enriched_hdf5": worker._binding(source_hdf5),
            },
        },
    )
    return path


def _inputs(tmp_path: Path) -> dict[str, Path]:
    input_root = tmp_path / "input"
    interface = _fixture(input_root)
    source_bundle = tmp_path / "source-bundle"
    portable.build_bundle(interface, source_bundle)
    receipt = _receipt(tmp_path / "receipt", interface)
    return {"interface": interface, "bundle": source_bundle, "receipt": receipt}


def _run_args(inputs: dict[str, Path], tmp_path: Path) -> argparse.Namespace:
    return argparse.Namespace(
        source_receipt=inputs["receipt"],
        source_bundle=inputs["bundle"],
        relocated_bundle=tmp_path / "attempt" / "relocated" / "UF_F1_MDBC_TEST",
        output=tmp_path / "attempt" / "validation",
        isolation_wrapper=WRAPPER,
        python=PYTHON,
        max_bytes=2 * 1024**3,
        max_wall_seconds=240.0,
    )


def test_prepare_request_requires_completed_bound_source(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    request_path = tmp_path / "request.json"
    request = worker.prepare_request(
        argparse.Namespace(
            source_receipt=inputs["receipt"],
            source_bundle=inputs["bundle"],
            output_request=request_path,
            relocated_bundle_template="{attempt_root}/m4-actual-validation/relocated/UF_F1_MDBC_TEST",
            output_template="{attempt_root}/m4-actual-validation/results",
            isolation_wrapper=WRAPPER,
            python=PYTHON,
            max_wall_seconds=240.0,
        )
    )
    assert request["status"] == "prepared_after_completed_source_receipt"
    assert request["requires_completed_source_receipt"] is True
    assert request["source_bundle"]["production_validation"]["portable"] is True
    assert request["destination_contract"]["fresh_second_absolute_nas_attempt_root"]
    assert [item["name"] for item in request["tamper_cases"]] == [
        "typed_identity_endpoint_label",
        "destination_position",
    ]
    command = request["command"]
    assert command[2:4] == ["run", "--source-receipt"]
    assert json.loads(request_path.read_text(encoding="utf-8"))["source_bundle"]["bytes"] > 0


def test_prepare_request_rejects_pending_source_receipt(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    receipt = json.loads(inputs["receipt"].read_text(encoding="utf-8"))
    receipt["status"] = "pending"
    inputs["receipt"].write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    with pytest.raises(worker.ActualValidationError, match="not completed"):
        worker.prepare_request(
            argparse.Namespace(
                source_receipt=inputs["receipt"],
                source_bundle=inputs["bundle"],
                output_request=tmp_path / "request.json",
                relocated_bundle_template="{attempt_root}/relocated",
                output_template="{attempt_root}/results",
                isolation_wrapper=WRAPPER,
                python=PYTHON,
                max_wall_seconds=240.0,
            )
        )


@pytest.mark.skipif(shutil.which("bwrap") is None, reason="bubblewrap is unavailable")
def test_actual_replay_and_rehashed_hdf5_semantic_negatives(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    source_manifest_hash = worker._sha256(inputs["bundle"] / "manifest.json")
    source_hdf5_hash = worker._sha256(inputs["bundle"] / "normalized.h5")
    result = worker.run_actual_validation(_run_args(inputs, tmp_path))
    assert result["status"] == "completed"
    assert result["source_unchanged"] is True
    assert result["isolated_replay"]["portable"] is True
    assert result["isolated_replay"]["denied_probes_passed"] is True
    assert result["semantic_negatives"]["passed"] is True
    assert result["semantic_negatives"]["count"] == 2
    assert worker._sha256(inputs["bundle"] / "manifest.json") == source_manifest_hash
    assert worker._sha256(inputs["bundle"] / "normalized.h5") == source_hdf5_hash
    reports = [Path(path) for path in result["semantic_negatives"]["reports"]]
    assert all(path.is_file() for path in reports)
    rows = [json.loads(path.read_text(encoding="utf-8")) for path in reports]
    assert {row["status"] for row in rows} == {"rejected_as_expected"}
    assert all(row["artifact_layer_rehashed"] is True for row in rows)
    assert "endpoint identity labels changed" in rows[0]["production_validator"]["stderr_tail"]
    assert "displacement is not the keyed" in rows[1]["production_validator"]["stderr_tail"]
    assert not (tmp_path / "attempt" / "validation" / "scratch").exists()
