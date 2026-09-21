from __future__ import annotations

import json
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from scripts import core_f3_baffle_runtime as base_runtime
from scripts import core_f3_baffle_runtime_v2 as runtime


ROOT = Path(__file__).resolve().parents[1]
SCOPE = ROOT / "campaigns/core-v1/cfd/f3-baffle-exchange-source-scope-v1"
CANDIDATE = SCOPE / "candidate-card-normals-v2.json"
MATRIX = SCOPE / "qualification-matrix-v1.json"
DENOMINATOR = SCOPE / "failure-denominator-v1.json"
PREPARED = SCOPE / "anchor-q0p5-dp0p0075-normals-v2c/prepared.json"
REVIEW = SCOPE / "runtime-root-review-anchor-normals-v2.json"


def _binding() -> dict:
    return runtime.verify_bindings(candidate_path=CANDIDATE, matrix_path=MATRIX,
                                   denominator_path=DENOMINATOR, prepared_path=PREPARED,
                                   review_path=REVIEW)


def test_v2_binding_is_normals_aware_one_anchor_zero_credit() -> None:
    binding = _binding()
    assert binding["prepared"]["revision_id"] == runtime.REVISION_ID
    assert binding["prepared"]["case_id"] == runtime.TARGET_CASE_ID
    assert binding["row"]["status"] == "not_started"
    assert binding["review"]["execution_policy"]["matrix_credit"] == 0
    assert binding["review"]["authorization"]["matrix_expansion"] is False
    assert binding["prepared"]["normal_geometry"]["geometry_list"] == "GeometryForNormals"
    assert binding["prepared"]["normal_geometry"]["baffle_mkbound"] == "1"
    assert Path(binding["prepared"]["generated_prefix"] + "_hdp_Actual.vtk").is_file()
    assert base_runtime.REVISION_ID == "F3_baffle_exchange_native_mdbc_v1"


def test_v2_definition_binds_outer_and_baffle_normals() -> None:
    binding = _binding()
    definition = Path(binding["prepared"]["source_provenance"]["core_preflight_runner_path"])
    assert definition.name == "core_f3_baffled_source_scope_preflight_v2.py"
    xml = ET.parse(binding["geometry"]["xml_path"].parent.parent /
                   (Path(binding["geometry"]["xml_path"]).stem + "_Def.xml"))
    root = xml.getroot()
    normal_list = root.find("./casedef/geometry/commands/list[@name='GeometryForNormals']")
    assert normal_list is not None
    assert [node.get("mk") for node in normal_list.findall("setmkbound")] == ["0", "1"]
    assert normal_list.find("shapeout").get("file") == "hdp"
    mainlist = root.find("./casedef/geometry/commands/mainlist")
    assert mainlist.find("runlist").get("name") == "GeometryForNormals"
    assert root.find("./casedef/normals").get("active") == "true"
    assert root.find("./casedef/normals/norgeometry/geometryfile").get("file") == "[CaseName]_hdp_Actual.vtk"


def test_v2_job_is_scheduler_valid_and_registry_free(tmp_path: Path) -> None:
    spec = runtime.build_job(lab=ROOT, candidate=CANDIDATE, matrix=MATRIX,
                             denominator=DENOMINATOR, prepared=PREPARED,
                             review=REVIEW, output=tmp_path / "job.json")
    assert spec["job_id"] == runtime.TARGET_JOB_ID
    assert spec["revision_id"] == runtime.REVISION_ID
    assert spec["prepared_case_id"] == runtime.TARGET_CASE_ID
    assert spec["argv"][1].endswith("core_f3_baffle_runtime_v2.py")
    assert spec["matrix_credit"] == 0
    assert spec["queue_mutation_authorized"] is False
    assert spec["ledger_mutation_authorized"] is False
    assert spec["registry_mutation_authorized"] is False
    assert spec["matrix_expansion_authorized"] is False
    assert any(item["path"].endswith("core_f3_baffle_runtime_v2.py") for item in spec["input_files"])


def test_v2_review_cannot_expand_matrix(tmp_path: Path) -> None:
    review = json.loads(REVIEW.read_text(encoding="utf-8"))
    review["authorization"]["matrix_expansion"] = True
    changed = tmp_path / "review.json"
    changed.write_text(json.dumps(review), encoding="utf-8")
    with pytest.raises(ValueError, match="matrix_expansion"):
        runtime.verify_bindings(candidate_path=CANDIDATE, matrix_path=MATRIX,
                                denominator_path=DENOMINATOR, prepared_path=PREPARED,
                                review_path=changed)
