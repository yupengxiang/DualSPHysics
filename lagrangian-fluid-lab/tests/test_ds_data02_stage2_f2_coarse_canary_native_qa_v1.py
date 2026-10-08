from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_coarse_canary_native_qa_v1.py"
REQUEST_DIR = (
    ROOT
    / "campaigns/ds-data-02/stage2/requests/"
    / "f2-coarse-canary-native-qa-v1-root-forward-104-001"
)
MANIFEST = REQUEST_DIR / "f2-coarse-canary-native-qa-v1-manifest.json"
REQUEST = REQUEST_DIR / "f2-coarse-canary-native-qa-v1-request.json"


def module():
    spec = importlib.util.spec_from_file_location("f2_coarse_canary_native_qa_v1", SCRIPT)
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def test_generated_xml_blocks_and_mass_are_typed():
    loaded = module()
    xml = Path("/tmp/f2-native-qa-generated.xml")
    xml.write_text(
        "<case><casedef><definition dp='0.0088'/><particles np='5'>"
        "<_summary><fluid count='5'/></_summary>"
        "<fluid mkfluid='0' mk='1' begin='0' count='3'/><fluid mkfluid='1' mk='2' begin='3' count='2'/>"
        "</particles><constants><massfluid value='0.5'/></constants></casedef></case>",
        encoding="utf-8",
    )
    result = loaded.generated_fluid_blocks(xml)
    assert result["fluid_count"] == 5
    assert result["massfluid_kg"] == pytest.approx(0.5)
    assert result["fluid_blocks"] == [
        {"mkfluid": 0, "mk": 1, "begin": 0, "count": 3},
        {"mkfluid": 1, "mk": 2, "begin": 3, "count": 2},
    ]
    loaded.validate_generated_expectations(
        result,
        {
            "initial_particles_total": 5,
            "initial_fluid_count": 5,
            "massfluid_kg": 0.5,
            "fluid_blocks": result["fluid_blocks"],
        },
    )
    with pytest.raises(loaded.NativeQaError, match="total particle count"):
        loaded.validate_generated_expectations(
            result,
            {"initial_particles_total": 6, "initial_fluid_count": 5},
        )


def test_native_rows_join_mk_mass_motive_and_saved_bracket(tmp_path: Path):
    loaded = module()
    csv_path = tmp_path / "PartOut.csv"
    csv_path.write_text(
        "PartOut,Motive,Idp,Pos.x [m],Pos.y [m],Pos.z [m],Rhop [kg/m^3],Vel.x [m/s],Vel.y [m/s],Vel.z [m/s]\n"
        "1,1,1,0.1,0.2,0.3,1001,1,2,3\n"
        "2,2,4,0.4,0.5,0.6,998,4,5,6\n",
        encoding="utf-8",
    )
    rows = loaded.parse_native_csv(csv_path, [
        {"begin": 0, "count": 3, "mkfluid": 0, "mk": 1},
        {"begin": 3, "count": 2, "mkfluid": 1, "mk": 2},
    ])
    runparts_path = tmp_path / "RunPARTs.csv"
    runparts_path.write_text(
        "Part;TimeStep [s];NpOut;NpOutPos;NpOutRho;NpOutMov\n"
        "0;0.0;0;0;0;0\n"
        "1;0.1;1;1;0;0\n"
        "2;0.2;1;0;1;0\n",
        encoding="utf-8",
    )
    runparts = loaded.parse_runparts(runparts_path)
    loaded.attach_saved_brackets(rows, runparts)
    assert rows[0]["motive"] == "position"
    assert rows[0]["mk"] == 1
    assert rows[1]["motive"] == "density"
    assert rows[1]["mk"] == 2
    assert rows[0]["saved_record_bracket_s"] == [0.0, 0.1]
    assert rows[1]["saved_record_bracket_s"] == [0.1, 0.2]


def test_native_id_outside_fluid_blocks_is_rejected(tmp_path: Path):
    loaded = module()
    csv_path = tmp_path / "PartOut.csv"
    csv_path.write_text(
        "PartOut,Motive,Idp,Pos.x [m],Pos.y [m],Pos.z [m],Rhop [kg/m^3]\n"
        "1,1,9,0,0,0,1000\n",
        encoding="utf-8",
    )
    with pytest.raises(loaded.NativeQaError, match="outside generated fluid blocks"):
        loaded.parse_native_csv(csv_path, [{"begin": 0, "count": 3, "mkfluid": 0, "mk": 1}])


def test_request_is_native_small_scope_and_no_threads_flag():
    request = json.loads(REQUEST.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert request["case_id"] == "STAGE2_F2_COARSE_CANARY_NATIVE_QA_V1"
    assert request["command"][1].endswith("ds_data02_stage2_f2_coarse_canary_native_qa_v1.py")
    assert "-threads:1" not in request["command"]
    assert request["hdf5_read"] is False
    assert request["solver_launch"] is False
    assert request["gencase_launch"] is False
    assert request["gpu_launch"] is False
    assert request["native_decode"] is True
    assert manifest["expected"]["initial_fluid_count"] == 27750
    assert manifest["expected"]["expected_native_loss_count"] == 153
    assert all(not path.lower().endswith(".h5") for path in request["input_files"])
    assert all("/Part_" not in path or not path.endswith(".bi4") for path in request["input_files"])


def test_request_binds_real_canary_receipt_and_partout():
    request = json.loads(REQUEST.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["inputs"]["solver_receipt"]["path"].endswith("f2-s1-owner-centered-cell-selector-dp0088-t4-coarse-canary-v5-root-095-001/execution-receipt.json")
    assert manifest["inputs"]["raw_partout"]["path"].endswith("solver_output/data/PartOut_000.obi4")
    assert manifest["inputs"]["runparts"]["path"].endswith("solver_output/RunPARTs.csv")
    assert request["source_binding"]["solver_case_id"] == "F2_S1_OWNER_CENTERED_CELL_SELECTOR_DP0088_T4_COARSE_CANARY_ROOT_095"
    assert request["source_binding"]["old_native_identity_1078_reuse"] is False
    assert request["source_binding"]["physical_fate"] == "UNKNOWN"
    assert manifest["raw_data_root"]["path"].endswith("solver_output/data")
    assert manifest["solver_output_root"]["path"].endswith("/solver_output")
