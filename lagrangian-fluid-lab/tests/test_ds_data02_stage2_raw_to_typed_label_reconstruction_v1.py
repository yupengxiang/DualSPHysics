from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import pytest


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import ds_data02_stage2_raw_to_typed_label_reconstruction_v1 as worker  # noqa: E402


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _request(tmp_path: Path, *, with_contract: bool = False) -> tuple[Path, dict]:
    raw = tmp_path / "PartOut_000.obi4"
    raw.write_bytes(b"raw native anchor\n")
    runparts = tmp_path / "RunPARTs.csv"
    runparts.write_text("time,part\n0,0\n")
    scan = tmp_path / "scientific-scan.json"
    scan.write_text("{}\n")
    typed = tmp_path / "trajectory.h5"
    # The preparation path must stat but never content-hash this file.
    typed.write_bytes(b"typed placeholder")
    request = {
        "schema": "ds02.request.v1",
        "request_id": "manufactured-raw-plan-001",
        "model_invoked": False,
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "input_files": [
            {"role": "native_partout", "path": str(raw), "sha256": _sha(raw)},
            {"role": "native_runparts", "path": str(runparts), "sha256": _sha(runparts)},
            {"role": "scientific_scan_sidecar", "path": str(scan), "sha256": _sha(scan)},
        ],
        "trajectory_h5": {
            "role": "trajectory_h5",
            "path": str(typed),
            "expected_content_sha256": "f" * 64,
            "bytes": typed.stat().st_size,
        },
    }
    if with_contract:
        converter = tmp_path / "converter.py"
        converter.write_text("# converter\n")
        label = tmp_path / "label.py"
        label.write_text("# label\n")
        converter_receipt = tmp_path / "raw-to-typed-receipt.json"
        converter_receipt.write_text("{}\n")
        label_receipt = tmp_path / "typed-to-label-receipt.json"
        label_receipt.write_text("{}\n")
        request["input_files"].extend([
            {"role": "raw_to_typed_converter_receipt", "path": str(converter_receipt), "sha256": _sha(converter_receipt)},
            {"role": "typed_to_label_operator_receipt", "path": str(label_receipt), "sha256": _sha(label_receipt)},
        ])
        request["reconstruction_contract"] = {
            "raw_to_typed": {
                "module_path": str(converter), "module_sha256": _sha(converter),
                "receipt_path": str(converter_receipt),
                "schema_contract": "typed.v1; fields/units/valid-mask bound",
            },
            "typed_to_label": {
                "module_path": str(label), "module_sha256": _sha(label),
                "receipt_path": str(label_receipt),
                "valid_mask_proof": "(Zone,Idp) exact + finite mask",
            },
        }
    path = tmp_path / "request.json"
    path.write_text(json.dumps(request) + "\n")
    return path, request


def test_prepare_is_pending_and_scan_is_not_converter(tmp_path: Path) -> None:
    request, _ = _request(tmp_path)
    output = tmp_path / "plan.json"
    plan = worker.prepare_plan(request, output)
    assert plan["status"] == "PENDING_SOURCE_RECONSTRUCTION"
    assert plan["contract"]["scientific_scan_is_not_reconstruction"] is True
    assert plan["raw_to_typed"]["invoked"] is False
    assert plan["qualification"] == worker.UNKNOWN_QUALIFICATION
    assert worker.validate_plan(output)["status"] == "VALID_PREPARATION_ONLY"


def test_complete_contract_is_only_ready_for_parent_guard(tmp_path: Path) -> None:
    request, _ = _request(tmp_path, with_contract=True)
    output = tmp_path / "plan.json"
    plan = worker.prepare_plan(request, output)
    assert plan["status"] == "READY_FOR_PARENT_GUARDED_RECONSTRUCTION"
    assert plan["execution_boundary"]["hdf5_content_hashed"] is False
    assert plan["raw_to_typed"]["invoked"] is False


def test_source_mutation_is_rejected(tmp_path: Path) -> None:
    request, data = _request(tmp_path)
    raw = Path(data["input_files"][0]["path"])
    raw.write_bytes(b"mutated native anchor\n")
    with pytest.raises(worker.ReconstructionBindingError, match="source SHA differs"):
        worker.prepare_plan(request, tmp_path / "plan.json")


def test_existing_output_is_never_overwritten(tmp_path: Path) -> None:
    request, _ = _request(tmp_path)
    output = tmp_path / "plan.json"
    output.write_text("historical\n")
    with pytest.raises(worker.ReconstructionBindingError, match="overwrite"):
        worker.prepare_plan(request, output)


def test_non_unknown_qualification_is_rejected(tmp_path: Path) -> None:
    request, data = _request(tmp_path)
    data["qualification"] = {"QI": "QN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
    request.write_text(json.dumps(data) + "\n")
    with pytest.raises(worker.ReconstructionBindingError, match="UNKNOWN"):
        worker.prepare_plan(request, tmp_path / "plan.json")
