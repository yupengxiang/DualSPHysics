from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import h5py
import numpy as np
import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ds_data02_stage2_family_label_canary_v1.py"
SPEC = importlib.util.spec_from_file_location("family_canary", SCRIPT)
assert SPEC and SPEC.loader
family_canary = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(family_canary)


def _tiny_config(path: Path, *, frame_kind: str = "fixed_solver_frame") -> Path:
    config = {
        "schema": "ds-data-02.static-event-config.v1",
        "frame_kind": frame_kind,
        "coordinate_frame": "synthetic-frame",
        "physical_case_id": "F3_SYNTHETIC_CASE",
        "source_assignment": "initial_regions",
        "source_regions": [
            {"id": "left", "bounds": [[-1.0, 0.0], [-1.0, 1.0], [-1.0, 1.0]]},
            {"id": "right", "bounds": [[0.0, 1.0], [-1.0, 1.0], [-1.0, 1.0]]},
        ],
        "destination_regions": [
            {"id": "left", "bounds": [[-1.0, 0.0], [-1.0, 1.0], [-1.0, 1.0]]},
            {"id": "right", "bounds": [[0.0, 1.0], [-1.0, 1.0], [-1.0, 1.0]]},
        ],
        "events": [{"id": "midplane", "axis": 0, "value": 0.0,
                    "aperture_bounds": [[-1.0, 1.0], [-1.0, 1.0]]}],
    }
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def _tiny_h5(path: Path) -> Path:
    # Particle 10 crosses the finite x=0 aperture; particle 11 becomes an
    # unknown destination at the final frame.  This exercises the saved-chord
    # label semantics without reading any campaign H5.
    with h5py.File(path, "w") as handle:
        handle.attrs["coordinate_frame"] = "synthetic-frame"
        handle.create_dataset("time", data=np.asarray([0.0, 1.0, 2.0]))
        handle.create_dataset("particle_id", data=np.asarray([10, 11], dtype=np.uint32))
        handle.create_dataset("particle_zone", data=np.asarray([0, 0], dtype=np.int16))
        handle.create_dataset("position", data=np.asarray([
            [[-0.5, 0.0, 0.0], [-0.5, 0.0, 0.0]],
            [[0.5, 0.0, 0.0], [0.5, 0.0, 0.0]],
            [[0.5, 0.0, 0.0], [1.5, 0.0, 0.0]],
        ], dtype=np.float64))
        handle.create_dataset("valid", data=np.ones((3, 2), dtype=np.bool_))
        handle.create_dataset("mass", data=np.full((3, 2), 0.5, dtype=np.float64))
        handle.create_dataset("type", data=np.full((3, 2), 3, dtype=np.int8))
    return path


def test_materialize_saved_chord_and_output_is_forward_only(tmp_path: Path) -> None:
    source = _tiny_h5(tmp_path / "source.h5")
    config = _tiny_config(tmp_path / "config.json")
    output = tmp_path / "labels.h5"
    result = family_canary.materialize(source, output, json.loads(config.read_text()), particle_chunk=2)
    assert result["frames"] == 3
    assert output.is_file()
    with h5py.File(output, "r") as handle:
        assert float(handle["forward_backward_mass_kg"][1, 0, 0]) == pytest.approx(1.0)
        assert float(handle["unknown_mass_kg"][-1]) == pytest.approx(0.5)
    with pytest.raises(FileExistsError):
        family_canary.materialize(source, source, json.loads(config.read_text()))


def _synthetic_contract(tmp_path: Path, config: Path, source: Path) -> dict:
    files = {
        "current_manifest": tmp_path / "CURRENT.json",
        "trajectory": source,
        "conversion_report": tmp_path / "conversion.json",
        "generated_xml": tmp_path / "case.xml",
        "gencase_receipt": tmp_path / "gencase.json",
        "solver_receipt": tmp_path / "solver.json",
        "run_out": tmp_path / "solver" / "Run.out",
        "run_parts": tmp_path / "solver" / "RunPARTs.csv",
    }
    files["run_out"].parent.mkdir()
    files["current_manifest"].write_text("{}")
    files["conversion_report"].write_text("{}")
    files["generated_xml"].write_text("<case />")
    files["gencase_receipt"].write_text(json.dumps({"status": "completed"}))
    files["solver_receipt"].write_text(json.dumps({"status": "completed"}))
    files["run_out"].write_text("Run.out")
    files["run_parts"].write_text("RunPARTs")
    bindings = {}
    for key, path in files.items():
        bindings[key] = {"path": str(path), "sha256": family_canary.sha256_file(path)}
    bindings["label_config"] = {"path": str(config), "sha256": family_canary.sha256_file(config)}
    current = {
        "cases": [{
            "family_id": "F3",
            "physical_case_id": "F3_SYNTHETIC_CASE",
            "frames": 3,
            "particles": 2,
            "actual_time_window_s": [0.0, 2.0],
            "trajectory": {"path": str(source), "producer_declared_sha256": family_canary.sha256_file(source)},
            "conversion_report": {"path": str(files["conversion_report"])},
            "source_bindings": {
                key: {"path": str(files[key]), "sha256": bindings[key]["sha256"]}
                for key in ("generated_xml", "gencase_receipt", "solver_receipt")
            },
            "raw_root": {"path": str(files["run_out"].parent / "data")},
        }]
    }
    files["current_manifest"].write_text(json.dumps(current))
    bindings["current_manifest"]["sha256"] = family_canary.sha256_file(files["current_manifest"])
    return {
        "schema": family_canary.SCHEMA,
        "family_id": "F3",
        "physical_case_id": "F3_SYNTHETIC_CASE",
        "mechanism_id": "synthetic_exchange",
        "frames": 3,
        "particles": 2,
        "actual_time_window_s": [0.0, 2.0],
        "source": {key: bindings[key] for key in files},
        "label_config": bindings["label_config"],
        "semantics": {"physical_fate": "UNKNOWN", "dynamic_impact": "UNKNOWN",
                       "frame_claim": "fixed_eulerian_observer"},
    }


def test_contract_rejects_moving_frame_and_wrong_physical_binding(tmp_path: Path) -> None:
    source = _tiny_h5(tmp_path / "source.h5")
    config = _tiny_config(tmp_path / "config.json")
    contract = _synthetic_contract(tmp_path, config, source)
    assert family_canary.validate_contract(contract, check_content=True)["physical_case_id"] == "F3_SYNTHETIC_CASE"

    moving = json.loads(json.dumps(contract))
    moving_config = _tiny_config(tmp_path / "moving.json", frame_kind="moving_solver_frame")
    moving["label_config"] = {"path": str(moving_config), "sha256": family_canary.sha256_file(moving_config)}
    with pytest.raises(family_canary.ContractError, match="moving-frame"):
        family_canary.validate_contract(moving, check_content=True)

    wrong = json.loads(json.dumps(contract))
    wrong["physical_case_id"] = "F3_OTHER_CASE"
    with pytest.raises(family_canary.ContractError, match="CURRENT"):
        family_canary.validate_contract(wrong, check_content=True)


def test_contract_rejects_unearned_dynamic_credit(tmp_path: Path) -> None:
    source = _tiny_h5(tmp_path / "source.h5")
    config = _tiny_config(tmp_path / "config.json")
    contract = _synthetic_contract(tmp_path, config, source)
    contract["semantics"]["dynamic_impact"] = "BOUNDED"
    with pytest.raises(family_canary.ContractError, match="dynamic impact"):
        family_canary.validate_contract(contract, check_content=True)


def test_contract_rejects_runparts_from_another_raw_parent(tmp_path: Path) -> None:
    source = _tiny_h5(tmp_path / "source.h5")
    config = _tiny_config(tmp_path / "config.json")
    contract = _synthetic_contract(tmp_path, config, source)
    other = tmp_path / "other-solver"
    other.mkdir()
    other_runparts = other / "RunPARTs.csv"
    other_runparts.write_text("same-looking-but-different-solver-parent")
    contract["source"]["run_parts"] = {
        "path": str(other_runparts),
        "sha256": family_canary.sha256_file(other_runparts),
    }
    with pytest.raises(family_canary.ContractError, match="raw solver output"):
        family_canary.validate_contract(contract, check_content=True)
