"""Tests for the additive .01 s matched RV4 spatial-reference requests."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET


REQUEST_ROOT = (
    Path(__file__).resolve().parents[1]
    / "handoff_20261003/rv4_matched_three_dp_init_v1/solver_requests_spatial_reference_v1"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def test_four_requests_bind_additive_01_inputs_and_terminal_gencase():
    requests = sorted(REQUEST_ROOT.glob("*_request.json"))
    assert len(requests) == 4
    physical_cases = set()
    for path in requests:
        request = json.loads(path.read_text(encoding="utf-8"))
        assert request["case_id"].endswith("_SPATIAL_REFERENCE_SAVE010")
        assert request["root_only"] is True
        assert request["gpu_launch"]["family_owner_launch"] is False
        assert request["gencase_receipt_sha256"] == sha256(Path(request["gencase_receipt"]))
        receipt = json.loads(Path(request["gencase_receipt"]).read_text(encoding="utf-8"))
        assert receipt["status"] == "completed"
        assert receipt["returncode"] == 0
        assert receipt["solver_dimension_from_gencase"] == 3
        assert receipt["total_particles"] > receipt["fluid_particles"] > 0

        prefix = Path(request["gencase_prefix"])
        xml = prefix.with_name(prefix.name + ".xml")
        bi4 = prefix.with_name(prefix.name + ".bi4")
        motion = Path(request["derived_solver_inputs"]["derived_motion"])
        assert xml.is_file() and bi4.is_file() and motion.is_file()
        assert request["input_sha256"][str(xml)] == sha256(xml)
        assert request["input_sha256"][str(bi4)] == sha256(bi4)
        assert request["input_sha256"][str(motion)] == sha256(motion)

        values = {
            node.attrib.get("key"): node.attrib.get("value")
            for node in ET.parse(xml).getroot().findall(".//execution/parameters/parameter")
        }
        assert float(values["TimeMax"]) == 4.0
        assert float(values["TimeOut"]) == 0.01
        assert request["numerical_recipe_fields"]["frame_count_expected"] == 401
        assert request["estimated_storage_bytes"] == math.ceil(receipt["total_particles"] * 401 * 64 * 1.5)
        assert request["q_n_status"] == "not_assessed"
        assert request["new_independent_physical_case_count"] == 0
        physical_cases.add(request["physical_case_id"])
    assert physical_cases == {"F2H10V2_CENTER_V1", "F2H10V2_OFFSET_V1"}


def test_derived_xml_changes_only_timeout_and_keeps_event_gate_deferred():
    for path in sorted(REQUEST_ROOT.glob("*_request.json")):
        request = json.loads(path.read_text(encoding="utf-8"))
        source = Path(request["derived_solver_inputs"]["source_xml"])
        derived = Path(request["derived_solver_inputs"]["derived_xml"])
        source_text = source.read_text(encoding="utf-8")
        expected = re.sub(
            r'(<parameter key="TimeOut" value=")([^\"]+)("\s*/>)',
            r"\g<1>0.01\g<3>",
            source_text,
            count=1,
        )
        assert derived.read_text(encoding="utf-8") == expected
        review = request["save_strategy_review"]
        assert review["registered_save_interval_s"] == 0.01
        assert review["registered_half_bracket_s"] == 0.005
        assert review["per_save_allocation_s"] == 0.0001467278159987655
        assert review["registered_recipe_event_qualification"] == "deferred"
        assert request["qualification_claim"].startswith("none;")


def test_spatial_reference_budget_sidecar_is_explicitly_non_event_qualified():
    budget = json.loads((REQUEST_ROOT / "save-budget-review-v1.json").read_text(encoding="utf-8"))
    assert budget["registered_spatial_save_interval_s"] == 0.01
    assert budget["registered_spatial_half_bracket_s"] == 0.005
    assert budget["save_per_study_allocation_s"] == 0.0001467278159987655
    assert budget["registered_spatial_recipe_event_status"] == "deferred"
    assert budget["deferred_event_save_interval_s"] == 0.00025
    assert budget["q_n_status"] == "not_assessed"
