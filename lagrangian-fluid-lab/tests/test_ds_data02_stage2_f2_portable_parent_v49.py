from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "ds_data02_stage2_f2_portable_parent_v49.py"
)
spec = importlib.util.spec_from_file_location("ds02_parent_v49", SCRIPT)
assert spec is not None and spec.loader is not None
parent_v49 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parent_v49)


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _sha(path: Path) -> str:
    return parent_v49.sha256_file(path)


def _canonicalize(value: dict) -> dict:
    value["sha256"] = parent_v49.canonical_sha(value)
    return value


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, int]:
    worker = tmp_path / "raw-worker.py"
    worker.write_text("# tiny immutable worker\n", encoding="utf-8")
    worker_sha = _sha(worker)
    worker_bytes = worker.stat().st_size

    overlay = _canonicalize({
        "schema": "ds02.stage2.f2-native-raw-portable-overlay.v5",
        "entries": [],
        "forward_v49": {
            "schema": parent_v49.V49_OVERLAY_FORWARD_SCHEMA,
            "source_stat_only": True,
            "original_path_fallback": "FORBIDDEN",
        },
    })
    overlay_path = tmp_path / "overlay.json"
    _write_json(overlay_path, overlay)

    closure_rows = [
        {
            "role": "v2_worker",
            "path": str(worker),
            "sha256": worker_sha,
            "bytes": worker_bytes,
            "target_relative_path": "runtime/raw-worker.py",
        },
    ]
    # The same immutable worker is listed in both roles.  The parent builder
    # must charge it once while retaining both role bindings.
    runtime_rows = [
        {
            "role": "raw_worker_v2",
            "path": str(worker),
            "sha256": worker_sha,
            "bytes": worker_bytes,
            "target_relative_path": "runtime/raw-worker-v2.py",
        },
    ]
    executor = {
        "schema": parent_v49.EXECUTOR_SCHEMA,
        "status": "READY_FOR_V49_PARENT",
        "source_entries": closure_rows,
        "runtime_sources": runtime_rows,
        "v5_overlay_template": {
            "path": str(overlay_path),
            "sha256": _sha(overlay_path),
            "canonical_sha256": overlay["sha256"],
        },
        "fresh_roots": {
            "target_root": str(tmp_path / "executor-target"),
            "output_root": str(tmp_path / "executor-products"),
        },
        "execution": {
            "decoder_scratch": {
                "wrapper_schema": "ds02.stage2.f2-native-raw-to-typed-label-scratch-wrapper.v4",
                "default_tmp_forbidden": True,
                "cleanup_after_each_frame": True,
                "max_frame_scratch_bytes": 64,
                "decoder_timeout_seconds": 2.0,
            },
        },
        "forward_v49": {
            "schema": parent_v49.V49_EXECUTOR_FORWARD_SCHEMA,
            "static_copy_bytes_after_rebind": worker_bytes,
            "content_read_during_build": False,
            "payload_hashes_computed_during_build": False,
        },
    }
    executor = _canonicalize(executor)
    executor_path = tmp_path / "executor.json"
    _write_json(executor_path, executor)

    base = _canonicalize({
        "schema": parent_v49.SCHEMA,
        "status": "READY_FOR_PARENT_GUARD",
        "qualification": dict(parent_v49.UNKNOWN),
        "model_invoked": False,
        "parent_resource_binding": {"ledger": "shared-stage2", "policy": "home_floor_plus_external"},
        "accounting": {"same_parent_ledger": True},
        "executor_request": {
            "role": "executor_v34_request",
            "path": str(executor_path),
            "sha256": _sha(executor_path),
        },
        "static_bindings": [{
            "role": "executor_v34_request",
            "path": str(executor_path),
            "sha256": _sha(executor_path),
        }],
    })
    base_path = tmp_path / "base-parent.json"
    _write_json(base_path, base)
    return base_path, executor_path, overlay_path, worker_bytes


def test_build_parent_deduplicates_copy_bytes_and_defers_product_credit(tmp_path: Path) -> None:
    base, executor, _overlay, worker_bytes = _fixture(tmp_path)
    output = tmp_path / "parent-v49.json"
    result = parent_v49.build_parent(
        base_parent=base,
        executor_request=executor,
        parent_output=output,
        target_root=tmp_path / "executor-target",
        output_root=tmp_path / "executor-products",
        parent_attempt_id="f2-s1-v49-test-001",
        home_budget_bytes=128,
        external_budget_bytes=worker_bytes + 64 + 128,
        typed_output_budget_bytes=128,
    )
    assert result["status"] == "READY_FOR_PARENT_GUARD_V49_METADATA"
    value = json.loads(output.read_text(encoding="utf-8"))
    assert value["status"] == "READY_FOR_PARENT_GUARD_V49_METADATA"
    assert value["qualification"] == parent_v49.UNKNOWN
    assert value["parent_resource_binding"]["allow_missing_parent"] is True
    assert value["storage_scope"]["declared_static_copy_bytes"] == worker_bytes
    assert value["storage_scope"]["payload_content_read_during_builder"] is False
    assert value["v49_forward"]["fresh_product"]["new_v16_result_sha256"] is None
    assert value["v49_forward"]["evaluator"]["status"] == "DEFERRED_UNTIL_FRESH_PROOF"
    roles = {row["role"] for row in value["static_bindings"]}
    assert {
        "executor_v49_request",
        "terminal_sealer_v1",
        "fresh_v16_proof_consumer_v11",
        "no_model_evaluator_v4",
        "parent_builder_v49",
    } <= roles


def test_build_parent_rejects_copy_budget_overrun(tmp_path: Path) -> None:
    base, executor, _overlay, worker_bytes = _fixture(tmp_path)
    with pytest.raises(parent_v49.ParentV49Error, match="exceeds external budget"):
        parent_v49.build_parent(
            base_parent=base,
            executor_request=executor,
            parent_output=tmp_path / "parent-v49.json",
            target_root=tmp_path / "executor-target",
            output_root=tmp_path / "executor-products",
            parent_attempt_id="f2-s1-v49-test-budget-001",
            external_budget_bytes=worker_bytes + 64,
            typed_output_budget_bytes=128,
        )


def test_build_parent_rejects_declared_copy_mismatch(tmp_path: Path) -> None:
    base, executor, _overlay, _worker_bytes = _fixture(tmp_path)
    value = json.loads(executor.read_text(encoding="utf-8"))
    value["forward_v49"]["static_copy_bytes_after_rebind"] += 1
    _write_json(executor, _canonicalize(value))
    with pytest.raises(parent_v49.ParentV49Error, match="declared copy bytes differ"):
        parent_v49.build_parent(
            base_parent=base,
            executor_request=executor,
            parent_output=tmp_path / "parent-v49.json",
            target_root=tmp_path / "executor-target",
            output_root=tmp_path / "executor-products",
            parent_attempt_id="f2-s1-v49-test-mismatch-001",
        )
