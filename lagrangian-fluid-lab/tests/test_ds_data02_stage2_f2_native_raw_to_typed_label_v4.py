from __future__ import annotations

import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import time
import types

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ds_data02_stage2_f2_native_raw_to_typed_label_v4.py"
spec = importlib.util.spec_from_file_location("ds02_scratch_v4_test", SCRIPT)
assert spec is not None and spec.loader is not None
v4 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v4)


def _state(*, limit: int = 1024, timeout: float = 2.0) -> dict[str, object]:
    return {
        "max_frame_scratch_bytes": limit,
        "decoder_timeout_seconds": timeout,
        "active_frame_directories": 0,
        "max_live_frame_directories": 0,
        "frames_started": 0,
        "frames_cleaned": 0,
        "scratch_bytes_peak": 0,
        "scratch_files_peak": 0,
        "cleanup_failures": [],
        "frame_records": [],
    }


def _loader(function):
    module = types.SimpleNamespace()
    module.subprocess = subprocess
    module.decode_frame = function

    class Loader:
        def _load_module(self, _path, _name):
            return module

    return Loader(), module


def _run_decode(tmp_path: Path, function, *, limit: int = 1024, timeout: float = 2.0):
    loader, module = _loader(function)
    state = _state(limit=limit, timeout=timeout)
    root = tmp_path / "owned"
    root.mkdir()
    original, restore = v4.install_decoder_scratch(loader, state)
    try:
        converter = loader._load_module(Path("unused"), "_ds02_bound_converter_v2")
        result = converter.decode_frame(Path("frame"), Path("decoder"), root, 0)
    finally:
        restore()
        shutil.rmtree(root, ignore_errors=True)
    return result, state, module


def test_v4_measures_peak_and_cleans_per_frame(tmp_path: Path) -> None:
    def decode(_frame, _decoder, scratch, _index):
        path = Path(scratch) / "decoded.bin"
        path.write_bytes(b"x" * 512)
        time.sleep(0.06)
        return "decoded"

    result, state, _module = _run_decode(tmp_path, decode, limit=1024)
    assert result == "decoded"
    assert int(state["scratch_bytes_peak"]) >= 512
    assert state["frames_cleaned"] == 1
    assert state["cleanup_failures"] == []
    record = state["frame_records"][0]
    assert record["peak_bytes"] >= 512
    assert record["cleanup"] == "PASS"


def test_v4_live_byte_guard_interrupts_and_cleans(tmp_path: Path) -> None:
    def decode(_frame, _decoder, scratch, _index):
        Path(scratch, "too-large.bin").write_bytes(b"x" * 4096)
        time.sleep(1.0)
        return "must-not-return"

    with pytest.raises(v4.OwnedScratchLimitError, match="scratch byte budget exceeded"):
        _run_decode(tmp_path, decode, limit=128, timeout=2.0)


def test_v4_decoder_subprocess_has_finite_timeout_and_owned_group(tmp_path: Path) -> None:
    def decode(_frame, _decoder, _scratch, _index):
        module = sys.modules[__name__]  # keep this callback independent of globals in v4
        del module
        # The wrapper replaces the module-local subprocess object before this
        # callback runs.  ``_loader`` exposes it through the closure below.
        return "unused"

    loader, converter = _loader(decode)
    state = _state(limit=1024, timeout=0.1)
    root = tmp_path / "owned"
    root.mkdir()

    def timeout_decode(_frame, _decoder, _scratch, _index):
        converter.subprocess.run(
            [sys.executable, "-c", "import time; time.sleep(2)"],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            text=True, timeout=180,
        )

    converter.decode_frame = timeout_decode
    _original, restore = v4.install_decoder_scratch(loader, state)
    try:
        bound = loader._load_module(Path("unused"), "_ds02_bound_converter_v2")
        with pytest.raises(v4.OwnedDecoderTimeout, match="exceeded"):
            bound.decode_frame(Path("frame"), Path("decoder"), root, 0)
    finally:
        restore()
        shutil.rmtree(root, ignore_errors=True)
    assert state["frames_cleaned"] == 1
    assert state["frame_records"][0]["cleanup"] == "PASS"


def test_v4_cleanup_failure_is_evidence_and_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def decode(_frame, _decoder, scratch, _index):
        Path(scratch, "decoded.bin").write_bytes(b"ok")
        return "decoded"

    loader, _module = _loader(decode)
    state = _state()
    root = tmp_path / "owned"
    root.mkdir()
    _original, restore = v4.install_decoder_scratch(loader, state)
    monkeypatch.setattr(v4.shutil, "rmtree", lambda _path: None)
    try:
        bound = loader._load_module(Path("unused"), "_ds02_bound_converter_v2")
        with pytest.raises(v4.OwnedScratchError, match="frame scratch remained"):
            bound.decode_frame(Path("frame"), Path("decoder"), root, 0)
    finally:
        restore()
        monkeypatch.undo()
        shutil.rmtree(root, ignore_errors=True)
    assert state["frames_cleaned"] == 0
    assert state["cleanup_failures"]
    assert state["frame_records"][0]["cleanup"] == "FAILED"
