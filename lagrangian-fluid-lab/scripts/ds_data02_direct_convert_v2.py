#!/usr/bin/env python3
"""Use the preserved BI4 converter with bounded, per-frame decoder scratch.

The original converter and its numerical arrays remain unchanged.  Its decoder
loads arrays with numpy.fromfile, so decoded files can be removed immediately
after the frame has been loaded, before the next frame is decoded.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ds_data02_direct_convert as base

ORIGINAL_DECODE = base.decode_frame
ORIGINAL_CONVERT = base.convert_direct
SCRATCH_POLICY = "one private decoded frame; delete after arrays are loaded"
_usage = {"decoded_frames": 0, "max_decoded_frame_bytes": 0}


def decode_frame(frame_path: Path, decoder: Path, scratch_root: Path, index: int) -> base.DecodedFrame:
    scratch_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"decode-{index:04d}-", dir=scratch_root) as name:
        private = Path(name)
        frame = ORIGINAL_DECODE(frame_path, decoder, private, index)
        decoded_bytes = sum(p.stat().st_size for p in private.rglob("*") if p.is_file())
        _usage["decoded_frames"] += 1
        _usage["max_decoded_frame_bytes"] = max(_usage["max_decoded_frame_bytes"], decoded_bytes)
    return frame


def convert_direct(**kwargs):
    _usage.update(decoded_frames=0, max_decoded_frame_bytes=0)
    previous = base.decode_frame
    base.decode_frame = decode_frame
    try:
        report = ORIGINAL_CONVERT(**kwargs)
    finally:
        base.decode_frame = previous
    report["decoder_scratch"] = {
        "adapter_version": "ds_data02_direct_convert_v2",
        "policy": SCRATCH_POLICY,
        "max_live_decoded_frames": 1,
        "arrays_loaded_in_memory_before_cleanup": True,
        **_usage,
    }
    Path(kwargs["report_path"]).write_text(json.dumps(report, indent=2, sort_keys=True, default=base._json_default) + "\n")
    return report


def main(argv: Sequence[str] | None = None) -> int:
    previous = base.convert_direct
    base.convert_direct = convert_direct
    try:
        return base.main(argv)
    finally:
        base.convert_direct = previous


if __name__ == "__main__":
    raise SystemExit(main())
