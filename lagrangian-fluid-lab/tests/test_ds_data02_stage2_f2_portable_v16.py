from __future__ import annotations

from pathlib import Path
import hashlib
import sys

import pytest


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import ds_data02_stage2_f2_portable_v16 as v16  # noqa: E402


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _profile(tmp_path: Path) -> dict:
    small = tmp_path / "source.txt"
    small.write_bytes(b"portable-small-source\n")
    h5 = tmp_path / "trajectory.h5"
    h5.write_bytes(b"synthetic-hdf5-bytes")
    return {
        "schema": v16.PROFILE_SCHEMA,
        "original_sources": [{
            "role": "small",
            "original_path": str(small),
            "content_sha256": _sha(small),
            "bytes": small.stat().st_size,
            "original_mtime_ns": small.stat().st_mtime_ns,
        }],
        "trajectory_h5": {
            "role": "trajectory_h5",
            "original_path": str(h5),
            "expected_content_sha256": _sha(h5),
            "bytes": h5.stat().st_size,
            "original_mtime_ns": h5.stat().st_mtime_ns,
        },
    }


def test_relocated_small_source_allows_new_path_and_mtime(tmp_path: Path) -> None:
    profile = _profile(tmp_path)
    relocated = tmp_path / "relocated-small.txt"
    relocated.write_bytes(b"portable-small-source\n")
    h5_copy = tmp_path / "relocated.h5"
    h5_copy.write_bytes(b"synthetic-hdf5-bytes")
    report = v16.verify_relocated_profile(
        profile,
        {"small": str(relocated), "trajectory_h5": str(h5_copy)},
        full_replay=True,
    )
    assert report["status"] == "FULL_REPLAY_SOURCE_VERIFIED"
    assert report["trajectory_h5"]["content_hash_verified"] is True
    assert report["source_records"][0]["original_path"] != report["source_records"][0]["relocated_path"]


def test_same_size_wrong_content_hdf5_is_rejected(tmp_path: Path) -> None:
    profile = _profile(tmp_path)
    relocated = tmp_path / "relocated-small.txt"
    relocated.write_bytes(b"portable-small-source\n")
    wrong_h5 = tmp_path / "wrong.h5"
    wrong_h5.write_bytes(b"synthetic-hdf5-byteX")
    assert wrong_h5.stat().st_size == profile["trajectory_h5"]["bytes"]
    with pytest.raises(v16.PortableV16BindingError, match="HDF5 content SHA"):
        v16.verify_relocated_profile(
            profile,
            {"small": str(relocated), "trajectory_h5": str(wrong_h5)},
            full_replay=True,
        )


def test_wrong_small_content_is_rejected_even_without_hdf5_full_hash(tmp_path: Path) -> None:
    profile = _profile(tmp_path)
    wrong_small = tmp_path / "wrong-small.txt"
    wrong_small.write_bytes(b"portable-small-sourceX")
    assert wrong_small.stat().st_size == profile["original_sources"][0]["bytes"]
    h5_copy = tmp_path / "relocated.h5"
    h5_copy.write_bytes(b"synthetic-hdf5-bytes")
    with pytest.raises(v16.PortableV16BindingError, match="source SHA"):
        v16.verify_relocated_profile(
            profile,
            {"small": str(wrong_small), "trajectory_h5": str(h5_copy)},
            full_replay=False,
        )


def test_metadata_overlay_does_not_grant_full_replay_without_hdf5_hash(tmp_path: Path) -> None:
    profile = _profile(tmp_path)
    relocated = tmp_path / "relocated-small.txt"
    relocated.write_bytes(b"portable-small-source\n")
    h5_copy = tmp_path / "relocated.h5"
    h5_copy.write_bytes(b"synthetic-hdf5-bytes")
    report = v16.verify_relocated_profile(
        profile,
        {"small": str(relocated), "trajectory_h5": str(h5_copy)},
        full_replay=False,
    )
    assert report["status"] == "SMALL_SOURCE_VERIFIED_HDF5_CONTENT_PENDING"
    assert report["trajectory_h5"]["content_hash_verified"] is False
