from __future__ import annotations

import hashlib
import json
from pathlib import Path
import os
import stat
import subprocess


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_portable_executor_v58.py"
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: str | dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, str):
        path.write_text(value)
    else:
        path.write_text(json.dumps(value, sort_keys=True))


def test_v58_run_uses_old_raw_root_without_copying_payload(tmp_path):
    old = tmp_path / "old-bundle"
    old.mkdir()
    raw = old / "Part_0000.bi4"
    raw.write_bytes(b"manufactured-raw-payload")
    old_before = (raw.stat().st_size, raw.stat().st_mtime_ns, _sha(raw))

    frozen_v57 = tmp_path / "frozen-v57.json"
    _write(frozen_v57, {"schema": "ds02.stage2.f2-portable-executor-request.v34",
                        "forward_v57": {"schema": "ds02.stage2.f2-portable-executor-v57-forward.v1"}})

    worker = tmp_path / "stub-worker.py"
    _write(worker, r'''
import argparse, json, pathlib
p = argparse.ArgumentParser()
p.add_argument("run")
p.add_argument("--request", required=True)
p.add_argument("--output-dir", required=True)
p.add_argument("--io-slot-approved", action="store_true")
p.add_argument("--run-labels", action="store_true")
a = p.parse_args()
r = json.loads(pathlib.Path(a.request).read_text())
assert r["raw_binding"]["new_payload_copy_forbidden"] is True
assert pathlib.Path(r["raw_binding"]["data_root"]).name == "old-bundle"
out = pathlib.Path(a.output_dir)
out.mkdir(parents=True, exist_ok=True)
(out / "labels.json").write_text(json.dumps({"status": "MANUFACTURED_LABEL_OUTPUT",
                                               "raw_root": r["raw_binding"]["data_root"],
                                               "output_root": str(out)}))
print(json.dumps({"status": "PASS_MANUFACTURED_DIRECT_RECOVERY"}))
''')

    target = tmp_path / "new" / "bundle-target"
    products = tmp_path / "new" / "products"
    request = tmp_path / "request.json"
    request_value = {
        "schema": "ds02.stage2.f2-root145-copied-recovery-v58.v1",
        "status": "READY_FOR_PARENT_STAGE2_GUARD",
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "fresh_cold_credit": False,
        "v57_provenance": {"path": str(frozen_v57)},
        "fresh_roots": {"target_root": str(target), "output_root": str(products)},
        "reused_immutable_copy": {"bundle_root": str(old)},
        "embedded_worker_request": {
            "schema": "ds02.stage2.f2-native-raw-to-typed-to-label-request.v2",
            "raw_binding": {
                "data_root": str(old), "expected_file_count": 1,
                "frame_count": 1, "expected_raw_tree_sha256": "a" * 64,
                "frames": [{"frame": 0, "path": str(raw), "bytes": raw.stat().st_size,
                            "sha256": "PENDING_PARENT_GUARD_CONTENT_SHA256"}],
                "new_payload_copy_forbidden": True,
            },
            "recovery_binding": {"new_output_root": "<V58_OUTPUT_ROOT>"},
        },
        "runtime": {"worker_target": str(target / "runtime/native/ds_data02_stage2_f2_native_raw_to_typed_label_v2.py")},
        "execution": {"max_wall_seconds": 20, "env": {}},
    }
    _write(request, request_value)
    command = [str(PYTHON), str(SCRIPT), "run", "--request", str(request),
               "--worker-override", str(worker), "--io-slot-approved"]
    completed = subprocess.run(command, capture_output=True, text=True,
                               check=False, timeout=30)
    assert completed.returncode == 0, completed.stderr + completed.stdout
    report = json.loads(completed.stdout)
    assert report["status"].startswith("PASS_RECOVERY")
    assert report["raw_copy_attempts"] == 0
    assert report["source_copy_bytes"] == 0
    assert report["reused_source_root"] == str(old)
    assert report["new_output_root"] == str(products)
    assert (products / "labels.json").is_file()
    assert (raw.stat().st_size, raw.stat().st_mtime_ns, _sha(raw)) == old_before
    assert not (target / "Part_0000.bi4").exists()
    assert report["old_namespace_before"] == report["old_namespace_after"]


def test_v58_payload_copy_guard_rejects_bi4(tmp_path):
    # The guard is intentionally unit-scoped and does not read the payload.
    import importlib.util
    spec = importlib.util.spec_from_file_location("v58", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = tmp_path / "Part_0000.bi4"
    source.write_bytes(b"x")
    try:
        module._copy_code(source, tmp_path / "copy" / source.name)
    except module.PortableV58Error as error:
        assert "payload copy" in str(error)
    else:
        raise AssertionError("V58 copied a BI4 payload")
