from __future__ import annotations

import json
from pathlib import Path

import h5py
import pytest

from scripts.ds_data02_convert import (
    ConversionError,
    _csv_frames,
    _raw_manifest,
    convert_bi4,
)


HEADER = (
    "Pos.x [m],Pos.y [m],Pos.z [m],Zone,Idp,Vel.x [m/s],Vel.y [m/s],"
    "Vel.z [m/s],Rhop [kg/m^3],Mass [kg],Press [Pa],Type,Mk,\n"
)


def _write_csv(path: Path, time: float) -> None:
    path.write_text(
        "TimeStep [s],Np,Nbound,Nfixed,Nmoving,Nfloat,Nfluid\n"
        f"{time},3,0,0,0,0,3\n\n"
        + HEADER
        + "0.1,0.0,0.0,0,10,0.0,0.0,0.0,1000.0,1.0,0.0,3,1,\n"
        + "0.2,0.0,0.0,0,11,0.1,0.0,0.0,1000.0,1.0,1.0,3,1,\n"
        + "0.3,0.0,0.0,0,12,0.2,0.0,0.0,1000.0,1.0,2.0,3,1,\n",
        encoding="utf-8",
    )


def _write_fixture(tmp_path: Path) -> dict[str, Path]:
    solver_root = tmp_path / "solver-attempt"
    solver_dir = solver_root / "solver"
    data_dir = solver_dir / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "Part_0000.bi4").write_bytes(b"frame-0")
    (data_dir / "Part_0001.bi4").write_bytes(b"frame-1")
    (solver_dir / "Run.out").write_text(
        "**3D-Simulation parameters:\n"
        "Particles of simulation (initial): 3\n"
        "CaseNfluid=3\n"
        "CaseNfloat=0\n"
        "Excluded particles...............: 0\n",
        encoding="utf-8",
    )
    (solver_dir / "Run.csv").write_text(
        "#Run;PhysicalTime;PartFiles\n"
        "0;1.0;2\n",
        encoding="utf-8",
    )
    (solver_dir / "RunPARTs.csv").write_text(
        "Part;TimeStep [s];Steps\n"
        "0;0.0;0\n"
        "1;1.000000123;1\n",
        encoding="utf-8",
    )
    generated_xml = tmp_path / "Case.xml"
    generated_xml.write_text(
        "<case><execution><parameters>"
        "<parameter key='Shifting' value='0'/>"
        "</parameters><motion/></execution>"
        "<constants><data2d value='false'/></constants></case>",
        encoding="utf-8",
    )
    definition_xml = tmp_path / "Case_Def.xml"
    definition_xml.write_text("<case><geometry/></case>", encoding="utf-8")
    owner = tmp_path / "Case.metadata.json"
    owner.write_text(json.dumps({
        "schema": "ds-data-02.f1.generator.v1",
        "case_id": "F1_TEST",
        "family_id": "F1",
        "mechanism_id": "test",
        "recipe_id": "test-recipe",
        "resolution": "coarse",
        "control_family_id": "F1_CONTROL_TEST",
        "geometry_family_id": "F1_GEOM_TEST",
        "geometry": {"tank_length_m": 1.0, "open_top": True},
        "solver_parameters": {"Shifting": 0},
        "source_mother": {"boundary": "DBC", "solver_dimension": "3D"},
    }), encoding="utf-8")
    gencase_receipt = tmp_path / "gencase-execution-receipt.json"
    gencase_receipt.write_text(json.dumps({
        "schema": "ds02.execution-receipt.v1",
        "status": "completed",
        "total_particles": 3,
        "fluid_particles": 3,
        "solver_dimension_from_gencase": 3,
        "output_root": str(tmp_path / "gencase"),
        "request": {"input_files": [str(definition_xml), str(owner)]},
    }), encoding="utf-8")
    solver_receipt = tmp_path / "solver-execution-receipt.json"
    solver_receipt.write_text(json.dumps({
        "schema": "ds02.execution-receipt.v1",
        "status": "completed",
        "output_root": str(solver_root),
        "request": {
            "kind": "qualification",
            "case_id": "F1_TEST",
            "input_files": [str(generated_xml), str(data_dir / "Part_0000.bi4"), str(gencase_receipt)],
        },
    }), encoding="utf-8")
    csv_root = tmp_path / "csv"
    csv_root.mkdir()
    _write_csv(csv_root / "Particles_0000.csv", 0.0)
    _write_csv(csv_root / "Particles_0001.csv", 1.0)
    return {
        "solver": solver_receipt, "gencase": gencase_receipt, "owner": owner,
        "csv": csv_root, "output": tmp_path / "trajectory.h5", "report": tmp_path / "report.json",
        "work": tmp_path / "work",
    }


def test_converter_preserves_typed_identity_units_and_actual_dimension(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path)
    report = convert_bi4(
        solver_receipt=paths["solver"], gencase_receipt=paths["gencase"], owner_metadata=paths["owner"],
        output=paths["output"], work_dir=paths["work"], csv_root=paths["csv"],
        partvtk=Path(__file__), report_path=paths["report"], keep_csv=True,
    )
    assert report["conversion_status"] == "completed"
    assert report["q_n_status"] == "not_assessed"
    assert report["q_i_audit"]["dimension_evidence"]["solver_dimension"] == 3
    assert report["q_i_audit"]["q_i_status"] == "Q-I-incomplete"
    assert report["verification"]["valid_complete"] is True
    with h5py.File(paths["output"], "r") as handle:
        assert handle["position"].shape == (2, 3, 3)
        assert handle["particle_id"][:].tolist() == [10, 11, 12]
        assert handle["particle_zone"][:].tolist() == [0, 0, 0]
        assert handle["time"].attrs["units"] == "s"
        assert handle["mass"].attrs["units"] == "kg"
        assert handle.attrs["identity_key"] == "(Zone,Idp)"
        assert handle.attrs["solver_dimension"] == 3
        assert handle.attrs["coordinate_frame_inference_from_coordinate_values"] == 0
        assert handle["time"][:].tolist() == pytest.approx([0.0, 1.000000123])
        assert "RunPARTs.csv" in handle.attrs["time_source"]
    json.loads(paths["report"].read_text(encoding="utf-8"))


def test_raw_manifest_requires_contiguous_bi4_frames(tmp_path: Path) -> None:
    root = tmp_path / "data"
    root.mkdir()
    (root / "Part_0000.bi4").write_bytes(b"0")
    (root / "Part_0002.bi4").write_bytes(b"2")
    with pytest.raises(ConversionError, match="not contiguous"):
        _raw_manifest(root)


def test_csv_frames_require_unit_labelled_partvtk_columns(tmp_path: Path) -> None:
    root = tmp_path / "csv"
    root.mkdir()
    _write_csv(root / "Particles_0000.csv", 0.0)
    (root / "Particles_0001.csv").write_text(
        "TimeStep [s],Np\n1.0,0\n\nPos.x [m],Idp\n0,1\n", encoding="utf-8"
    )
    with pytest.raises(ConversionError, match="missing required unit-labelled"):
        _csv_frames(root, 2)
