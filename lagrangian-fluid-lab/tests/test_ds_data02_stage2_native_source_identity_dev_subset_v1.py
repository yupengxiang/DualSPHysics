from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts/ds_data02_stage2_native_source_identity_dev_subset_v1.py"
SPEC = importlib.util.spec_from_file_location("native_source_identity_dev_subset_v1", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _split_payload(*, safe: str = "UNKNOWN") -> dict:
    return {
        "schema": "ds02.stage2.source-closed-development-split.v25",
        "status": "PREPARED_SOURCE_CLOSED_DEVELOPMENT_SPLIT_V24_ACTUAL_VERIFIED_NO_PHYSICAL_QUALIFICATION",
        "development_split": {
            "assignments": [{"family_id": family, "scientific_split_safe": safe} for family in ("F1", "F2", "F3", "F4", "F5", "F6", "F7")],
            "supported_task_scopes": ["saved_frame_artifact"],
            "cross_component_transfer_edges": [],
        },
    }


def _qualification_payload(*, qn: str = "UNKNOWN") -> tuple[dict, dict]:
    qualification = {
        "schema": "ds02.stage2.final-qualification-catalog.v29",
        "status": "ACTUAL_336_CASE_AUDIT_AND_118_NATIVE_IMPACT_BOUND_NO_SCIENTIFIC_QUALIFICATION",
        "coverage": {"current_cases": 336, "audit_native_intersection": 118, "native_impact_cases": 118},
        "claim_boundary": {key: "UNKNOWN" for key in ("physical_fate", "legal_outflow_or_spill", "dynamical_impact", "QI", "QN", "QE")},
    }
    task_scope = {
        "schema": "ds02.stage2.task-scope-catalog.v30",
        "status": "ACTUAL_V29_TASK_SCOPE_INDEX_WITH_QN_QE_QI_UNKNOWN",
        "task_qualification": {
            "QN": qn, "QE": "UNKNOWN", "QI": "UNKNOWN", "physical_fate": "UNKNOWN",
            "legal_flux": "UNKNOWN", "dynamical_impact": "UNKNOWN", "effective_split_safe": "UNKNOWN",
            "native_mk_motive_and_id": "ELIGIBLE_118_SOURCE_CLOSED_CASES",
            "saved_record_censor": "ELIGIBLE_118_SAVED_BRACKET_CASES",
        },
        "coverage": {},
    }
    return qualification, task_scope


def _write_receipt(root: Path, *, command: list[str]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    receipt = {
        "status": "completed", "returncode": 0, "output_root": str(root), "bytes": 42,
        "model_invoked": False, "cfd_invoked": False,
        "source_preflight": {"status": "PASS_AFTER_RESERVATION"},
        "terminal_storage_guard": {"status": "passed", "actual_bytes": 42},
        "request": {"command": command},
    }
    path = root / "execution-receipt.json"
    path.write_text(json.dumps(receipt) + "\n", encoding="utf-8")
    return path


def _write_root063_fixture(tmp_path: Path, *, bad_f2_ids: bool = False) -> tuple[Path, Path, Path, Path]:
    f2_root = tmp_path / "f2"
    f2_root.mkdir(parents=True, exist_ok=True)
    f2_report = f2_root / "f2-report.json"
    ids = [397194, 403829, 404024] if not bad_f2_ids else [1, 2, 3]
    f2_report.write_text(json.dumps({
        "schema": "ds02.stage2.f2-s1-native-source-adapter.v3",
        "status": "COMPLETED_F2_S1_NATIVE_SOURCE_JOIN_WITH_PHYSICAL_FATE_UNKNOWN",
        "native_identity": {"id_count": 3, "ids": [{"idp": value} for value in ids], "motive_counts": {"density": 0, "movement": 0, "position": 3}},
        "claim_boundary": {"physical_fate": "UNKNOWN; native numerical position exclusion is not legal spill or physical outflow"},
        "read_policy": {"trajectory_h5_opened": False, "part_frames_opened": False},
    }) + "\n", encoding="utf-8")
    f2_receipt = _write_receipt(f2_root, command=["adapter-v3"])
    half_receipt = _write_receipt(tmp_path / "f1-half", command=["/opt/PartVTKOut_linux64"])
    same_receipt = _write_receipt(tmp_path / "f1-same", command=["/opt/PartVTKOut_linux64"])
    return f2_report, f2_receipt, half_receipt, same_receipt


def test_split_reference_keeps_scientific_safety_unknown():
    result = MODULE._split_reference(_split_payload())
    assert result["scientific_split_safe"] == "UNKNOWN"
    assert result["assignments"][0]["family_id"] == "F1"


def test_split_reference_rejects_widened_scientific_safety():
    with pytest.raises(MODULE.AuditError, match="scientific split safety"):
        MODULE._split_reference(_split_payload(safe="PASS"))


def test_qualification_reference_preserves_task_unknowns():
    qualification, task_scope = _qualification_payload()
    result = MODULE._qualification_reference(qualification, task_scope)
    assert result["v30_task_qualification"]["native_mk_motive_and_id"] == "ELIGIBLE_118_SOURCE_CLOSED_CASES"
    with pytest.raises(MODULE.AuditError, match="unknown qualification"):
        bad_qualification, bad_scope = _qualification_payload(qn="PASS")
        MODULE._qualification_reference(bad_qualification, bad_scope)


def test_root063_lineage_binds_singleton_and_official_decoders(tmp_path: Path):
    f2_report, f2_receipt, half_receipt, same_receipt = _write_root063_fixture(tmp_path)
    result = MODULE._root063_lineage(f2_report, f2_receipt, half_receipt, same_receipt)
    assert result["f2_s1_singleton"]["native_ids"] == [397194, 403829, 404024]
    assert result["f1_half_decoder_receipt"]["official_tool"] == "PartVTKOut"


def test_root063_lineage_rejects_wrong_singleton_ids(tmp_path: Path):
    f2_report, f2_receipt, half_receipt, same_receipt = _write_root063_fixture(tmp_path, bad_f2_ids=True)
    with pytest.raises(MODULE.AuditError, match="native identity set"):
        MODULE._root063_lineage(f2_report, f2_receipt, half_receipt, same_receipt)
