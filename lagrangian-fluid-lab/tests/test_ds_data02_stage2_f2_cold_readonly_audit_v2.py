from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_cold_readonly_audit_v2.py"
SPEC = importlib.util.spec_from_file_location("f2_cold_readonly_audit_v2", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def _write_trace(path: Path, *lines: str) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_trace_allows_original_access_only_for_declared_source_pid(tmp_path: Path) -> None:
    prefix = tmp_path / "trace"
    _write_trace(
        tmp_path / "trace.101",
        '101 openat(AT_FDCWD, "/orig/data/PartFluid.bi4", O_RDONLY) = 3',
    )
    _write_trace(
        tmp_path / "trace.202",
        '202 openat(AT_FDCWD, "/relocated/target/runtime/worker.py", O_RDONLY) = 3',
    )

    result = audit.classify_trace(
        prefix,
        source_pids={101},
        private_pids={202},
        original_roots=["/orig/data", "/orig/runtime"],
        target_root="/relocated/target",
        output_root="/relocated/output",
    )

    assert result["unknown_groups"] == []
    assert result["missing_source_pids"] == []
    assert result["missing_private_pids"] == []
    assert result["private_original_path_violations"] == {}
    assert result["groups"]["101"]["access_role"] == "source_copy"
    assert result["groups"]["202"]["access_role"] == "private_worker_or_evaluator"


def test_trace_rejects_private_access_to_original_runtime(tmp_path: Path) -> None:
    prefix = tmp_path / "trace"
    _write_trace(
        tmp_path / "trace.202",
        '202 openat(AT_FDCWD, "/orig/runtime/worker.py", O_RDONLY) = 3',
    )

    result = audit.classify_trace(
        prefix,
        source_pids=set(),
        private_pids={202},
        original_roots=["/orig/runtime"],
        target_root="/relocated/target",
        output_root="/relocated/output",
    )

    assert result["private_original_path_violations"] == {
        "202": ["/orig/runtime/worker.py"]
    }


def test_trace_separates_registered_interpreter_from_unbound_private_paths_and_argv(
    tmp_path: Path,
) -> None:
    prefix = tmp_path / "trace"
    _write_trace(
        tmp_path / "trace.202",
        '202 execve("/bound/.venv/bin/python", ["python", "/orig/provenance.json"], 0) = 0',
        '202 openat(AT_FDCWD, "/bound/.venv/lib/python3.11/site-packages/numpy.py", O_RDONLY) = 3',
        '202 openat(AT_FDCWD, "/tmp/unregistered/secret.json", O_RDONLY) = 3',
        '202 openat(AT_FDCWD, 3, "relative-after-dirfd", O_RDONLY) = 4',
    )

    result = audit.classify_trace(
        prefix,
        source_pids=set(),
        private_pids={202},
        original_roots=["/orig"],
        target_root="/relocated/target",
        output_root="/relocated/output",
        registered_environment_roots=["/bound/.venv", "/usr"],
    )

    # The provenance-looking argv entry is not an open.  The explicitly
    # registered interpreter/site-packages path is environment scope, while
    # the unregistered /tmp path and relative dirfd access remain blockers.
    assert result["private_original_path_violations"] == {}
    assert result["groups"]["202"]["environment_hits"] == [
        "/bound/.venv/bin/python", "/bound/.venv/lib/python3.11/site-packages/numpy.py"
    ]
    assert result["private_unbound_absolute_path_hits"] == {
        "202": ["/tmp/unregistered/secret.json"]
    }
    assert "202" in result["private_unresolved_relative_path_access"]


def test_provenance_without_explicit_license_scope_is_pending(tmp_path: Path) -> None:
    bound = tmp_path / "bound.json"
    bound.write_text('{"bound": true}\n', encoding="utf-8")
    sidecar = {
        "status": "PROVENANCE_ONLY_NOT_EXECUTION_BINDING",
        "bindings": [
            {
                "role": f"role-{index:02d}",
                "path": str(bound),
                "bytes": bound.stat().st_size,
                "sha256": audit.sha256_file(bound),
                "scope": "small runtime provenance",
            }
            for index in range(24)
        ],
        "excluded_content": {"hdf5": True, "bi4": True, "raw_source_tree": True},
    }
    sidecar["sha256"] = audit.canonical_sha(sidecar)

    checked = audit._binding_files(sidecar)

    assert checked["count"] == 24
    assert checked["license_scope_status"] == "MISSING_EXPLICIT_LICENSE_SCOPE"


def test_audit_keeps_missing_fresh_products_pending_without_reading_binary_inputs(
    tmp_path: Path,
) -> None:
    original = tmp_path / "original"
    target = tmp_path / "relocated" / "target"
    output = tmp_path / "relocated" / "output"
    original.mkdir(parents=True)
    (target / "runtime").mkdir(parents=True)
    output.mkdir(parents=True)
    source = original / "request.json"
    runtime = original / "worker.py"
    target_worker = target / "runtime" / "worker.py"
    source.write_text("source\n", encoding="utf-8")
    runtime.write_text("runtime\n", encoding="utf-8")
    target_worker.write_text("relocated\n", encoding="utf-8")

    v34 = {
        "schema": "ds02.stage2.f2-portable-executor-request.v34",
        "source_entries": [{"path": str(source)}],
        "runtime_sources": [{"path": str(runtime)}],
    }
    v34["sha256"] = audit.canonical_sha(v34)
    v34_path = tmp_path / "request-v34.json"
    v34_path.write_text(json.dumps(v34), encoding="utf-8")

    bound = tmp_path / "bound.json"
    bound.write_text('{"bound": true}\n', encoding="utf-8")
    sidecar = {
        "status": "PROVENANCE_ONLY_NOT_EXECUTION_BINDING",
        "bindings": [
            {
                "role": f"role-{index:02d}",
                "path": str(bound),
                "bytes": bound.stat().st_size,
                "sha256": audit.sha256_file(bound),
                "scope": "small runtime provenance",
            }
            for index in range(24)
        ],
        "excluded_content": {"hdf5": True, "bi4": True, "raw_source_tree": True},
    }
    sidecar["sha256"] = audit.canonical_sha(sidecar)
    sidecar_path = tmp_path / "provenance.json"
    sidecar_path.write_text(json.dumps(sidecar), encoding="utf-8")

    private_audit = target / "runtime-audit.json"
    private_audit.write_text("{}\n", encoding="utf-8")
    raw_report = output / "raw-report.json"
    raw_report.write_text("{}\n", encoding="utf-8")
    executor = {
        "original_path_fallback": "FORBIDDEN",
        "stages": {
            "raw_to_typed_to_label": {"report": str(raw_report)},
            "private_runtime": {
                "audit": str(private_audit),
                "module_files": {"worker": str(target_worker)},
            },
        },
    }
    executor_path = tmp_path / "executor-report.json"
    executor_path.write_text(json.dumps(executor), encoding="utf-8")

    trace_prefix = tmp_path / "trace"
    _write_trace(
        tmp_path / "trace.101",
        f'101 openat(AT_FDCWD, "{source}", O_RDONLY) = 3',
    )
    _write_trace(
        tmp_path / "trace.202",
        f'202 openat(AT_FDCWD, "{target_worker}", O_RDONLY) = 3',
    )

    result = audit.audit(
        executor_report_path=executor_path,
        v34_request_path=v34_path,
        provenance_path=sidecar_path,
        trace_prefix=trace_prefix,
        source_pids=[101],
        private_pids=[202],
        target_root=target,
        output_root=output,
    )

    assert result["status"] == "PENDING_OR_FAILED_READONLY_AUDIT"
    assert result["trace"]["private_original_path_violations"] == {}
    assert result["private_runtime"]["audit_present"] is True
    assert "fresh V16 proof/result has not been supplied" in result["blockers"]
    assert "fresh evaluator-parent report has not been supplied" in result["blockers"]
    assert "dependency/license scope is not explicitly declared" in result["blockers"]
