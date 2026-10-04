#!/usr/bin/env python3
"""Read-only source checks for the Root 065 qualification-input package."""

from __future__ import annotations

import importlib.util
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F4")
PLAN = ROOT.parent / "root_followup_060_stage1_drop_gap_endpoints_v1/endpoint-plan.json"
METADATA = ROOT.parent / "root_followup_062_stage1_drop_gap_request_readiness_v1/metadata"
ACTUAL_INDEX = DATA / (
    "F4_DROP_GAP_ENDPOINTS/root-stage1-f4-gap0180-0260-actual-native-initial-qa-069/"
    "initial-qa/initial-native-audit-index.json"
)
GENCASE_RESULT = DATA / (
    "F4_DROP_GAP_ENDPOINTS/root-stage1-f4-gap0180-0260-genuine-gencase-063/"
    "gencase-preflight-result.json"
)
ORIGINAL_RECEIPT = DATA / (
    "F4_DROP_GAP_ENDPOINTS/root-stage1-f4-gap0180-0260-genuine-gencase-063/"
    "execution-receipt.json"
)
MOTHER_XML = DATA / (
    "F4_DROP_CENTERED_REFERENCE_001_DP010/gencase-centered-reference-002/"
    "F4_DROP_CENTERED_REFERENCE_001_DP010.xml"
)
MOTHER_RECEIPT = DATA / (
    "F4_DROP_CENTERED_REFERENCE_001_DP010/qualification-centered-fullwindow-001/"
    "execution-receipt.json"
)
ENDPOINTS = (
    "F4_DROP_ENDPOINT_GAP0p18000_DP010",
    "F4_DROP_ENDPOINT_GAP0p26000_DP010",
)


def load_worker():
    path = ROOT / "workers/build_f4_gap_qualification_bindings_v1.py"
    spec = importlib.util.spec_from_file_location("f4_065_builder", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_worker_compiles_and_mother_recipe_is_exact():
    worker = load_worker()
    recipe = worker.validate_mother_recipe(MOTHER_XML, MOTHER_RECEIPT)
    assert recipe["solver_options"] == ["-tmax:1.2", "-tout:0.001"]
    assert recipe["expected_frames"] == 1201
    assert recipe["no_slip_boundary_inheritance"] == {
        "boundary_model": "DBC",
        "ViscoTreatment": 1,
        "Visco": 0.08,
        "ViscoBoundFactor": 1,
    }
    assert recipe["dt_cfl_inheritance"]["cflnumber"] == 0.2
    assert recipe["dt_cfl_inheritance"]["CoefDtMin"] == 0.05


def test_actual_qa_and_original_failure_are_read_only_bound():
    worker = load_worker()
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    index = json.loads(ACTUAL_INDEX.read_text(encoding="utf-8"))
    actual = worker.validate_actual_qa(index_path=ACTUAL_INDEX, index=index, plan=plan)
    commands = worker.validate_original_bindings(
        plan_path=PLAN,
        plan=plan,
        gencase_result_path=GENCASE_RESULT,
        gencase_result=json.loads(GENCASE_RESULT.read_text(encoding="utf-8")),
        original_receipt_path=ORIGINAL_RECEIPT,
        original_receipt=json.loads(ORIGINAL_RECEIPT.read_text(encoding="utf-8")),
    )
    assert set(actual) == set(ENDPOINTS)
    assert set(commands) == set(ENDPOINTS)
    for endpoint_id in ENDPOINTS:
        row = actual[endpoint_id]
        metadata = json.loads((METADATA / f"{endpoint_id}.metadata.json").read_text(encoding="utf-8"))
        counts = worker.generated_particle_counts(row["xml_path"], metadata)
        assert counts["total_particles"] == 83233
        assert counts["fixed_particles"] == 24161
        assert counts["fluid_particles"] == 59072
        assert counts["counts_by_source"] == {"drop": 5824, "pool": 53248}
        assert row["index_row"]["checks"]["true_3d"] is True
        assert commands[endpoint_id]["executed"] is True
        assert commands[endpoint_id]["returncode"] == 0

    original = json.loads(ORIGINAL_RECEIPT.read_text(encoding="utf-8"))
    assert original["status"] == "failed"
    assert original["returncode"] == 0
    assert original["error"] == "GenCase actual particle count missing"


def test_source_binding_keeps_the_reviewed_069_index_hash():
    binding = json.loads((ROOT / "source-binding.json").read_text(encoding="utf-8"))
    digest = hashlib.sha256(ACTUAL_INDEX.read_bytes()).hexdigest()
    assert binding["actual_qa_index_sha256"] == digest
    assert binding["actual_qa_status"] == "initial-native-input-integrity-pass"


def test_templates_are_disabled_and_inherit_exact_solver_window():
    for name, endpoint_id in (
        ("qualification_gap0180_template.json", ENDPOINTS[0]),
        ("qualification_gap0260_template.json", ENDPOINTS[1]),
    ):
        request = json.loads((ROOT / "requests" / name).read_text(encoding="utf-8"))
        assert request["template_only"] is True
        assert request["binding_state"] == "materialize_after_069_review_with_builder"
        assert request["case_id"] == endpoint_id
        assert request["launch"] is False
        assert request["launch_allowed"] is False
        assert request["launch_owner"] == "root"
        assert request["command"][-2:] == ["-tmax:1.2", "-tout:0.001"]
        assert request["qualification_scope"]["expected_frames"] == 1201


if __name__ == "__main__":
    test_worker_compiles_and_mother_recipe_is_exact()
    test_actual_qa_and_original_failure_are_read_only_bound()
    test_templates_are_disabled_and_inherit_exact_solver_window()
    print("F4 Root 065 qualification-input source contract: PASS")
