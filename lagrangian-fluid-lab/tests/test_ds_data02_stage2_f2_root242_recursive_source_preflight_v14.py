"""ROOT242 V14 recursive source-closure preflight tests.

The production case is metadata-only: it walks the already-bound ROOT242
request graph and verifies every actionable source edge before a parent can
reserve or copy anything.  The fixture cases exercise the same V2 rewrite
entry point with terminal evidence, a nested request, a missing source, and a
live ledger.  They do not read production H5/BI4/JSONL data or mutate a
ledger.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_root242_recursive_source_preflight_v14.py"
PRIMARY_ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
ACTUAL_REQUEST = (
    PRIMARY_ROOT
    / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/"
    / "portable-typed-root242-v13-root-forward-242-004.json"
)


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


V14 = _load(SCRIPT, "root242_recursive_source_preflight_v14_test")


def _write_json(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _tiny_graph(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    """Create the complete nested shape that failed in ROOT242 V13."""
    terminal_delta = _write_json(
        tmp_path / "terminal-cpu-delta-reconciliation-v4.json",
        {"schema": "ds02.stage2.terminal-cpu-delta.v4", "status": "CLOSED"},
    )
    terminal_evidence = _write_json(
        tmp_path / "actual-terminal-systemd-cpu-evidence.json",
        {"schema": "ds02.stage2.systemd-cpu-evidence.v1", "cpu_ns": 1234},
    )
    nested = _write_json(
        tmp_path / "nested-source-request.json",
        {
            "schema": "ds02.stage2.root242.nested-source.v1",
            "v66_parent_binding": {
                "terminal_delta": {"path": str(terminal_delta)},
                "terminal_evidence": {"path": str(terminal_evidence)},
            },
        },
    )
    inner = _write_json(
        tmp_path / "root200-inner-request.json",
        {
            "schema": "ds02.stage2.root242.inner.v1",
            "v12_forward": {
                "output_root_rebind_v14": {
                    "path": str(tmp_path / "historical-output"),
                }
            },
            "v66_parent_binding": {
                "terminal_delta": {"path": str(terminal_delta)},
                "terminal_evidence": {"path": str(terminal_evidence)},
            },
            "source_request": {"path": str(nested)},
        },
    )
    return inner, nested, terminal_delta, terminal_evidence


@pytest.mark.skipif(not ACTUAL_REQUEST.is_file(), reason="primary ROOT242 request is not mounted")
def test_actual_root242_v14_walks_complete_graph_without_payload_read(tmp_path: Path) -> None:
    result = V14.preflight_actual(
        request_path=ACTUAL_REQUEST,
        target_root=tmp_path / "fresh-root242-v14",
    )

    assert result["status"] == "READY_FOR_PARENT_GUARD_METADATA_ONLY"
    assert result["base_role_count"] == 50
    assert result["role_count"] >= 52
    assert result["document_count"] >= 8
    assert result["unbound_actionable_paths"] == []
    assert result["graph_errors"] == []
    assert result["rewrite"]["errors"] == []
    assert result["rewrite"]["v2_rewrite_invoked"] is True
    assert result["policy"]["payload_content_read_by_builder"] is False
    assert result["policy"]["hdf5_bi4_jsonl_content_read_by_builder"] is False
    assert result["policy"]["ledger_mutated"] is False
    assert result["policy"]["portable_cold_replay_credit"] == "NOT_CLAIMED"

    discovered = {
        row["source_path_provenance"]: row
        for row in result["roles"]
        if row["logical_role"].startswith("v14_discovered_")
    }
    assert any(path.endswith("terminal-cpu-delta-reconciliation-v4.json")
               for path in discovered)
    assert any(path.endswith("actual-terminal-systemd-cpu-evidence.json")
               for path in discovered)
    binding_pointers = {
        row["pointer"] for row in result["nested_actionable_bindings"]
        if row.get("actionable")
    }
    assert "/v66_parent_binding/terminal_delta/path" in binding_pointers
    assert "/v66_parent_binding/terminal_evidence/path" in binding_pointers


def test_v14_tiny_complete_nested_graph_rewrites_terminal_evidence(tmp_path: Path) -> None:
    inner, nested, terminal_delta, terminal_evidence = _tiny_graph(tmp_path)
    result = V14.preflight_inner(
        inner_path=inner, roles=[], target_root=tmp_path / "fresh-target",
    )

    assert result["status"] == "READY_FOR_PARENT_GUARD_METADATA_ONLY"
    assert result["document_count"] == 2
    assert result["role_count"] == 3
    assert result["unbound_actionable_paths"] == []
    assert result["rewrite"]["errors"] == []
    assert result["policy"]["payload_content_read_by_builder"] is False
    assert {Path(row["source_path_provenance"]).name for row in result["roles"]} == {
        nested.name, terminal_delta.name, terminal_evidence.name,
    }
    pointers = [row["pointer"] for row in result["nested_actionable_bindings"]]
    assert pointers.count("/v66_parent_binding/terminal_delta/path") == 2
    assert pointers.count("/v66_parent_binding/terminal_evidence/path") == 2


def test_v14_rejects_missing_nested_actionable_source(tmp_path: Path) -> None:
    missing = tmp_path / "missing-terminal-delta.json"
    inner = _write_json(
        tmp_path / "inner.json",
        {
            "schema": "ds02.stage2.root242.inner.v1",
            "v66_parent_binding": {"terminal_delta": {"path": str(missing)}},
        },
    )
    result = V14.preflight_inner(
        inner_path=inner, roles=[], target_root=tmp_path / "fresh-target",
    )

    assert result["status"] == "REJECTED_RECURSIVE_ACTIONABLE_CLOSURE"
    assert any(row["pointer"] == "/v66_parent_binding/terminal_delta/path"
               and row["path"] == str(missing)
               for row in result["unbound_actionable_paths"])
    assert result["rewrite"]["v2_rewrite_invoked"] is False


def test_v14_requires_frozen_snapshot_for_live_ledger(tmp_path: Path) -> None:
    live_ledger = _write_json(tmp_path / "resource-ledger.json", {"charges": []})
    inner = _write_json(
        tmp_path / "inner.json",
        {
            "schema": "ds02.stage2.root242.inner.v1",
            "source_request": {"path": str(live_ledger)},
        },
    )
    result = V14.preflight_inner(
        inner_path=inner, roles=[], target_root=tmp_path / "fresh-target",
    )

    assert result["status"] == "REJECTED_RECURSIVE_ACTIONABLE_CLOSURE"
    assert any(row["kind"] == "live_ledger_requires_frozen_snapshot"
               for row in result["unbound_actionable_paths"])
    assert result["policy"]["ledger_mutated"] is False
