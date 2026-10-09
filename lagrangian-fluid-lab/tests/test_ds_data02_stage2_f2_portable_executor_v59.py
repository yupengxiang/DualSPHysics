from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import os
import subprocess
from datetime import datetime, timedelta, timezone


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_portable_executor_v59.py"
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
RUNTIME = ROOT / "scripts/ds_data02_runtime_v6.py"
PARENT = ROOT / "scripts/ds_data02_stage2_f2_portable_executor_parent_v3.py"
V21 = ROOT / "scripts/ds_data02_stage2_f2_external_supervisor_v21.py"


def _load():
    spec = importlib.util.spec_from_file_location("v59_test_module", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")


def _ledger(tmp_path: Path, home: Path) -> Path:
    data_root = tmp_path / "data"
    runtime = data_root / "runtime"
    runtime.mkdir(parents=True)
    value = {
        "schema": "ds02.resource-ledger.v1",
        "deadline_utc": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        "limits": {"storage_policy": "home_free_floor", "home_path": str(home),
                   "home_min_free_bytes": 0, "cpu_core_seconds": 1000.0,
                   "gpu_seconds": 0.0, "new_storage_bytes": 10**9,
                   "qualification_attempts": 100, "production_attempts": 100},
        "charges": [], "reservations": [], "attempts": [],
    }
    path = runtime / "resource-ledger.json"
    _write_json(path, value)
    return path


def _worker(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env python3
import argparse, hashlib, json
from pathlib import Path

def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        while True:
            b=f.read(65536)
            if not b: break
            h.update(b)
    return h.hexdigest()

def manifest(root):
    rows=[]
    for p in sorted(x for x in root.rglob('*') if x.is_file()):
        rows.append({'path':p.relative_to(root).as_posix(),'bytes':p.stat().st_size,'sha256':sha(p)})
    return hashlib.sha256(json.dumps(rows,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()

p=argparse.ArgumentParser(); p.add_argument('run'); p.add_argument('--request',required=True)
p.add_argument('--output-dir',required=True); p.add_argument('--io-slot-approved',action='store_true')
p.add_argument('--run-labels',action='store_true'); a=p.parse_args()
r=json.loads(Path(a.request).read_text()); root=Path(r['raw_binding']['data_root']); out=Path(a.output_dir)
before=manifest(root); out.mkdir(parents=True,exist_ok=True)
(out/'labels.json').write_text(json.dumps({'status':'MANUFACTURED_LABELS'}))
after=manifest(root)
result={'status':'PASS_MANUFACTURED_STRICT_WORKER','raw_tree_before_sha256':before,
        'raw_tree_after_sha256':after,'raw_copy_attempts':0,'hdf5_opened':False}
(out/'worker-report.json').write_text(json.dumps(result,sort_keys=True))
print(json.dumps(result,sort_keys=True))
"""
    )
    path.chmod(0o755)


def _request(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    module = _load()
    ext = tmp_path / "external"
    home = tmp_path / "home"
    raw = tmp_path / "raw"
    ext.mkdir(); home.mkdir(); raw.mkdir()
    (raw / "Part_0000.bi4").write_bytes(b"frame-0")
    (raw / "Part_0001.bi4").write_bytes(b"frame-1")
    (raw / "PartInfo.ibi4").write_bytes(b"aux")
    manifest = module._raw_tree_manifest(raw)
    worker = tmp_path / "worker.py"
    _worker(worker)
    target = ext / "attempt" / "bundle-target"
    output = ext / "attempt" / "products"
    supervisor = ext / "attempt" / "supervisor"
    receipt = home / "v59-receipt.json"
    ledger = _ledger(tmp_path, home)
    frames = [{"frame": i, "path": str(raw / f"Part_{i:04d}.bi4"),
               "bytes": (raw / f"Part_{i:04d}.bi4").stat().st_size,
               "sha256": None} for i in range(2)]
    worker_request = {"schema": "ds02.stage2.f2-native-raw-to-typed-to-label-request.v2",
                      "raw_binding": {"data_root": str(raw), "frames": frames}}
    worker_target = target / "runtime" / "native" / "worker.py"
    static = []
    for role, path in (("portable_executor_v59", SCRIPT), ("parent_executor_v3", PARENT),
                       ("shared_v21_accounting", V21), ("shared_runtime_v6", RUNTIME),
                       ("worker", worker)):
        st = path.stat()
        static.append({"role": role, "path": str(path), "bytes": st.st_size,
                       "mtime_ns": st.st_mtime_ns, "mode_bits": st.st_mode & 0o777,
                       "sha256": _sha(path)})
    request = {
        "schema": module.SCHEMA, "status": "READY_FOR_PARENT_GUARD", "role": "DEVELOPMENT",
        "family_id": "F2", "case_id": "manufactured-v59", "request_id": "manufactured-v59",
        "attempt_id": "manufactured-v59", "worktree_root": str(ROOT.parent),
        "parent_adapter": {"schema": "ds02.stage2.f2-portable-executor-parent-request.v3",
                            "implementation": str(PARENT), "apis": ["_reserve", "_charge", "_release", "ledger_locked"],
                            "same_parent_ledger": True},
        "raw_source": {"root": str(raw), "tree_sha256": manifest["tree_sha256"],
                       "file_count": manifest["file_count"], "frame_count": 2,
                       "copy_forbidden": True, "prepost_required": True,
                       "verification_phase": "AFTER_ATOMIC_PARENT_RESERVATION_BEFORE_WORKER",
                       "frames": frames},
        "runtime": {"pinned_python": str(PYTHON), "worker_target": str(worker_target),
                    "worker_request_target": str(target / "runtime/native/worker-request.json"),
                    "raw_copy_forbidden": True,
                    "code_overlay_bindings": [{"role": "worker", "source_path": str(worker),
                        "target_path": str(worker_target), "sha256": _sha(worker),
                        "bytes": worker.stat().st_size, "required_executable": False}],
                    "scratch": {"attempt_owned": True, "default_tmp_forbidden": True}},
        "embedded_worker_request": worker_request,
        "execution": {"python": str(PYTHON), "command": [str(PYTHON), "-B", "-I", str(worker_target)],
                       "max_wall_seconds": 20.0, "cpu_reservation_seconds": 20.0,
                       "child_cleanup_grace_seconds": 20.0,
                       "bounded_log_bytes_per_stream": 1024 * 1024, "log_tail_bytes": 65536,
                       "env": {"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1",
                               "MKL_NUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1"},
                       "original_path_fallback": "FORBIDDEN"},
        "parent_resource_binding": {"ledger_path": str(ledger), "attempt_id": "manufactured-v59",
            "reservation_id": "manufactured-v59::reservation", "charge_id": "manufactured-v59::charge",
            "same_parent_ledger": True, "ledger_reset": False, "allow_missing_parent": True,
            "storage_policy": "home_free_floor", "deadline_utc": json.loads(ledger.read_text())["deadline_utc"],
            "home_path": str(home), "home_min_free_bytes": 0, "external_filesystem": str(ext)},
        "runtime_binding": {"path": str(RUNTIME), "sha256": _sha(RUNTIME), "role": "shared_runtime_v6", "immutable": True},
        "storage_scope": {"external_filesystem": str(ext), "external_output_root": str(output),
            "supervisor_output_root": str(supervisor), "home_receipt_path": str(receipt),
            "home_receipt_bytes": 4096, "external_reservation_bytes": 1024 * 1024,
            "source_copy_bytes": 0, "external_min_free_bytes": 0, "home_min_free_bytes": 0,
            "two_filesystem_charge_required": True, "new_namespace_absent_before_run": True},
        "static_bindings": static, "model_invoked": False, "cfd_invoked": False,
        "raw_opened": False, "hdf5_opened": False, "fresh_cold_credit": False,
        "qualification": dict(module.UNKNOWN),
    }
    request["sha256"] = module._canonical(request)
    path = tmp_path / "v59-request.json"
    _write_json(path, request)
    return path, ledger, raw, output


def test_v59_real_parent_reserve_worker_charge_and_release(tmp_path):
    request, ledger, raw, output = _request(tmp_path)
    completed = subprocess.run(
        [str(PYTHON), str(SCRIPT), "run", "--request", str(request), "--io-slot-approved",
         "--parent-pid", str(os.getpid())], capture_output=True, text=True, check=False, timeout=30)
    assert completed.returncode == 0, completed.stderr + completed.stdout
    result = json.loads(completed.stdout)
    assert result["status"].startswith("COMPLETED_PARENT_EXECUTOR")
    assert result["ledger_mutated"] is True
    assert result["raw_copy_attempts"] == 0
    assert result["fresh_cold_credit"] is False
    assert (output / "labels.json").is_file()
    value = json.loads(ledger.read_text())
    assert value["reservations"] == []
    charges = [row for row in value["charges"] if row.get("id") == "manufactured-v59::charge"]
    assert len(charges) == 1
    assert charges[0]["external_storage_bytes"] >= (output / "labels.json").stat().st_size
    assert (raw / "Part_0000.bi4").read_bytes() == b"frame-0"


def test_v59_builder_is_metadata_only_and_rejects_existing_target(tmp_path):
    module = _load()
    request, ledger, raw, output = _request(tmp_path)
    existing = tmp_path / "existing.json"
    try:
        module._validate_request(request, verify_static=False)
    except Exception as error:  # pragma: no cover - this request is valid
        raise AssertionError(error)
    output.mkdir(parents=True)
    try:
        module._validate_request(request, verify_static=False)
    except module.PortableV59Error as error:
        assert "fresh" in str(error)
    else:
        raise AssertionError("V59 accepted an existing output namespace")
    assert not existing.exists()


def test_v59_timeout_terminates_owned_group_and_charges_failure(tmp_path):
    request, ledger, raw, output = _request(tmp_path)
    value = json.loads(request.read_text())
    worker = Path(value["runtime"]["code_overlay_bindings"][0]["source_path"])
    worker.write_text("""import argparse, json, time\nfrom pathlib import Path\np=argparse.ArgumentParser(); p.add_argument('run'); p.add_argument('--request'); p.add_argument('--output-dir'); p.add_argument('--io-slot-approved', action='store_true'); p.add_argument('--run-labels', action='store_true'); p.parse_args(); time.sleep(3)\n""")
    digest = _sha(worker)
    value["runtime"]["code_overlay_bindings"][0]["sha256"] = digest
    value["runtime"]["code_overlay_bindings"][0]["bytes"] = worker.stat().st_size
    for item in value["static_bindings"]:
        if item["role"] == "worker":
            item["sha256"] = digest
            item["bytes"] = worker.stat().st_size
            item["mtime_ns"] = worker.stat().st_mtime_ns
    value["execution"]["max_wall_seconds"] = 0.5
    value["execution"]["cpu_reservation_seconds"] = 0.5
    value["sha256"] = _load()._canonical(value)
    _write_json(request, value)
    completed = subprocess.run(
        [str(PYTHON), str(SCRIPT), "run", "--request", str(request), "--io-slot-approved",
         "--parent-pid", str(os.getpid())], capture_output=True, text=True, check=False, timeout=30)
    assert completed.returncode == 1, completed.stderr + completed.stdout
    result = json.loads(completed.stdout)
    assert result["status"] == "FAILED_PARENT_EXECUTOR"
    state = json.loads(ledger.read_text())
    assert state["reservations"] == []
    charge = [row for row in state["charges"] if row["id"] == "manufactured-v59::charge"]
    assert len(charge) == 1 and charge[0]["status"] == "failed"
