from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_typed_labels_only_v1.py"
SPEC = importlib.util.spec_from_file_location("typed_labels_only_v1_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
worker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(worker)


def _request(path: Path, *, expected: str) -> Path:
    value = {
        "schema": worker.SCHEMA,
        "role": "DEVELOPMENT",
        "status": "READY_FOR_PARENT_TYPED_LABEL_GUARD",
        "model_invoked": False,
        "cfd_invoked": False,
        "raw_opened": False,
        "qualification": dict(worker.UNKNOWN),
        "execution": {"raw_opened": False},
        "typed_input": {
            "path": str(path), "bytes_at_build": path.stat().st_size,
            "mtime_ns_at_build": path.stat().st_mtime_ns,
            "expected_sha256": expected,
        },
    }
    value["sha256"] = worker.canonical_sha(value)
    request = path.parent / "request.json"
    request.write_text(json.dumps(value) + "\n")
    return request


def test_preflight_is_stat_only(tmp_path: Path) -> None:
    typed = tmp_path / "typed.h5"
    typed.write_bytes(b"small fixture")
    request = _request(typed, expected="0" * 64)
    result = worker.preflight(request, tmp_path / "preflight.json")
    assert result["typed_input"]["content_hash_read"] is False
    assert result["hdf5_or_bi4_read"] is False


def test_run_rejects_wrong_typed_content_after_guard_boundary(tmp_path: Path) -> None:
    typed = tmp_path / "typed.h5"
    typed.write_bytes(b"wrong content")
    request = _request(typed, expected="0" * 64)
    try:
        worker.run(request, output_dir=tmp_path / "out",
                   io_slot_approved=True)
    except worker.TypedLabelsOnlyError as error:
        assert "content SHA differs" in str(error)
    else:
        raise AssertionError("wrong typed content was accepted")
