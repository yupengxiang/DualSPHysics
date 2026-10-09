from __future__ import annotations

import importlib.util
import os
import signal
import sys
import time
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_coarse_active_stream_v10.py"
CONTRACT = ROOT / "campaigns/ds-data-02/stage2/contracts/f2-coarse-active-stream-v10-full-stream-contract.json"


def module():
    spec = importlib.util.spec_from_file_location("f2_coarse_active_stream_v10_test", SCRIPT)
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def _signal_fixture(tmp_path):
    """Start a real worker/decoder pair for OS-signal cancellation tests."""
    decoder = tmp_path / "fake-decoder.py"
    pid_file = tmp_path / "child.pid"
    decoder.write_text(
        "#!/usr/bin/env python3\n"
        "import pathlib, os, sys, time\n"
        "prefix = pathlib.Path(sys.argv[2])\n"
        f"pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid()), encoding='utf-8')\n"
        "prefix.parent.mkdir(parents=True, exist_ok=True)\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    decoder.chmod(decoder.stat().st_mode | 0o111)
    frame = tmp_path / "Part_0000.bi4"
    frame.write_bytes(b"synthetic")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    helper = tmp_path / "worker.py"
    helper.write_text(
        "import importlib.util, pathlib\n"
        f"script = pathlib.Path({str(SCRIPT)!r})\n"
        "spec = importlib.util.spec_from_file_location('v10_signal_worker', script)\n"
        "loaded = importlib.util.module_from_spec(spec)\n"
        "assert spec and spec.loader\n"
        "spec.loader.exec_module(loaded)\n"
        f"loaded.decode_frame_bounded(object(), pathlib.Path({str(frame)!r}), pathlib.Path({str(decoder)!r}), pathlib.Path({str(scratch)!r}), 0, 1024 * 1024, poll_interval_s=0.01, max_decoder_seconds=60)\n",
        encoding="utf-8",
    )
    worker = __import__("subprocess").Popen(
        [sys.executable, str(helper)],
        stdout=__import__("subprocess").PIPE,
        stderr=__import__("subprocess").PIPE,
        text=True,
    )
    deadline = time.monotonic() + 5
    while not pid_file.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert pid_file.exists(), worker.stderr.read() if worker.poll() is not None else "decoder did not start"
    return worker, int(pid_file.read_text(encoding="utf-8"))


def _wait_pid_dead(pid: int, timeout: float = 5.0):
    """Treat a reparented zombie as exited; it cannot execute or write."""
    deadline = time.monotonic() + timeout
    proc_stat = Path(f"/proc/{pid}/stat")
    while time.monotonic() < deadline:
        try:
            fields = proc_stat.read_text(encoding="utf-8").split()
        except FileNotFoundError:
            return
        if len(fields) >= 3 and fields[2] == "Z":
            return
        time.sleep(0.02)
    raise AssertionError(f"decoder pid {pid} remained live after worker cancellation")


def test_v10_cleanup_kills_decoder_process_group_on_scratch_overrun(tmp_path):
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


def test_v10_cleanup_kills_decoder_on_unexpected_poller_exception(tmp_path, monkeypatch):
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


def test_v10_real_sigterm_handler_reaps_decoder_process_group(tmp_path):
    """SIGTERM must enter the worker exception path, not skip Python finally."""
    worker, decoder_pid = _signal_fixture(tmp_path)
    try:
        worker.send_signal(signal.SIGTERM)
        assert worker.wait(timeout=10) != 0
        _wait_pid_dead(decoder_pid)
    finally:
        if worker.poll() is None:
            worker.kill()
            worker.wait(timeout=10)
        _wait_pid_dead(decoder_pid)


def test_v10_worker_sigkill_closes_decoder_via_parent_death_signal(tmp_path):
    """A SIGKILL, which cannot run finally, must still kill the decoder."""
    worker, decoder_pid = _signal_fixture(tmp_path)
    try:
        worker.kill()
        assert worker.wait(timeout=10) < 0
        _wait_pid_dead(decoder_pid)
    finally:
        if worker.poll() is None:
            worker.kill()
            worker.wait(timeout=10)
        _wait_pid_dead(decoder_pid)


def test_v10_result_json_has_bounded_atomic_output(tmp_path):
    loaded = module()
    loaded.MAX_RESULT_JSON_BYTES = 32
    with pytest.raises(loaded.StreamObservationError, match="bounded JSON output size"):
        loaded.atomic_json(tmp_path / "result.json", {"payload": "x" * 100})
    assert not (tmp_path / "result.json").exists()


def test_v10_contract_records_cleanup_and_output_bound():
    import json
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert contract["result_output"]["max_json_bytes"] == 134217728
    assert contract["result_output"]["oversize_is_failure"] is True
    assert contract["frame_processing"]["per_frame_scratch"]["cleanup_on_exception"] is True
    assert contract["cancellation_supervision"]["worker_signal_handlers"] == ["SIGTERM", "SIGINT"]
    assert contract["cancellation_supervision"]["decoder_start_new_session"] is True
    assert contract["cancellation_supervision"]["decoder_parent_death_signal"] == "SIGTERM via Linux PR_SET_PDEATHSIG"
    assert contract["cancellation_supervision"]["real_os_signal_test_required"] is True
    assert contract["old_products_immutable"] is True


def test_v10_registers_dataclass_backend_before_import(tmp_path):
    loaded = module()
    backend_path = tmp_path / "dataclass_backend.py"
    backend_path.write_text("from dataclasses import dataclass\n@dataclass\nclass DecodedFrame:\n    value: int\n", encoding="utf-8")
    backend = loaded.load_backend(backend_path)
    assert backend.__name__ == "ds02_direct_convert_for_f2_stream_v10"
    assert sys.modules[backend.__name__] is backend
