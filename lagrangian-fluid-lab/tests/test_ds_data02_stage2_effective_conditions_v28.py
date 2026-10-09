from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_effective_conditions_v28.py"
V26_INDEX = ROOT / "campaigns/ds-data-02/stage2/lineage/v26-effective-condition-directory/EFFECTIVE_PHYSICAL_SPLIT_INDEX_V26.json"


def _load():
    spec = importlib.util.spec_from_file_location("effective_conditions_v28_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_root241_build_request_collects_full_336_source_closure(tmp_path: Path):
    module = _load()
    result = module.build_request(
        v26_index=V26_INDEX,
        request_dir=tmp_path / "request",
        output_root=tmp_path / "fresh-output",
        ledger_path=tmp_path / "resource-ledger.json",
        attempt_id="manufactured-root241-001",
    )
    request = json.loads(Path(result["request"]).read_text(encoding="utf-8"))
    closure = json.loads(Path(result["closure"]).read_text(encoding="utf-8"))
    assert result["case_count"] == 336
    assert result["role_count"] >= 336
    assert closure["role_counts"]["owner_metadata"] == 336
    assert closure["role_counts"]["generated_xml"] == 336
    assert closure["role_counts"]["conversion_report"] == 336
    assert closure["role_counts"]["solver_receipt"] == 336
    assert closure["role_counts"]["trajectory"] == 336
    assert any(item.get("content_policy") == "STAT_ONLY_DEFERRED_PAYLOAD"
               for item in closure["roles"])
    assert request["parent_resource_binding"]["same_parent_ledger"] is True
    assert request["parent_resource_binding"]["ledger_reset"] is False
    assert request["outputs"]["fresh_attempt_namespace"] is True
    assert request["source_closure"]["owner_xml_receipt_conversion_current_bound"] is True
    assert request["read_policy"]["hdf5"] == "FORBID"


def test_root241_rejects_conflicting_source_declarations():
    module = _load()
    table: dict[str, dict] = {}
    first = {"logical_role": "a", "path": "/tmp/source.json",
             "expected_sha256": "a" * 64, "expected_stat": {"bytes": 1}}
    second = {"logical_role": "b", "path": "/tmp/source.json",
              "expected_sha256": "b" * 64, "expected_stat": {"bytes": 1}}
    module._merge_source(table, first)
    with pytest.raises(module.EffectiveConditionV28Error, match="conflicting declared SHA"):
        module._merge_source(table, second)


def test_root241_rejects_nonfresh_output_namespace(tmp_path: Path):
    module = _load()
    output = tmp_path / "already-used"
    output.mkdir()
    (output / "old-report.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(module.EffectiveConditionV28Error, match="not fresh"):
        module.build_request(
            v26_index=V26_INDEX,
            request_dir=tmp_path / "request",
            output_root=output,
            ledger_path=tmp_path / "resource-ledger.json",
        )


def test_root241_real_metadata_run_closes_source_prepost_without_payload(tmp_path: Path):
    module = _load()
    request = module.build_request(
        v26_index=V26_INDEX,
        request_dir=tmp_path / "request",
        output_root=tmp_path / "fresh-output",
        ledger_path=tmp_path / "resource-ledger.json",
        attempt_id="manufactured-root241-run-001",
    )
    report = module.run(request_path=request["request"], parent_pid=os.getpid())
    assert report["status"] == "COMPLETED_METADATA_ONLY"
    assert report["source_pre"]["checked_roles"] == report["source_post"]["checked_roles"]
    assert report["source_pre"]["checked_roles"] >= 2900
    assert report["v26"]["case_count"] == 336
    assert report["v27"]["case_count"] == 336
    assert report["hdf5_opened"] is False
    assert report["bi4_opened"] is False
    assert report["raw_arrays_opened"] is False
    assert report["jsonl_opened"] is False
    assert report["solver_output_opened"] is False
