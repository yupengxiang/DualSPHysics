from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f7_s1_coarse_selector_candidate_v1.py"
MANIFEST = (
    ROOT
    / "campaigns/ds-data-02/stage2/requests/f7-s1-coarse-selector-candidate-v1-root-prepared-152-001"
    / "f7-s1-coarse-selector-candidate-v1-manifest.json"
)
REQUEST = MANIFEST.with_name("f7-s1-coarse-selector-candidate-v1-request.json")
SPEC = importlib.util.spec_from_file_location("f7_s1_coarse_selector_candidate_v1", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _manifest(tmp_path: Path) -> Path:
    value = json.loads(MANIFEST.read_text(encoding="utf-8"))
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return path


def _fluid_drawboxes(tree: ET.ElementTree) -> list[ET.Element]:
    mainlist = tree.getroot().find(".//geometry/commands/mainlist")
    assert mainlist is not None
    children = list(mainlist)
    marker = next(i for i, child in enumerate(children) if child.tag == "setmkfluid" and child.get("mk") == "1")
    result = []
    for child in children[marker + 1 :]:
        if child.tag in {"shapeout", "setmkbound", "setmkfluid"}:
            break
        if child.tag == "drawbox":
            result.append(child)
    return result


def _mainlist_nonfluid_signature(tree: ET.ElementTree) -> list[tuple[str, tuple[tuple[str, str], ...], str | None]]:
    mainlist = tree.getroot().find(".//geometry/commands/mainlist")
    assert mainlist is not None
    children = list(mainlist)
    marker = next(i for i, child in enumerate(children) if child.tag == "setmkfluid" and child.get("mk") == "1")
    signature = []
    for index, child in enumerate(children):
        if marker < index < marker + 5 and child.tag == "drawbox":
            continue
        signature.append((child.tag, tuple(sorted(child.attrib.items())), child.text.strip() if child.text else None))
    return signature


def _semantic(element: ET.Element | None) -> tuple:
    assert element is not None
    return (
        element.tag,
        tuple(sorted(element.attrib.items())),
        (element.text or "").strip(),
        tuple(_semantic(child) for child in list(element)),
    )


def test_candidate_is_deterministic_and_keeps_frozen_mass_policy() -> None:
    lattice = MODULE._candidate_lattice()
    assert lattice["axis_counts"] == [42, 28, 18]
    assert lattice["axis_offsets_from_source"] == [1, 0, 0]
    assert lattice["predicted_fluid_count"] == 20484
    assert lattice["target_fluid_count_from_owner_mass"] == 20493
    assert lattice["predicted_massfluid_kg"] == pytest.approx(320.0625)
    assert lattice["predicted_count_is_not_gencase_result"] is True


def test_actual_source_report_is_closed_and_candidate_xml_is_additive(tmp_path: Path) -> None:
    output = tmp_path / "candidate-report.json"
    report = MODULE.build_report(MANIFEST, output)
    assert report["status"] == "PREPARED_F7_S1_COARSE_SELECTOR_CANDIDATE_SOURCE_ONLY"
    assert report["existing_coarse_evidence"]["root149_outside_owner_envelope_unique_count"] == 810
    assert report["candidate"]["actual_gencase_status"] == "NOT_RUN_BY_THIS_WORKER"
    assert report["scientific_scope"]["QI"] == "UNKNOWN"
    candidate_path = output.parent / "f7-s1-coarse-selector-candidate-v1_Def.xml"
    source_path = next(
        Path(ref["path"])
        for ref in json.loads(MANIFEST.read_text())["source_refs"]
        if ref["key"] == "coarse_def"
    )
    source_tree = ET.parse(source_path)
    candidate_tree = ET.parse(candidate_path)
    assert len(_fluid_drawboxes(candidate_tree)) == 4
    assert _mainlist_nonfluid_signature(candidate_tree) == _mainlist_nonfluid_signature(source_tree)
    assert _semantic(candidate_tree.getroot().find(".//casedef/constantsdef")) == _semantic(
        source_tree.getroot().find(".//casedef/constantsdef")
    )
    assert _semantic(candidate_tree.getroot().find(".//casedef/motion")) == _semantic(
        source_tree.getroot().find(".//casedef/motion")
    )
    assert report["candidate"]["definition_xml_sha256"] == MODULE.sha256_file(candidate_path)


def test_wrong_case_or_evidence_is_rejected(tmp_path: Path) -> None:
    path = _manifest(tmp_path)
    value = json.loads(path.read_text())
    value["physical_case_id"] = "F7_OTHER_CASE"
    path.write_text(json.dumps(value) + "\n")
    with pytest.raises(MODULE.CandidateError, match="manifest physical case"):
        MODULE.build_report(path)

    value = json.loads(MANIFEST.read_text())
    value["source_refs"][next(i for i, row in enumerate(value["source_refs"]) if row["key"] == "root149_report")]["sha256"] = "deadbeef"
    path.write_text(json.dumps(value) + "\n")
    with pytest.raises(MODULE.CandidateError, match="root149_report SHA"):
        MODULE.build_report(path)


def test_mass_rescale_and_tolerance_widen_are_rejected(tmp_path: Path) -> None:
    path = _manifest(tmp_path)
    value = json.loads(path.read_text())
    value["owner_rescale"] = True
    path.write_text(json.dumps(value) + "\n")
    with pytest.raises(MODULE.CandidateError, match="owner rescale policy"):
        MODULE.build_report(path)

    value = json.loads(MANIFEST.read_text())
    value["tolerance_widen"] = True
    path.write_text(json.dumps(value) + "\n")
    with pytest.raises(MODULE.CandidateError, match="tolerance policy"):
        MODULE.build_report(path)


def test_native_payload_reference_is_rejected(tmp_path: Path) -> None:
    path = _manifest(tmp_path)
    value = json.loads(path.read_text())
    value["source_refs"].append({"key": "forbidden_bi4", "path": "/tmp/not-read.bi4", "kind": "binary", "sha256": "PARENT_GUARD_COMPUTED"})
    path.write_text(json.dumps(value) + "\n")
    with pytest.raises(MODULE.CandidateError, match="forbidden native payload"):
        MODULE.build_report(path)


def test_prepared_request_binds_every_json_xml_input_and_forbids_native_reads() -> None:
    request = json.loads(REQUEST.read_text(encoding="utf-8"))
    assert request["cpu_task_kind"] == "audit"
    assert request["command"][0].endswith("/.venv/bin/python")
    assert request["command"][1].endswith("ds_data02_stage2_f7_s1_coarse_selector_candidate_v1.py")
    assert request["hdf5_read"] is False
    assert request["bi4_read"] is False
    assert request["gencase_launch"] is False
    assert request["solver_launch"] is False
    assert request["guard_policy"]["owner_rescale"] is False
    assert request["guard_policy"]["tolerance_widen"] is False
    for path, expected in request["input_sha256"].items():
        actual = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        assert actual == expected, path
        assert Path(path).suffix.lower() not in {".h5", ".hdf5", ".vtk", ".bi4", ".obi4"}
