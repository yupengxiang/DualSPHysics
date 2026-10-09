"""Strict V7 source-closure tests.

These tests use only tiny temporary JSON files.  They cover the forward
contract that V6 could not express: report/receipt paths are actionable when
they are inputs, missing source identities fail closed, and only the explicitly
identified mutable parent ledger is converted to an administrative reference.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
EXECUTOR_SCRIPT = ROOT / "scripts" / (
    "ds_data02_stage2_f2_root213_portable_typed_executor_v7.py"
)
RUNTIME_SCRIPT = ROOT / "scripts" / (
    "ds_data02_stage2_f2_typed_only_portable_rebind_v7.py"
)


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _root(module, table, source: Path, target: str = "evidence/root.json"):
    return table.add(
        role="root200_inner_request", source=source, target=target,
        sha256=_sha(source),
        stat=module.EXECUTOR_V1._full_stat(source, "V7 fixture root"),
        kind="bounded_nested_metadata", deferred=False,
    )


def test_v7_report_and_receipt_are_recursive_sealed_inputs(tmp_path: Path):
    module = _load(EXECUTOR_SCRIPT, "root213_executor_v7_report_input_test")
    source = tmp_path / "source"
    relocated = tmp_path / "relocated"
    source.mkdir()
    relocated.mkdir()
    receipt = source / "receipt.json"
    receipt.write_text(json.dumps({"status": "COMPLETED", "value": 3}) + "\n")
    report = source / "report.json"
    report.write_text(json.dumps({
        "receipt": {"path": str(receipt), "sha256": _sha(receipt)},
        "status": "PASS",
    }, sort_keys=True) + "\n")
    parent = source / "parent.json"
    parent.write_text(json.dumps({
        "report": {"path": str(report), "sha256": _sha(report)},
    }, sort_keys=True) + "\n")

    table = module.EXECUTOR_V1._ArtifactTable(relocated)
    _root(module, table, parent)
    module._install_hooks()
    try:
        discoveries = module._collect_recursive_metadata(table)
        checks = module._preflight_recursive_rewrites(table, relocated)
    finally:
        module._restore_hooks()

    discovered = {Path(item["source_path"]).name for item in discoveries}
    assert {"report.json", "receipt.json"} <= discovered
    assert {Path(item["source_path_provenance"]).name for item in table.items} >= {
        "parent.json", "report.json", "receipt.json",
    }
    assert checks
    assert all(item["status"] == "PASS_REWRITE_PREFLIGHT" for item in checks)


def test_v7_report_without_sha_fails_closed(tmp_path: Path):
    module = _load(EXECUTOR_SCRIPT, "root213_executor_v7_missing_report_sha_test")
    source = tmp_path / "source"
    relocated = tmp_path / "relocated"
    source.mkdir()
    relocated.mkdir()
    report = source / "report.json"
    report.write_text('{"status":"PASS"}\n')
    parent = source / "parent.json"
    parent.write_text(json.dumps({"report": {"path": str(report)}}) + "\n")
    table = module.EXECUTOR_V1._ArtifactTable(relocated)
    _root(module, table, parent)

    module._install_hooks()
    try:
        with pytest.raises(module.Root213ExecutorV7Error, match="no declared SHA"):
            module._collect_recursive_metadata(table)
    finally:
        module._restore_hooks()


def test_v7_only_active_ledger_is_replaced(tmp_path: Path):
    module = _load(EXECUTOR_SCRIPT, "root213_executor_v7_ledger_scope_test")
    runtime = tmp_path / "runtime"
    archive = tmp_path / "archive" / "runtime"
    runtime.mkdir()
    archive.mkdir(parents=True)
    active = runtime / "resource-ledger.json"
    frozen = archive / "resource-ledger.json"
    active.write_text('{"mutable":true}\n')
    frozen.write_text('{"frozen":true}\n')
    root = tmp_path / "relocated"
    root.mkdir()
    table = module.EXECUTOR_V1._ArtifactTable(root)
    active_item = table.add(
        role="parent_resource_ledger", source=active,
        target=f"evidence/closure/{_sha(active)}-resource-ledger.json",
        sha256=_sha(active), stat=module.EXECUTOR_V1._full_stat(active, "active"),
        kind="administrative_source", deferred=True, placeholder=True,
    )
    frozen_item = table.add(
        role="frozen_ledger_snapshot", source=frozen,
        target="evidence/historical/resource-ledger.json",
        sha256=_sha(frozen), stat=module.EXECUTOR_V1._full_stat(frozen, "frozen"),
        kind="bounded_nested_metadata", deferred=False, placeholder=False,
    )
    module._configure_live_ledger_items(table.items)
    assert module._is_live_ledger(active)
    assert not module._is_live_ledger(frozen)
    reference = module._prepare_administrative_ledger_reference(table, root)
    assert reference is not None
    assert reference["logical_role"] == "administrative_ledger_reference_v7"
    assert table.get(active) is reference
    assert table.get(frozen) is frozen_item
    assert active_item not in table.items
    assert (root / "runtime/administrative-ledger-reference-v7.json").is_file()


def test_v7_generated_trace_without_sha_stays_output_only(tmp_path: Path):
    module = _load(EXECUTOR_SCRIPT, "root213_executor_v7_generated_trace_test")
    root = tmp_path / "relocated"
    value = {
        "trace": {"path": "/old/trace.log"},
        "expected_artifacts": [{"trace_path": "/old/final.trace"}],
        "report": {"path": "/unbound/report.json"},
    }
    records = module._strict_path_records_v7(value)
    assert not any(path.endswith("trace.log") or path.endswith("final.trace")
                   for path, _, _ in records)
    assert any(path.endswith("report.json") for path, _, _ in records)
    rebound = module._rebase_generated_outputs(value, root)
    assert rebound["trace"]["path"] == str(root / "runtime/generated/trace.log")
    assert rebound["expected_artifacts"][0]["trace_path"] == str(
        root / "runtime/generated/final.trace"
    )
