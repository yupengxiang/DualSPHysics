from __future__ import annotations

import importlib.util
import os
import signal
import sys
import time
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_coarse_active_stream_v9.py"
CONTRACT = ROOT / "campaigns/ds-data-02/stage2/contracts/f2-coarse-active-stream-v9-full-stream-contract.json"


def module():
    spec = importlib.util.spec_from_file_location("f2_coarse_active_stream_v9_test", SCRIPT)
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def test_v9_cleanup_kills_decoder_process_group_on_scratch_overrun(tmp_path):
    loaded = module()
    decoder = tmp_path / "fake-decoder.py"
    decoder.write_text(
        "#!/usr/bin/env python3\n"
        "import pathlib, sys, time\n"
        "prefix = pathlib.Path(sys.argv[2])\n"
        "prefix.parent.mkdir(parents=True, exist_ok=True)\n"
        "(prefix.parent / 'oversize.bin').write_bytes(b'x' * 4096)\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )
    decoder.chmod(decoder.stat().st_mode | 0o111)
    frame = tmp_path / "Part_0000.bi4"
    frame.write_bytes(b"synthetic")
    parent = tmp_path / "attempt"
    parent.mkdir()
    with loaded.tempfile.TemporaryDirectory(prefix="frame-", dir=str(parent)) as scratch:
        with pytest.raises(loaded.StreamObservationError, match="exceeded limit"):
            loaded.decode_frame_bounded(object(), frame, decoder, Path(scratch), 0, 1024, poll_interval_s=0.001)
    assert loaded.directory_bytes(parent) == 0


def test_v9_cleanup_kills_decoder_on_unexpected_poller_exception(tmp_path, monkeypatch):
    loaded = module()
    decoder = tmp_path / "fake-decoder.py"
    pid_file = tmp_path / "child.pid"
    decoder.write_text(
        "#!/usr/bin/env python3\n"
        "import pathlib, os, sys, time\n"
        "prefix = pathlib.Path(sys.argv[2])\n"
        f"pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid()))\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )
    decoder.chmod(decoder.stat().st_mode | 0o111)
    frame = tmp_path / "Part_0000.bi4"
    frame.write_bytes(b"synthetic")
    parent = tmp_path / "attempt"
    parent.mkdir()
    calls = {"count": 0}
    original = loaded.directory_bytes

    def fail_once(path):
        calls["count"] += 1
        if calls["count"] == 1:
            raise OSError("synthetic poll failure")
        return original(path)

    monkeypatch.setattr(loaded, "directory_bytes", fail_once)
    with loaded.tempfile.TemporaryDirectory(prefix="frame-", dir=str(parent)) as scratch:
        with pytest.raises(OSError, match="synthetic poll failure"):
            loaded.decode_frame_bounded(object(), frame, decoder, Path(scratch), 0, 1024, poll_interval_s=0.001)
    assert loaded.directory_bytes(parent) == 0
    if pid_file.exists():
        pid = int(pid_file.read_text())
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)


def test_v9_result_json_has_bounded_atomic_output(tmp_path):
    loaded = module()
    loaded.MAX_RESULT_JSON_BYTES = 32
    with pytest.raises(loaded.StreamObservationError, match="bounded JSON output size"):
        loaded.atomic_json(tmp_path / "result.json", {"payload": "x" * 100})
    assert not (tmp_path / "result.json").exists()


def test_v9_contract_records_cleanup_and_output_bound():
    import json
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert contract["result_output"]["max_json_bytes"] == 134217728
    assert contract["result_output"]["oversize_is_failure"] is True
    assert contract["frame_processing"]["per_frame_scratch"]["cleanup_on_exception"] is True
    assert contract["old_products_immutable"] is True


def test_v9_registers_dataclass_backend_before_import(tmp_path):
    loaded = module()
    backend_path = tmp_path / "dataclass_backend.py"
    backend_path.write_text("from dataclasses import dataclass\n@dataclass\nclass DecodedFrame:\n    value: int\n", encoding="utf-8")
    backend = loaded.load_backend(backend_path)
    assert backend.__name__ == "ds02_direct_convert_for_f2_stream_v9"
    assert sys.modules[backend.__name__] is backend
