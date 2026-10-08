from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_coarse_active_stream_v4.py"
DIRECT_CONVERTER = ROOT / "scripts/ds_data02_direct_convert.py"
REQUEST_DIR = ROOT / "campaigns/ds-data-02/stage2/requests/f2-coarse-active-stream-v4-root-forward-111-001"
MANIFEST = REQUEST_DIR / "f2-coarse-active-stream-v4-manifest.json"
REQUEST = REQUEST_DIR / "f2-coarse-active-stream-v4-request.json"


def module():
    spec = importlib.util.spec_from_file_location("f2_coarse_active_stream_v4_test", SCRIPT)
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_v4_request_binds_forward_worker_and_v4_manifest():
    request = json.loads(REQUEST.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    worker = SCRIPT.resolve()
    manifest_path = MANIFEST.resolve()
    assert request["request_schema"] == "ds02.stage2.f2.coarse-active-stream.v4-request.v1"
    assert request["attempt_id"] == "f2-coarse-active-stream-v4-root-forward-111-001"
    assert request["command"][1] == str(worker)
    assert request["command"][3] == str(manifest_path)
    assert manifest["schema"] == "ds02.stage2.f2.coarse-active-stream.manifest.v4"
    assert manifest["status"] == "READY_FOR_PARENT_GUARDED_EXECUTION_V4"
    assert request["input_sha256"][str(worker)] == digest(worker)
    assert request["input_sha256"][str(manifest_path)] == digest(manifest_path)
    assert request["hdf5_read"] is False
    assert request["solver_launch"] is False


def test_v4_loads_real_direct_converter_with_module_registration():
    loaded = module()
    backend = loaded.load_backend(DIRECT_CONVERTER)
    assert backend.__name__ == "ds02_direct_convert_for_f2_stream_v4"
    assert sys.modules[backend.__name__] is backend
    assert callable(backend.parse_particle_blocks)
    assert callable(backend._reject_dynamic_contract)
    assert hasattr(backend, "DecodedFrame")

