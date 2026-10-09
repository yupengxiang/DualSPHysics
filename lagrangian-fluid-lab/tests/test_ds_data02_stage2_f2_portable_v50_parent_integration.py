from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V50_EXEC = _load("ds02_v50_executor", ROOT / "scripts" / "ds_data02_stage2_f2_portable_executor_v50.py")
V50_PARENT = _load("ds02_v50_parent", ROOT / "scripts" / "ds_data02_stage2_f2_portable_parent_v50.py")
PARENT_V3 = _load("ds02_parent_v3", ROOT / "scripts" / "ds_data02_stage2_f2_portable_executor_parent_v3.py")


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _binding(path: Path, role: str) -> dict:
    info = path.stat()
    return {
        "role": role, "path": str(path), "sha256": V50_PARENT.sha256_file(path),
        "bytes": info.st_size, "mtime_ns": info.st_mtime_ns,
        "mode_bits": info.st_mode & 0o777, "immutable": True,
    }


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path]:
    external = tmp_path / "external"
    external.mkdir()
    source = tmp_path / "source.py"
    source.write_text("# metadata-only fixture source\n", encoding="utf-8")
    source_sha = V50_EXEC.sha256_file(source)
    source_bytes = source.stat().st_size
    target = external / "bundle-target"
    products = external / "products"
    v49 = {
        "schema": V50_EXEC.V34_SCHEMA,
        "status": V50_EXEC.V49_STATUS,
        "role": "DEVELOPMENT",
        "family_id": "F2",
        "case_id": "fixture-case",
        "model_invoked": False,
        "cfd_invoked": False,
        "raw_opened": False,
        "hdf5_opened": False,
        "qualification": dict(V50_EXEC.UNKNOWN),
        "source_entries": [{
            "role": "v2_worker", "path": str(source), "sha256": source_sha,
            "bytes": source_bytes, "target_relative_path": "runtime/source.py",
            # Deliberately stale V2 mirrors.  V50 must preserve them as
            # provenance and install the current V4 wrapper stat contract.
            "resolved_source_path": str(tmp_path / "old-v2-worker.py"),
            "source_stat_expected": {
                "st_size": 46872, "st_mode": 33204, "mode_bits": 436,
                "st_mtime_ns": 123, "st_ctime_ns": 123, "st_dev": 1,
                "st_ino": 2, "st_nlink": 1, "st_uid": 1001, "st_gid": 1001,
            },
        }],
        "runtime_sources": [{
            "role": "raw_worker_v2", "path": str(source), "sha256": source_sha,
            "bytes": source_bytes, "target_relative_path": "runtime/raw-worker-v2.py",
        }],
        "fresh_roots": {"target_root": str(target), "output_root": str(products)},
        "execution": {
            "original_path_fallback": "FORBIDDEN",
            "decoder_scratch": {
                "wrapper_schema": "ds02.stage2.f2-native-raw-to-typed-label-scratch-wrapper.v4",
                "wrapper_path": str(source),
                "default_tmp_forbidden": True, "cleanup_after_each_frame": True,
                "max_frame_scratch_bytes": 64, "decoder_timeout_seconds": 2.0,
            },
        },
        "forward_v49": {
            "schema": V50_EXEC.V49_FORWARD_SCHEMA,
            "source_closure": {"deduplicated_copy_bytes": source_bytes},
            "static_copy_bytes_after_rebind": source_bytes,
        },
    }
    v49["sha256"] = V50_EXEC.canonical_sha(v49)
    v49_path = tmp_path / "v49-executor.json"
    _write(v49_path, v49)
    v50_path = tmp_path / "v50-executor.json"
    V50_EXEC.build_forward(v49_request=v49_path, output_request=v50_path)

    data_root = tmp_path / "data-root"
    ledger_path = data_root / "runtime" / "resource-ledger.json"
    _write(ledger_path, {
        "schema": "ds02.resource-ledger.test.v1",
        "deadline_utc": "2099-01-01T00:00:00+00:00",
        "limits": {"storage_policy": "home_free_floor", "home_min_free_bytes": 128},
        "charges": [], "reservations": [], "attempts": [],
    })
    home = tmp_path / "home"
    home.mkdir()
    old_supervisor = external / "old-supervisor"
    old_receipt = tmp_path / "old-receipt.json"
    base = {
        "schema": V50_PARENT.SCHEMA,
        "status": "READY_FOR_PARENT_GUARD",
        "role": "DEVELOPMENT", "family_id": "F2", "case_id": "fixture-case",
        "attempt_id": "old-parent::f2-v47-parent",
        "model_invoked": False, "cfd_invoked": False, "raw_opened": False,
        "hdf5_opened": False, "qualification": dict(V50_PARENT.UNKNOWN),
        "worktree_root": str(ROOT.parent.parent),
        "executor_request": {"path": str(v49_path), "sha256": V50_EXEC.sha256_file(v49_path),
                              "schema": V50_PARENT.EXECUTOR_SCHEMA, "immutable": True},
        "executor_script": _binding(ROOT / "scripts" / "ds_data02_stage2_f2_portable_executor_v45.py", "executor_v45"),
        "runtime_binding": _binding(ROOT / "scripts" / "ds_data02_runtime_v6.py", "shared_runtime_v6"),
        "parent_resource_binding": {
            "ledger_path": str(ledger_path), "storage_policy": "home_free_floor",
            "deadline_utc": "2099-01-01T00:00:00+00:00", "home_path": str(home),
            "home_min_free_bytes": 128, "external_filesystem": str(external),
            "same_parent_ledger": True, "ledger_reset": False, "no_new_data_root": True,
            "reservation_id": "old-reservation", "charge_id": "old-charge",
            "allow_missing_parent": True,
        },
        "storage_scope": {
            "external_filesystem": str(external), "supervisor_output_root": str(old_supervisor),
            "home_receipt_path": str(old_receipt), "home_receipt_bytes": 64,
            "external_reservation_bytes": source_bytes + 1024,
            "source_copy_bytes": source_bytes, "external_min_free_bytes": 1,
            "home_min_free_bytes": 128, "two_filesystem_charge_required": True,
        },
        "execution": {
            "max_wall_seconds": 6000.0, "cpu_reservation_seconds": 6000.0,
            "child_cleanup_grace_seconds": 25.0,
            "original_path_fallback": "FORBIDDEN",
            "trace_path": str(old_supervisor / "os-trace-v34"),
            "strace": {"path": "/usr/bin/strace", "sha256": V50_PARENT.sha256_file("/usr/bin/strace"),
                       "options": ["-ff", "-e", "trace=%file,%process", "-s", "4096"]},
            "thread_environment": {"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1",
                                    "MKL_NUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1"},
            "command": ["/home/jade/venv/python", "--request", str(v49_path)],
        },
        "accounting": {"same_parent_ledger": True, "allow_missing_parent": True},
        "static_bindings": [
            _binding(ROOT / "scripts" / "ds_data02_stage2_f2_external_supervisor_v21.py", "shared_v21_accounting"),
            {**_binding(Path("/usr/bin/strace"), "os_strace")},
            _binding(v49_path, "executor_v34_request"),
        ],
    }
    base["sha256"] = V50_PARENT.canonical_sha(base)
    base_path = tmp_path / "base-parent.json"
    _write(base_path, base)
    return base_path, v50_path, external, ledger_path, source


def test_v50_status_normalization_preserves_unknown_and_source_budget(tmp_path: Path) -> None:
    _base, v50, _external, _ledger, source = _fixture(tmp_path)
    value = json.loads(v50.read_text(encoding="utf-8"))
    assert value["status"] == V50_EXEC.V50_STATUS
    assert value["forward_v50"]["previous_status"] == V50_EXEC.V49_STATUS
    assert value["forward_v50"]["source_closure"]["deduplicated_copy_bytes"] == source.stat().st_size
    assert value["qualification"] == V50_EXEC.UNKNOWN
    assert value["model_invoked"] is False


def test_v50_parent_merges_scope_and_validates_actual_parent_v3(tmp_path: Path) -> None:
    base, v50, external, ledger, _source = _fixture(tmp_path)
    target = external / "bundle-target"
    products = external / "products"
    supervisor = external / "supervisor"
    receipt = tmp_path / "home" / "fresh-receipt.json"
    result = V50_PARENT.build_parent(
        base_parent=base, executor_request=v50,
        parent_output=tmp_path / "parent-v50.json",
        target_root=target, output_root=products,
        supervisor_output_root=supervisor, home_receipt_path=receipt,
        parent_attempt_id="f2-s1-v50-fixture-001",
        external_filesystem=external, external_reservation_bytes=1024,
        home_receipt_bytes=64, external_min_free_bytes=1,
        typed_output_budget_bytes=128, max_wall_seconds=60.0,
        terminal_sealer=ROOT / "scripts" / "ds_data02_stage2_f2_v47_terminal_sealer_v1.py",
        proof_consumer=ROOT / "scripts" / "ds_data02_stage2_f2_fresh_v16_proof_consumer_v11.py",
        evaluator=ROOT / "scripts" / "ds_data02_stage2_f2_no_model_evaluator_v4.py",
    )
    parent_path = Path(result["parent_request"])
    parent = json.loads(parent_path.read_text(encoding="utf-8"))
    assert parent["status"] == "READY_FOR_PARENT_GUARD"
    assert parent["executor_request"]["schema"] == V50_PARENT.EXECUTOR_SCHEMA
    assert parent["storage_scope"]["source_copy_bytes"] > 0
    assert parent["storage_scope"]["external_filesystem"] == str(external)
    assert parent["storage_scope"]["supervisor_output_root"] == str(supervisor)
    assert parent["storage_scope"]["home_receipt_path"] == str(receipt)
    assert parent["v50_forward"]["fresh_product"]["new_v16_result_sha256"] is None
    # This is the real parent-v3 metadata validator, with no reservation or
    # child execution.  It catches the old status/binding/scope regressions.
    bound = PARENT_V3._validate_request(parent_path, verify_static_content=True)
    assert bound["executor"]["status"] == "READY_FOR_PARENT_STAGE2_GUARD"
    assert bound["external_estimate"] == 1024
    assert bound["allow_missing_parent"] is True


def test_v50_refuses_implicit_dependency_paths(tmp_path: Path) -> None:
    base, v50, external, _ledger, _source = _fixture(tmp_path)
    with pytest.raises(V50_PARENT.ParentV50Error, match="must be explicit"):
        V50_PARENT.build_parent(
            base_parent=base, executor_request=v50,
            parent_output=tmp_path / "parent-v50.json",
            target_root=external / "bundle-target", output_root=external / "products",
            supervisor_output_root=external / "supervisor", home_receipt_path=tmp_path / "r.json",
            parent_attempt_id="f2-s1-v50-no-deps-001", external_filesystem=external,
            external_reservation_bytes=_source.stat().st_size + 1024,
            typed_output_budget_bytes=1,
        )


def test_v50_rebinds_v4_wrapper_and_keeps_old_v2_stat_provenance(tmp_path: Path) -> None:
    _base, v50, _external, _ledger, source = _fixture(tmp_path)
    value = json.loads(v50.read_text(encoding="utf-8"))
    row = next(item for item in value["source_entries"] if item["role"] == "v2_worker")
    observed = source.stat()
    assert row["path"] == str(source)
    assert row["resolved_source_path"] == str(source)
    assert row["source_stat_expected"]["st_size"] == observed.st_size
    assert row["source_stat_expected"]["st_mtime_ns"] == observed.st_mtime_ns
    assert row["source_mode_bits"] == (observed.st_mode & 0o777)
    assert row["source_stat_provenance"]["st_size"] == 46872
    binding = value["forward_v50"]["actionable_wrapper_binding"]
    assert binding["current_bytes"] == observed.st_size
    assert binding["old_resolved_source_path"].endswith("old-v2-worker.py")
    assert value["runtime_sources"][0]["path"] == str(source)
