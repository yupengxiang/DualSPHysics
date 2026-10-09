"""Tiny source/CLI tests for the V66 worker-owned output boundary."""
from __future__ import annotations

import importlib.util
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

import pytest


ROOT = Path(__file__).resolve().parents[1]
V66 = ROOT / "scripts" / "ds_data02_stage2_f2_portable_executor_v66.py"
BOOTSTRAP = ROOT / "scripts" / "ds_data02_stage2_f2_v64_terminal_adapter_bootstrap_v1.py"
V62_REQUEST = ROOT / "campaigns" / "ds-data-02" / "stage2" / "native-reconstruction" / "raw-to-label-v62-root145-runout-20261009" / "f2-s1-root145-v62c-runout-parent-request.json"
LEDGER = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/runtime/resource-ledger.json")
EXTERNAL = Path("/var/tmp/ds02-stage2/F2")


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
