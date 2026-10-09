from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f7_s1_initial_spatial_qa_v1.py"
REQUEST_DIR = ROOT / "campaigns/ds-data-02/stage2/requests/f7-s1-initial-spatial-qa-v1-root-prepared-141-001"
MANIFEST = REQUEST_DIR / "f7-s1-initial-spatial-qa-v1-manifest.json"
REQUEST = REQUEST_DIR / "f7-s1-initial-spatial-qa-v1-request.json"


def loaded():
    spec = importlib.util.spec_from_file_location("f7_s1_initial_spatial_qa_v1", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_actual_manifest_source_closure_is_metadata_only():
    module = loaded()
    manifest, refs, docs = module._validate_static_manifest(MANIFEST)
    assert manifest["schema"].endswith("initial-spatial-qa.manifest.v1")
    assert len(refs) == 15
    assert docs["current336"]["cases"][288]["physical_case_id"] == module.CASE_ID
    assert manifest["deferred_inputs"]["initial_bi4"]["sha256"] == "e618440bc55384f8942506929f98ac4c688a8585bf017b532cafbc8ada839425"
    assert manifest["deferred_inputs"]["native_frame0"]["sha256"] == "PARENT_GUARD_COMPUTED"
    assert manifest["contract"]["deferred_read_scope"] == "one prepared BI4 and one native Part_0000 frame only"
    assert manifest["contract"]["hdf5_read"] is False


def test_request_defers_only_two_frame_zero_bi4_inputs():
    request = json.loads(REQUEST.read_text(encoding="utf-8"))
    assert request["case_id"] == "DS02_STAGE2_F7_S1_INITIAL_SPATIAL_QA_V1"
    assert request["cpu_task_kind"] == "audit"
    assert request["command"][1].endswith("ds_data02_stage2_f7_s1_initial_spatial_qa_v1.py")
    assert request["command"][3] == str(MANIFEST.resolve())
    assert request["deferred_input_file_count"] == 2
    assert request["bi4_read"] is True
    assert request["hdf5_read"] is False
    assert request["solver_launch"] is False
    assert request["gpu_launch"] is False
    assert request["guard_policy"]["later_native_frames_opened"] == 0
    assert request["source_binding"]["current336_case_index"] == 288
    assert request["source_binding"]["current336_exact_case_binding"] is True


def test_wrong_current_identity_is_rejected_without_opening_deferred_payloads(tmp_path: Path):
    module = loaded()
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    current_entry = next(row for row in payload["source_refs"] if row["key"] == "current336")
    current_copy = tmp_path / "CURRENT336-wrong.json"
    current = json.loads(Path(current_entry["path"]).read_text(encoding="utf-8"))
    current["cases"][288]["physical_case_id"] = "F7_WRONG_CASE"
    current_copy.write_text(json.dumps(current), encoding="utf-8")
    current_entry["path"] = str(current_copy)
    current_entry["sha256"] = module.sha256_file(current_copy)
    mutated = tmp_path / "manifest.json"
    mutated.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(module.SpatialQAError, match="CURRENT288 physical case"):
        module._validate_static_manifest(mutated)


def test_deferred_hdf5_substitution_is_rejected_before_any_payload_read(tmp_path: Path):
    module = loaded()
    payload = copy.deepcopy(json.loads(MANIFEST.read_text(encoding="utf-8")))
    payload["deferred_inputs"]["native_frame0"]["path"] = str(tmp_path / "wrong.h5")
    mutated = tmp_path / "manifest.json"
    mutated.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(module.SpatialQAError, match="not a BI4"):
        module._validate_static_manifest(mutated)


def test_claim_boundary_keeps_owner_and_science_qualification_unknown():
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert "UNKNOWN" in payload["claim_boundary"] or payload["contract"]["continuous_owner_equivalence"] == "UNKNOWN"
    assert payload["contract"]["continuous_owner_equivalence"] == "UNKNOWN"
    assert payload["contract"]["all_qi_qn_qe"] == "UNKNOWN"
