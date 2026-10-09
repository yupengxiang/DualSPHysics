"""Tiny source/CLI tests for the V66 worker-owned output boundary."""
from __future__ import annotations

import importlib.util
import inspect
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

import pytest


ROOT = Path(__file__).resolve().parents[1]
V66 = ROOT / "scripts" / "ds_data02_stage2_f2_portable_executor_v66.py"
V64_NATIVE = ROOT / "scripts" / "ds_data02_stage2_f2_native_raw_to_typed_label_v64.py"
V2_NATIVE = ROOT / "scripts" / "ds_data02_stage2_f2_native_raw_to_typed_label_v2.py"
BOOTSTRAP = ROOT / "scripts" / "ds_data02_stage2_f2_v64_terminal_adapter_bootstrap_v1.py"
V62_REQUEST = ROOT / "campaigns" / "ds-data-02" / "stage2" / "native-reconstruction" / "raw-to-label-v62-root145-runout-20261009" / "f2-s1-root145-v62c-runout-parent-request.json"
# This is a small request envelope (the scientific payload is not read by this
# test); it supplies the exact V2 request shape which the native worker
# validates before it reaches its output-directory guard.
V64_CANDIDATE = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/f2-s1-root145-v64-root179b-primary-prepared-002.json")
LEDGER = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/runtime/resource-ledger.json")
EXTERNAL = Path("/var/tmp/ds02-stage2/F2")


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_native_guard_fixture(tmp_path: Path, output: Path) -> Path:
    """Rebase the real V64/V2 request onto tiny metadata-only inputs.

    The native worker's preflight requires every declared Part frame and the
    source-role/stat shape, but the output guard is reached before any decoder
    or HDF5 read.  Zero-byte frame files therefore exercise the real CLI
    boundary without reading/copying scientific data.
    """
    envelope = json.loads(V64_CANDIDATE.read_text(encoding="utf-8"))
    request = copy.deepcopy(envelope["embedded_worker_request"])
    code_root = tmp_path / "copied-runtime" / "native"
    code_root.mkdir(parents=True)

    # Keep the actual V2 worker.  The other operator bindings are valid tiny
    # Python modules because V2 only hashes them on its metadata path; V64
    # imports the V14 sibling through the copied code root.
    worker_path = code_root / V2_NATIVE.name
    shutil.copyfile(V2_NATIVE, worker_path)
    modules = {}
    for role, name in {
        "worker": worker_path.name,
        "raw_converter": "tiny_raw_converter.py",
        "v14_operator": "tiny_v14_operator.py",
        "v15_operator": "tiny_v15_operator.py",
        "v16_operator": "tiny_v16_operator.py",
    }.items():
        path = code_root / name
        if role != "worker":
            path.write_text(f"# metadata-only {role}\n", encoding="utf-8")
        modules[role] = {"module": name, "path": str(path), "sha256": _sha256(path)}
    request["modules"] = modules

    binding = dict(request["v64_worker_binding"])
    binding["code_root"] = str(code_root)
    binding["v2_worker_path"] = str(worker_path)
    binding["module_sha256"] = {role: item["sha256"] for role, item in modules.items()}
    binding["bootstrap_target"] = str(code_root / "v64-bootstrap.py")
    request["v64_worker_binding"] = binding

    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    frames = []
    for index in range(401):
        path = raw_root / f"Part_{index:04d}.bi4"
        path.touch()
        frames.append({
            "frame": index,
            "path": str(path),
            "bytes": 0,
            "sha256": "PENDING_PARENT_GUARD_CONTENT_SHA256",
            "mtime_ns": path.stat().st_mtime_ns,
            "content_sha256_source": "TINY_METADATA_FIXTURE",
        })
    raw = dict(request["raw_binding"])
    raw["data_root"] = str(raw_root)
    raw["frames"] = frames
    raw["frame_count"] = len(frames)
    raw["expected_file_count"] = len(frames)
    raw["expected_raw_tree_sha256"] = "0" * 64
    request["raw_binding"] = raw
    request["v64_raw_scope"] = {
        "root": str(raw_root),
        "paths": [f"Part_{index:04d}.bi4" for index in range(401)],
        "expected_tree_sha256": "0" * 64,
    }

    source_root = tmp_path / "sources"
    source_root.mkdir()
    source_files = []
    for index, item in enumerate(request["source_files"]):
        role = str(item["role"])
        path = source_root / f"{index:02d}-{role}.source"
        path.write_text(f"tiny metadata source: {role}\n", encoding="utf-8")
        replacement = dict(item)
        replacement["path"] = str(path)
        replacement["sha256"] = _sha256(path)
        replacement["bytes"] = path.stat().st_size
        replacement["mtime_ns"] = path.stat().st_mtime_ns
        source_files.append(replacement)
    request["source_files"] = source_files

    external = tmp_path / "external"
    external.mkdir(parents=True, exist_ok=True)
    scratch = dict(request["runtime"]["scratch"])
    scratch["external_root"] = str(external)
    scratch["root"] = str(external / "scratch")
    scratch["attempt_id"] = "tiny-v66-native-guard"
    request["runtime"] = dict(request["runtime"], canonical_sibling_root=str(code_root), scratch=scratch)
    request["source_hashes_preverified_by_parent"] = True
    request["status"] = "READY_FOR_PARENT_GUARD"
    request["request_id"] = "tiny-v66-native-output-guard"
    request["output_dir_contract"] = {
        "output": str(output),
        "creation": "WORKER_ATOMIC_MKDIR_V66",
        "parent_must_not_create": True,
    }
    path = tmp_path / "native-v64-request.json"
    path.write_text(json.dumps(request, sort_keys=True), encoding="utf-8")
    return path


def test_worker_owned_output_is_absent_before_cli_and_existing_target_is_rejected(tmp_path):
    worker = _load(V66, "v66_output_protocol_test")
    output = tmp_path / "attempt" / "products"
    worker._assert_worker_output_fresh(output)
    assert not output.exists()
    assert output.parent.is_dir()

    child = tmp_path / "strict-child.py"
    child.write_text(
        "import json, pathlib, sys\n"
        "target = pathlib.Path(sys.argv[1])\n"
        "if target.exists(): raise SystemExit('parent pre-created output')\n"
        "target.mkdir(parents=False, exist_ok=False)\n"
        "(target / 'tiny-summary.json').write_text(json.dumps({'status':'COMPLETE_TINY'}))\n"
        "print(json.dumps({'status':'COMPLETE_TINY'}))\n",
        encoding="utf-8",
    )
    env = {key: value for key, value in os.environ.items()
           if key not in {"PYTHONPATH", "PYTHONHOME"}}
    result = worker._run_bounded(
        [sys.executable, str(child), str(output)], cwd=tmp_path, env=env,
        timeout=5.0, cleanup_grace=1.0, parent_pid=os.getpid())
    assert result["returncode"] == 0
    assert (output / "tiny-summary.json").is_file()
    with pytest.raises(worker.PortableV64Error, match="must be absent"):
        worker._assert_worker_output_fresh(output)


def test_isolated_adapter_bootstrap_imports_only_explicit_sibling_root(tmp_path):
    scripts = tmp_path / "copied-runtime"
    scripts.mkdir()
    (scripts / "sibling_runtime.py").write_text("VALUE = 'BOUND_SIBLING'\n", encoding="utf-8")
    adapter = scripts / "adapter.py"
    adapter.write_text(
        "import json, sibling_runtime, sys\n"
        "print(json.dumps({'value': sibling_runtime.VALUE, 'argv': sys.argv[1:]}))\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, "-B", "-I", str(BOOTSTRAP),
         "--scripts-root", str(scripts), "--adapter", str(adapter), "--",
         "inspect", "tiny"],
        cwd=str(tmp_path), capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value == {"value": "BOUND_SIBLING", "argv": ["inspect", "tiny"]}


def test_v66_protocol_is_explicit_and_v65_report_schema_remains_compatible():
    worker = _load(V66, "v66_protocol_schema_test")
    assert worker.OUTPUT_CREATION_PROTOCOL == "WORKER_ATOMIC_MKDIR_V66"
    assert worker.SCHEMA == "ds02.stage2.f2-root145-copied-recovery-parent-request.v64"
    assert worker.REPORT_SCHEMA == "ds02.stage2.f2-root145-copied-recovery-report.v64"
    assert "portable_executor_v66" in inspect.getsource(worker._make_static_bindings)


@pytest.mark.skipif(not V64_CANDIDATE.is_file(), reason="ROOT179B V64 candidate envelope is not mounted")
def test_actual_v64_native_cli_enforces_worker_owned_output_boundary(tmp_path):
    """Exercise the real V64 -> V2 CLI, rather than the strict-child stub.

    The first invocation uses an existing target and must stop at the pinned
    V2 ``target.exists`` guard without modifying its sentinel.  The second
    invocation uses an absent target; the real V2 worker creates it, writes
    its metadata-only preflight, and then V64 stops at the expected missing
    converter scratch stage.  That second state proves the worker, rather than
    the parent, owned output creation.  Neither branch has an approved I/O
    slot and all raw frame files are zero-byte test fixtures.
    """
    existing_root = tmp_path / "existing"
    output = existing_root / "external" / "products-existing"
    output.mkdir(parents=True)
    sentinel = output / "sentinel.txt"
    sentinel.write_text("preserve", encoding="utf-8")
    existing_request = _make_native_guard_fixture(existing_root, output)

    python = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
    if not python.is_file():
        python = Path(sys.executable)

    def run_native(request: Path, target: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(python), "-B", "-I", str(V64_NATIVE), "run",
             "--request", str(request), "--output-dir", str(target),
             "--no-run-labels"],
            cwd=str(tmp_path), capture_output=True, text=True, check=False,
            timeout=30,
        )

    rejected = run_native(existing_request, output)
    assert rejected.returncode == 2
    assert "refusing to use existing output directory" in rejected.stdout
    assert sentinel.read_text(encoding="utf-8") == "preserve"

    absent_root = tmp_path / "absent"
    absent = absent_root / "external" / "products-worker-created"
    absent_request = _make_native_guard_fixture(absent_root, absent)
    completed = run_native(absent_request, absent)
    assert completed.returncode == 2
    assert absent.is_dir(), "real V2 worker must create the absent output target"
    assert (absent / "metadata-preflight-v2.json").is_file()
    assert "refusing to use existing output directory" not in completed.stdout
    assert "scratch contract was not observed" in completed.stdout


@pytest.mark.skipif(not V62_REQUEST.is_file() or not LEDGER.is_file() or not EXTERNAL.is_dir(),
                    reason="ROOT145 V62 source-only fixture is not mounted")
def test_real_v66_builder_and_metadata_preflight_create_no_output_directory(tmp_path):
    worker = _load(V66, "v66_real_metadata_preflight_test")
    token = uuid.uuid4().hex
    namespace = EXTERNAL / f"STAGE2_F2_V66_METADATA_TEST_{token}"
    request_path = tmp_path / "root179c-v66-request.json"
    result = worker.build_request(
        v62_request=V62_REQUEST,
        output_request=request_path,
        target_root=namespace / "bundle-target",
        output_root=namespace / "products",
        supervisor_root=namespace / "supervisor",
        ledger=LEDGER,
        external_filesystem=EXTERNAL,
        home_receipt=tmp_path / "home-receipt.json",
        case_id="STAGE2_F2_ROOT145_V66_RECOVERY_ROOT_179C_METADATA_TEST",
        attempt_id="f2-s1-v66-root179c-metadata-test-003",
    )
    assert result["payload_read"] is False
    assert result["raw_copy_bytes"] == 0
    bound = worker._validate_request(request_path, verify_static=False)
    assert bound["request"]["runtime"]["output_creation_protocol"] == "WORKER_ATOMIC_MKDIR_V66"
    assert bound["request"]["storage_scope"]["output_creator"] == "copied_worker_atomic_mkdir"
    assert not (namespace / "products").exists()
    assert not (namespace / "bundle-target").exists()
