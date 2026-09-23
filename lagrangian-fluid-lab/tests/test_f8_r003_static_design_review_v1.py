import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from scripts import f8_r003_static_design_review_v1 as review_module


ROOT = Path(__file__).resolve().parents[1]


def test_r003_review_is_new_static_zero_credit_scope() -> None:
    review = review_module.build_review()
    assert review["schema"] == "core.cfd.f8.r003_static_design_review.v1"
    assert review["scope_id"] == "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R003"
    assert review["status"] == "r003_static_design_review_passed_inputs_not_authorized"
    assert review["qualification_credit"] == 0
    assert review["static_constraint_gaps"] == []
    assert not (ROOT / review_module.DEFINITION_TARGET).exists()
    assert not (ROOT / review_module.CONTROL_TARGET).exists()
    assert not (ROOT / review_module.PREFLIGHT_ROOT).exists()


def test_r003_constants_include_hswl_and_complete_reviewed_compatibility_set() -> None:
    xml = review_module.definition_xml(review_module.parameters())
    constants = {node.tag: node.attrib for node in ET.fromstring(xml).findall("./casedef/constantsdef/*")}
    assert constants["hswl"] == {"value": "0", "auto": "true"}
    assert constants["rhopgradient"]["value"] == "1"
    assert constants["gamma"]["value"] == "7"
    assert constants["speedsystem"] == {"value": "0", "auto": "true"}
    assert constants["coefsound"]["value"] == "1"
    assert constants["speedsound"] == {"value": "10", "auto": "false"}


def test_r003_preserves_finite_walls_and_new_control_copy_contract() -> None:
    review = review_module.build_review()
    proof = review["finite_wall_proof"]
    assert proof["shape_mode"] == "dp | bound"
    assert proof["lower_wall_z_interval_m"][1] == proof["fluid_z_interval_m"][0]
    assert proof["upper_wall_z_interval_m"][0] == proof["fluid_z_interval_m"][1]
    copy = review["control_dependency_copy_proof"]
    assert copy["definition_relative_reference"].endswith("_r003_acceleration.csv")
    assert "/generated/acceleration/" in copy["required_generated_copy"]
    assert any("r002" in path for path in copy["r001_and_r002_paths_explicitly_forbidden"])


def test_r003_retains_closed_r002_hswl_failure_without_reuse() -> None:
    review = review_module.build_review()
    r002 = next(item for item in review["closed_prior_scopes"] if item["scope_id"].endswith("R002"))
    assert r002["same_input_retry_forbidden"] is True
    assert r002["r002_output_reuse_forbidden"] is True
    assert "hswl" in r002["failure"]


def test_r003_receipt_is_hash_closed_and_immutable(tmp_path: Path) -> None:
    target = tmp_path / "receipt.json"
    review_module.write_review(target)
    committed = json.loads(target.read_text(encoding="utf-8"))
    assert committed["precommitted_input_bytes"]["materialized"] is False
    assert committed["execution_controls"]["gencase_invoked"] is False
    with pytest.raises(FileExistsError, match="immutable F8 r003 static review"):
        review_module.write_review(target)
    for item in committed["bindings"]:
        path = ROOT / item["path"]
        assert path.is_file()
        assert path.stat().st_size == item["bytes"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]
