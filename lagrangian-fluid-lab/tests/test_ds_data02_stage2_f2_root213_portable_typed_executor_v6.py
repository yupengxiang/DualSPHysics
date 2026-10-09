"""ROOT230 V6 recursive-closure tests.

The fixtures are bounded JSON and temporary files only.  They exercise the
same V2/V3 rewriter used by the V6 executor, including nested metadata,
directory anchors, and the mutable-ledger reference boundary.  No production
H5, BI4, native frame, result payload, ledger, or parent reservation is read
or changed.
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
    "ds_data02_stage2_f2_root213_portable_typed_executor_v6.py"
)
RUNTIME_SCRIPT = ROOT / "scripts" / (
    "ds_data02_stage2_f2_typed_only_portable_rebind_v6.py"
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


def _add_root(module, table, source: Path, target: str = "evidence/root.json"):
    stat = module.EXECUTOR_V1._full_stat(source, "fixture root")
    return table.add(
        role="root200_inner_request", source=source, target=target,
        sha256=_sha(source), stat=stat, kind="bounded_nested_metadata",
        deferred=False,
    )


def test_v6_preflights_nested_metadata_with_real_rewriter(tmp_path: Path):
    module = _load(EXECUTOR_SCRIPT, "root213_executor_v6_recursive_graph_test")
    source = tmp_path / "source"
    relocated = tmp_path / "relocated"
    source.mkdir()
    relocated.mkdir()
    grandchild = source / "grandchild.json"
    grandchild.write_text(json.dumps({"value": 7}, sort_keys=True) + "\n")
    child = source / "child.json"
    child.write_text(json.dumps({
        "historical_provenance": {
            "grandchild": {"path": str(grandchild), "sha256": _sha(grandchild)}
        }
    }, sort_keys=True) + "\n")
    parent = source / "parent.json"
    parent.write_text(json.dumps({
        "historical_provenance": {
            "child": {"path": str(child), "sha256": _sha(child)}
        }
    }, sort_keys=True) + "\n")

    table = module.EXECUTOR_V1._ArtifactTable(relocated)
    _add_root(module, table, parent)
    module._install_hooks()
    try:
        discoveries = module._collect_recursive_metadata(table)
        checks = module._preflight_recursive_rewrites(table, relocated)
    finally:
        module._restore_hooks()

    assert {Path(item["source_path"]).name for item in discoveries} == {
        "child.json", "grandchild.json"
    }
    assert checks
    assert all(item["status"] == "PASS_REWRITE_PREFLIGHT" for item in checks)


def test_v6_rebinds_filesystem_headroom_directory_anchor(tmp_path: Path):
    module = _load(RUNTIME_SCRIPT, "root213_runtime_v6_directory_alias_test")
    root = tmp_path / "relocated"
    root.mkdir()
    expected = root / "runtime" / "filesystem-headroom" / "home"
    assert module._directory_rebind_v6(("filesystem_headroom", "home"), root) == expected
    assert module._directory_rebind_v6(("filesystem_headroom", "home", "path"), root) == expected


def test_v6_bounded_json_pointer_is_not_misclassified_as_payload(tmp_path: Path):
    module = _load(EXECUTOR_SCRIPT, "root213_executor_v6_bounded_pointer_test")
    source = tmp_path / "pointer.json"
    source.write_text(json.dumps({"nested": True}) + "\n")
    root = tmp_path / "relocated"
    root.mkdir()
    table = module.EXECUTOR_V1._ArtifactTable(root)
    parent = {"path": str(source), "file_sha256": _sha(source), "bytes": 10**9}
    item = module._add_recursive_role(
        table, source, parent, root, ("source_request", "pointer")
    )
    assert item["deferred_content"] is False
    assert item["placeholder_only"] is False
    assert item["source_sha256"] == _sha(source)


def test_v6_live_ledger_becomes_admin_reference_only(tmp_path: Path):
    module = _load(EXECUTOR_SCRIPT, "root213_executor_v6_ledger_reference_test")
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    ledger = runtime / "resource-ledger.json"
    ledger.write_text('{"mutable": true}\n')
    root = tmp_path / "relocated"
    root.mkdir()
    table = module.EXECUTOR_V1._ArtifactTable(root)
    stat = module.EXECUTOR_V1._full_stat(ledger, "fixture live ledger")
    item = table.add(
        role="parent_resource_ledger", source=ledger,
        target="runtime/resource-ledger.json", sha256=_sha(ledger), stat=stat,
        kind="administrative_source", deferred=True, placeholder=True,
    )
    reference = module._prepare_administrative_ledger_reference(table, root)
    assert reference is not None
    assert reference["logical_role"] == "administrative_ledger_reference_v6"
    assert reference["scientific_input"] is False
    assert reference["content_read_by_manifest"] is False
    assert reference["content_verification_phase"] == "OUTER_PARENT_LEDGER_ONLY"
    sidecar = root / "runtime/administrative-ledger-reference-v6.json"
    assert sidecar.is_file()
    sidecar_value = json.loads(sidecar.read_text(encoding="utf-8"))
    assert sidecar_value["scientific_input"] is False
    assert sidecar_value["outer_parent_ledger_owner"] is True
    assert table.get(ledger) is reference
    assert item not in table.items


def test_v6_rejects_unknown_actionable_absolute_path(tmp_path: Path):
    module = _load(EXECUTOR_SCRIPT, "root213_executor_v6_unknown_path_test")
    with pytest.raises(module.Root213ExecutorV6Error, match="unbound nested metadata path"):
        module._assert_closed(
            {"source_request": {"path": "/unbound/metadata.json"}},
            tmp_path / "relocated",
        )


def test_v6_generated_trace_rebind_is_attempt_local(tmp_path: Path):
    module = _load(EXECUTOR_SCRIPT, "root213_executor_v6_generated_output_test")
    root = tmp_path / "relocated"
    value = {"trace": {"path": "/old/trace.log"},
             "expected_artifacts": [{"trace_path": "/old/final.trace"}]}
    rebound = module._rebase_generated_outputs(value, root)
    assert rebound["trace"]["path"] == str(root / "runtime/generated/trace.log")
    assert rebound["expected_artifacts"][0]["trace_path"] == str(
        root / "runtime/generated/final.trace"
    )
