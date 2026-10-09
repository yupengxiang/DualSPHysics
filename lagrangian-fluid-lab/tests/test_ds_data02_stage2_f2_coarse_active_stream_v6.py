from __future__ import annotations

import hashlib
import importlib.util
import os
import stat
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_coarse_active_stream_v6.py"


def module():
    spec = importlib.util.spec_from_file_location("f2_coarse_active_stream_v6_test", SCRIPT)
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_v6_schema_and_header_only_scope_are_forward_only():
    loaded = module()
    assert loaded.SCHEMA == "ds02.stage2.f2.coarse-active-stream.v6"
    assert loaded.MANIFEST_SCHEMA == "ds02.stage2.f2.coarse-active-stream.manifest.v6"
    assert "full stream" not in loaded.__doc__.lower().split("no tolerance")[0]


def test_v6_frame_binding_hashes_only_the_first_frame(tmp_path):
    loaded = module()
    raw_root = tmp_path / "data"
    raw_root.mkdir()
    first = raw_root / "Part_0000.bi4"
    first.write_bytes(b"synthetic first frame")
    ref = {
        "path": str(first),
        "bytes": first.stat().st_size,
        "mtime_ns": first.stat().st_mtime_ns,
        "ctime_ns": first.stat().st_ctime_ns,
        "st_dev": first.stat().st_dev,
        "st_ino": first.stat().st_ino,
        "sha256": "PARENT_GUARD_COMPUTED",
    }
    bound_path, bound = loaded.bind_frame_stat(ref, raw_root.resolve(), "frame[0]")
    assert bound_path == first.resolve()
    assert bound["sha256"] == digest(first)
    assert bound["sha256"] != "PARENT_GUARD_COMPUTED"


def test_v6_decoder_final_scratch_cap_and_cleanup(tmp_path):
    loaded = module()
    decoder = tmp_path / "fake_decoder.py"
    decoder.write_text(
        "#!/usr/bin/env python3\n"
        "import pathlib, sys, time\n"
        "prefix=pathlib.Path(sys.argv[2])\n"
        "prefix.parent.mkdir(parents=True, exist_ok=True)\n"
        "(prefix.parent/'oversize.bin').write_bytes(b'x'*4096)\n"
        "time.sleep(0.3)\n",
        encoding="utf-8",
    )
    decoder.chmod(decoder.stat().st_mode | stat.S_IXUSR)
    frame = tmp_path / "Part_0000.bi4"
    frame.write_bytes(b"synthetic")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    with pytest.raises(loaded.StreamHeaderError, match="scratch exceeded"):
        loaded._probe_decoder(decoder, frame, scratch, max_scratch_bytes=128, max_seconds=5.0, poll_interval=0.001)
    assert not list(scratch.iterdir()) or all(item.name == "oversize.bin" for item in scratch.iterdir())


def test_v6_output_schema_keeps_header_probe_without_scientific_credit():
    loaded = module()
    assert loaded.SCHEMA == "ds02.stage2.f2.coarse-active-stream.v6"
    assert loaded.MANIFEST_SCHEMA == "ds02.stage2.f2.coarse-active-stream.manifest.v6"
