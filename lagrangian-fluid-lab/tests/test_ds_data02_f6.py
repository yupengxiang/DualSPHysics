from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import xml.etree.ElementTree as ET


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ds_data02_f6.py"
SPEC = importlib.util.spec_from_file_location("ds_data02_f6", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
F6 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(F6)


def test_generate_validate_freezes_nested_split_and_no_model(tmp_path: Path) -> None:
    output = tmp_path / "F6"
    generated = F6.generate_family(output)
    assert generated["registry_rows"] == 48
    report = F6.validate_family(output)
    assert report["valid"], report
    assert report["history_reused_count"] == 0
    assert report["split_counts"] == {
        "train": 24,
        "validation": 6,
        "id_test": 6,
        "parameter_ood_test": 6,
        "geometry_control_ood_test": 6,
    }
    rows = [json.loads(line) for line in (output / "case_registry.jsonl").read_text().splitlines()]
    assert len({row["physical_case_id"] for row in rows}) == 48
    assert all(row["nested_subsets"][-1] == "final_48" for row in rows)
    assert all(not row["nested_subsets"] or row["nested_subsets"][0] == "pilot_8" for row in rows[:8])
    assert all(row["model_runtime_loaded"] is False for row in [F6.read_json(output / "family_card.json")])


def test_parent_definitions_are_native_three_d_no_contact_and_controls_are_full_window(tmp_path: Path) -> None:
    output = tmp_path / "F6"
    F6.generate_family(output)
    manifest = F6.read_json(output / "parent_inputs/parent_input_manifest.json")
    assert len(manifest["parents"]) == 2
    for parent in manifest["parents"]:
        definition = Path(parent["definition"]["path"])
        root = ET.parse(definition).getroot()
        rigid = next(node for node in root.findall("./execution/parameters/parameter") if node.get("key") == "RigidAlgorithm")
        assert rigid.get("value") == "1"
        assert root.find("./casedef/floatings/floating") is not None
        assert "<chrono" not in definition.read_text(encoding="utf-8").lower()
        coverage = F6._control_coverage(Path(parent["control"]["path"]))
        assert coverage["coverage_pass"]
        assert coverage["rows"] == F6.PARENT_CONTROL_ROWS
        assert coverage["time_start_s"] == 0.0
        assert coverage["time_end_s"] == 12.0
        assert parent["native"]["sha256"] == F6.sha256_file(Path(parent["native"]["path"]))
        assert parent["normal"]["sha256"] == F6.sha256_file(Path(parent["normal"]["path"]))


def test_bounded_repairs_bind_wave_motion_and_select_new_gencase_attempt(tmp_path: Path) -> None:
    output = tmp_path / "F6"
    F6.generate_family(output)
    manifest = F6.read_json(output / "parent_inputs/parent_input_manifest.json")
    parents = {row["mechanism_id"]: row for row in manifest["parents"]}
    simple_root = ET.parse(parents["simple_free_response"]["definition"]["path"]).getroot()
    wave_root = ET.parse(parents["wave_no_contact"]["definition"]["path"]).getroot()
    assert simple_root.find("./casedef/motion") is None
    assert wave_root.find("./casedef/motion/objreal[@ref='10']") is not None
    assert wave_root.find("./execution/special/wavepaddles/piston/mkbound[@value='10']") is not None
    assert F6._parent_specs()["simple_free_response"]["body"]["point_m"][2] == 0.36
    assert F6._parent_specs()["wave_no_contact"]["body"]["point_m"][2] == 0.36
    queue = F6.read_json(output / "execution_queue.json")
    assert {row["attempt_id"] for row in queue["cpu_requests"]} == {
        "F6_SIMPLE_FREE_RESPONSE_PARENT_GENCASE_02",
        "F6_WAVE_NO_CONTACT_PARENT_GENCASE_02",
    }
    repair = F6.read_json(output / "repair_evidence.json")
    assert repair["reused_count"] == 0
    assert {row["bounded_repair_number"] for row in repair["records"]} == {1}


def test_qualification_request_is_explicitly_pending_and_hash_bound() -> None:
    output = F6.FAMILY_ROOT
    if not (output / "qualification_requests/simple_free_response.json").is_file():
        return
    request = F6.read_json(output / "qualification_requests/simple_free_response.json")
    assert request["kind"] == "qualification"
    assert request["event_timing_qualified"] is False
    assert request["solver_launch_forbidden_for_f6_owner"] is True
    assert request["gencase_actual_particles"]["total"] > request["gencase_actual_particles"]["fluid"] > 0
    assert request["gencase_receipt_sha256"] == F6.sha256_file(Path(request["gencase_receipt"]))
    assert all(Path(path).is_file() for path in request["input_files"])
    assert any(path.endswith("__Actual.vtk") for path in request["input_files"])
    assert any(path.endswith("FloatingInfo_linux64") for path in request["input_files"])
    assert any(path.endswith("ComputeForces_linux64") for path in request["input_files"])
