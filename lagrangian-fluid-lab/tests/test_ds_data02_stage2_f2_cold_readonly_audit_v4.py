from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_cold_readonly_audit_v4.py"
SPEC = importlib.util.spec_from_file_location("f2_cold_readonly_audit_v4", SCRIPT)
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

    assert result["status"] == "PENDING_SOURCE_PROCESS_BINDING_LICENSE_SCOPE_PENDING"
    assert result["trace"]["private_original_path_violations"] == {}
    assert result["private_runtime"]["audit_present"] is True
    assert result["license_scope_status"] == "MISSING_EXPLICIT_LICENSE_SCOPE"
    assert result["qualification"] == audit.UNKNOWN
    assert "no portable" in result["credit_boundary"]


def _guard_record(path: Path, *, scratch: str | None = None) -> Path:
    value = {
        "schema": "ds02.stage2.f2-parent-process-record.v1",
        "root_pids": [100],
        "processes": [
            {"pid": 100, "role": "parent_guard"},
            {"pid": 101, "role": "source_copy", "parent_pid": 100},
            {"pid": 202, "role": "private_worker", "parent_pid": 100},
        ],
        "scratch_roots": [] if scratch is None else [
            {"path": scratch, "creator_pid": 202, "allowed_pids": [202]}
        ],
    }
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_ancestry_and_owned_scratch_close_with_guard_record(tmp_path: Path) -> None:
    prefix = tmp_path / "trace"
    scratch = "/tmp/ds02-direct-bi4-owned-abc"
    _write_trace(
        tmp_path / "trace.100",
        "100 clone(child_stack=NULL, flags=SIGCHLD) = 101",
        "100 clone(child_stack=NULL, flags=SIGCHLD) = 202",
    )
    _write_trace(
        tmp_path / "trace.101",
        '101 execve("/orig/copy", ["copy", "/orig/provenance.json"], 0) = 0',
        '101 openat(AT_FDCWD, "/orig/data/Part_0000.bi4", O_RDONLY) = 3',
    )
    _write_trace(
        tmp_path / "trace.202",
        '202 execve("/relocated/target/runtime/worker.py", ["worker", "/orig/provenance.json"], 0) = 0',
        f'202 mkdir("{scratch}", 0700) = 0',
        f'202 openat(AT_FDCWD, "{scratch}/frame.xml", O_RDONLY) = 3',
        '202 openat(AT_FDCWD, "/relocated/output/report.json", O_WRONLY) = 4',
    )
    guard = _guard_record(tmp_path / "guard.json", scratch=scratch)
    contract = audit._guard_contract(guard)

    result = audit.classify_trace(
        prefix, source_pids={101}, private_pids={202}, original_roots=["/orig"],
        target_root="/relocated/target", output_root="/relocated/output",
        registered_environment_roots=["/usr"], guard=contract,
    )

    assert result["ancestry"]["verified"] is True
    assert result["unknown_groups"] == []
    assert result["private_original_path_violations"] == {}
    assert result["private_unbound_absolute_path_hits"] == {}
    assert result["private_unresolved_relative_path_access"] == {}
    assert result["scratch"]["registered"][0]["creator_verified"] is True
    assert result["groups"]["202"]["owned_scratch_hits"] == [f"{scratch}/frame.xml"]


def test_dynamic_bi4_scratch_prefix_resolves_only_creator_mkdir(tmp_path: Path) -> None:
    prefix = tmp_path / "trace"
    scratch = "/tmp/ds02-direct-bi4-random-suffix"
    _write_trace(
        tmp_path / "trace.100",
        "100 clone(child_stack=NULL, flags=SIGCHLD) = 202",
    )
    _write_trace(
        tmp_path / "trace.202",
        '202 execve("/relocated/target/runtime/executor_v36.py", ["executor_v36"], 0) = 0',
        f'202 mkdir("{scratch}", 0700) = 0',
        f'202 openat(AT_FDCWD, "{scratch}/frame_0000.xml", O_RDONLY) = 3',
    )
    guard_path = tmp_path / "guard.json"
    guard_path.write_text(json.dumps({
        "root_pids": [100],
        "processes": [
            {"pid": 100, "role": "parent_guard"},
            {"pid": 202, "role": "executor_v36", "parent_pid": 100},
        ],
        "scratch_roots": [{
            "path_prefix": "/tmp/ds02-direct-bi4-",
            "creator_pid": 202,
            "allowed_pids": [202],
        }],
    }), encoding="utf-8")
    result = audit.classify_trace(
        prefix, source_pids=set(), private_pids={202}, original_roots=["/orig"],
        target_root="/relocated/target", output_root="/relocated/output",
        guard=audit._guard_contract(guard_path),
    )
    assert result["ancestry"]["verified"] is True
    assert result["groups"]["202"]["access_role"] == "private_worker_or_evaluator"
    assert result["scratch"]["registered"][0]["path"] == scratch
    assert result["scratch"]["registered"][0]["resolved_from_prefix"] is True
    assert result["scratch"]["registered"][0]["usable"] is True
    assert result["groups"]["202"]["owned_scratch_hits"] == [f"{scratch}/frame_0000.xml"]


def test_dynamic_bi4_prefix_does_not_whitelist_uncreated_tmp_path(tmp_path: Path) -> None:
    prefix = tmp_path / "trace"
    scratch = "/tmp/ds02-direct-bi4-never-created"
    _write_trace(
        tmp_path / "trace.100",
        "100 clone(child_stack=NULL, flags=SIGCHLD) = 202",
    )
    _write_trace(
        tmp_path / "trace.202",
        '202 execve("/relocated/target/runtime/executor_v36.py", ["executor_v36"], 0) = 0',
        f'202 openat(AT_FDCWD, "{scratch}/frame_0000.xml", O_RDONLY) = 3',
    )
    guard_path = tmp_path / "guard.json"
    guard_path.write_text(json.dumps({
        "root_pids": [100],
        "processes": [
            {"pid": 100, "role": "parent_guard"},
            {"pid": 202, "role": "executor_v36", "parent_pid": 100},
        ],
        "scratch_roots": [{
            "path_prefix": "/tmp/ds02-direct-bi4-",
            "creator_pid": 202,
            "allowed_pids": [202],
        }],
    }), encoding="utf-8")
    result = audit.classify_trace(
        prefix, source_pids=set(), private_pids={202}, original_roots=["/orig"],
        target_root="/relocated/target", output_root="/relocated/output",
        guard=audit._guard_contract(guard_path),
    )
    assert result["scratch"]["unverified_roots"]
    assert result["private_unbound_absolute_path_hits"] == {"202": [f"{scratch}/frame_0000.xml"]}


def test_ancestry_helper_keeps_unowned_tmp_and_relative_dirfd_unknown(tmp_path: Path) -> None:
    prefix = tmp_path / "trace"
    _write_trace(
        tmp_path / "trace.100",
        "100 clone(child_stack=NULL, flags=SIGCHLD) = 202",
    )
    _write_trace(
        tmp_path / "trace.202",
        '202 execve("/relocated/target/runtime/worker.py", ["worker"], 0) = 0',
        '202 openat(AT_FDCWD, "/tmp/unregistered/frame.bin", O_RDONLY) = 3',
        '202 openat(AT_FDCWD, 3, "relative-after-dirfd", O_RDONLY) = 4',
    )
    guard = _guard_record(tmp_path / "guard.json")
    result = audit.classify_trace(
        prefix, source_pids=set(), private_pids={202}, original_roots=["/orig"],
        target_root="/relocated/target", output_root="/relocated/output",
        registered_environment_roots=["/usr"], guard=audit._guard_contract(guard),
    )

    assert result["ancestry"]["verified"] is True
    assert result["private_unbound_absolute_path_hits"] == {
        "202": ["/tmp/unregistered/frame.bin"]
    }
    assert "202" in result["private_unresolved_relative_path_access"]


def test_missing_parent_guard_does_not_claim_ancestry(tmp_path: Path) -> None:
    prefix = tmp_path / "trace"
    _write_trace(tmp_path / "trace.202", '202 execve("/relocated/worker", ["worker"], 0) = 0')
    result = audit.classify_trace(
        prefix, source_pids=set(), private_pids={202}, original_roots=["/orig"],
        target_root="/relocated", output_root="/output", registered_environment_roots=["/usr"],
        guard=audit._guard_contract(None),
    )
    assert result["ancestry"]["verified"] is False
    assert "trace PID ancestry/process roles are not verified" not in result.get("blockers", [])
