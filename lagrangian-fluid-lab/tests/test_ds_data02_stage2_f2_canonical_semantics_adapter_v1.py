from __future__ import annotations

import importlib.util
import hashlib
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_canonical_semantics_adapter_v1.py"
SPEC = importlib.util.spec_from_file_location("f2_canonical_semantics_v1", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _binding(tmp_path: Path) -> dict:
    tmp_path.mkdir(parents=True, exist_ok=True)
    stages = []
    for role in MODULE.STAGE_ORDER:
        path = tmp_path / f"{role}.py"
        path.write_text(f"# {role}\n", encoding="utf-8")
        stages.append({"role": role, "path": str(path),
                       "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    return {
        "schema": MODULE.SCHEMA,
        "namespace_root": str(tmp_path),
        "case_identity": {"current_case_index": 65, "physical_case_id": MODULE.CANONICAL_ID},
        "current_binding": {"case_index": 65, "sha256": MODULE.CURRENT_SHA},
        "legacy_operator": {"case_index": 78, "physical_case_id": MODULE.HISTORICAL_ALIAS_ID,
                             "fallback": "REJECT"},
        "stages": stages,
        "source_fallback": "REJECT",
    }


def test_canonical_adapter_binds_pipeline_but_keeps_scientific_work_deferred(tmp_path: Path) -> None:
    value = _binding(tmp_path)
    value["legacy_operator"] = {"case_index": None, "physical_case_id": None, "fallback": "REJECT"}
    result = MODULE.validate(value)
    assert result["status"] == "CANONICAL65_SEMANTICS_BOUND_PARENT_GUARD_REQUIRED"
    assert result["raw_payload_read"] is False
    assert result["typed_or_label_payload_read"] is False
    assert result["legacy_operator"]["row78_reused"] is False


def test_canonical_adapter_rejects_historical_row78_operator(tmp_path: Path) -> None:
    with pytest.raises(MODULE.SemanticsError, match="row-78 operator"):
        MODULE.validate(_binding(tmp_path))


def test_canonical_adapter_rejects_alias_identity_and_bad_stage_order(tmp_path: Path) -> None:
    value = _binding(tmp_path)
    value["legacy_operator"] = {"fallback": "REJECT"}
    value["case_identity"]["physical_case_id"] = MODULE.HISTORICAL_ALIAS_ID
    with pytest.raises(MODULE.SemanticsError, match="RX047/ROT075"):
        MODULE.validate(value)
    value = _binding(tmp_path / "stages")
    value["legacy_operator"] = {"fallback": "REJECT"}
    value["stages"][1], value["stages"][2] = value["stages"][2], value["stages"][1]
    with pytest.raises(MODULE.SemanticsError, match="stage order"):
        MODULE.validate(value)
