from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_coarse_active_stream_v3.py"
REQUEST_DIR = ROOT / "campaigns/ds-data-02/stage2/requests/f2-coarse-active-stream-v3-root-forward-108-002"
MANIFEST = REQUEST_DIR / "f2-coarse-active-stream-v3-manifest.json"
REQUEST = REQUEST_DIR / "f2-coarse-active-stream-v3-request.json"


def module():
    spec = importlib.util.spec_from_file_location("f2_coarse_active_stream_v3", SCRIPT)
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def test_v3_request_binds_write_monitor_and_keeps_claims_unknown():
    request = json.loads(REQUEST.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["schema"] == "ds02.stage2.f2.coarse-active-stream.manifest.v3"
    assert manifest["runtime"]["max_scratch_bytes"] == 134217728
    assert manifest["runtime"]["scratch_poll_interval_s"] == pytest.approx(0.01)
    assert request["guard_policy"]["scratch_write_monitor_required"] is True
    assert request["guard_policy"]["decoder_child_terminated_on_overrun"] is True
    assert request["guard_policy"]["scratch_cleanup_on_exception"] is True
    assert request["source_binding"]["max_decoder_seconds_per_frame"] == 180.0
    assert request["hdf5_read"] is False
    assert request["solver_launch"] is False
    assert request["physical_qualification"] == {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}


def test_v3_kills_decoder_on_write_overrun_and_outer_cleanup(tmp_path: Path):
    loaded = module()
    decoder = tmp_path / "fake-decoder.py"
    decoder.write_text(
        "#!/usr/bin/env python3\n"
        "import pathlib, sys, time\n"
        "prefix = pathlib.Path(sys.argv[2])\n"
        "prefix.parent.mkdir(parents=True, exist_ok=True)\n"
        "(prefix.parent / 'oversize.bin').write_bytes(b'x' * 4096)\n"
        "time.sleep(5)\n",
        encoding="utf-8",
    )
    decoder.chmod(decoder.stat().st_mode | 0o111)
    frame = tmp_path / "Part_0000.bi4"
    frame.write_bytes(b"synthetic")
    parent = tmp_path / "attempt"
    parent.mkdir()
    with loaded.tempfile.TemporaryDirectory(prefix="frame-", dir=str(parent)) as scratch:
        with pytest.raises(loaded.StreamObservationError, match="exceeded limit"):
            loaded.decode_frame_bounded(
                backend=object(),
                frame_path=frame,
                decoder=decoder,
                scratch_root=Path(scratch),
                index=0,
                max_scratch_bytes=1024,
                poll_interval_s=0.005,
                max_decoder_seconds=2.0,
            )
        assert loaded.directory_bytes(Path(scratch)) >= 4096
    assert loaded.directory_bytes(parent) == 0


def test_v3_directory_bytes_does_not_follow_symlink(tmp_path: Path):
    loaded = module()
    root = tmp_path / "scratch"
    root.mkdir()
    (root / "payload").write_bytes(b"abc")
    target = tmp_path / "outside"
    target.write_bytes(b"outside")
    (root / "link").symlink_to(target)
    assert loaded.directory_bytes(root) == 3
