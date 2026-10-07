from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys

import pytest


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import ds_data02_stage2_f2_portable_v17 as v17  # noqa: E402


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _profile(tmp_path: Path) -> dict:
    small = tmp_path / "source.txt"
    small.write_bytes(b"portable-small-source\n")
    h5 = tmp_path / "trajectory.h5"
    h5.write_bytes(b"synthetic-hdf5-bytes")
    profile = {
        "schema": v17.PROFILE_SCHEMA,
        "profile_id": "fixture",
        "original_sources": [{
            "role": "small",
            "original_path": str(small),
            "content_sha256": _sha(small),
            "bytes": small.stat().st_size,
            "original_mtime_ns": small.stat().st_mtime_ns,
            "bundle_relative_path": "sources/small/source.txt",
        }],
        "trajectory_h5": {
            "role": "trajectory_h5",
            "original_path": str(h5),
            "expected_content_sha256": _sha(h5),
            "bytes": h5.stat().st_size,
            "original_mtime_ns": h5.stat().st_mtime_ns,
            "bundle_relative_path": "trajectory/trajectory.h5",
        },
    }
    profile["sha256"] = v17.canonical_sha(profile)
    return profile


def _relocated(tmp_path: Path) -> tuple[dict, dict[str, str]]:
    profile = _profile(tmp_path)
    small = tmp_path / "relocated-small.txt"
    small.write_bytes(b"portable-small-source\n")
    h5 = tmp_path / "relocated.h5"
    h5.write_bytes(b"synthetic-hdf5-bytes")
    return profile, {"small": str(small), "trajectory_h5": str(h5)}


def _rebind(profile: dict) -> dict:
    profile["sha256"] = v17.canonical_sha(profile)
    return profile


def test_modified_profile_is_rejected_even_when_all_files_are_valid(tmp_path: Path) -> None:
    profile = _profile(tmp_path)
    profile["profile_id"] = "modified-after-build"
    with pytest.raises(v17.PortableV17BindingError, match="canonical SHA"):
        v17.validate_profile(profile)


def test_duplicate_role_is_rejected_after_recanonicalizing(tmp_path: Path) -> None:
    profile = _profile(tmp_path)
    profile["original_sources"].append(copy.deepcopy(profile["original_sources"][0]))
    _rebind(profile)
    with pytest.raises(v17.PortableV17BindingError, match="duplicate"):
        v17.validate_profile(profile)


def test_unsafe_relative_path_is_rejected_after_recanonicalizing(tmp_path: Path) -> None:
    profile = _profile(tmp_path)
    profile["original_sources"][0]["bundle_relative_path"] = "sources/../outside.txt"
    _rebind(profile)
    with pytest.raises(v17.PortableV17BindingError, match="escape"):
        v17.validate_profile(profile)


def test_overlay_passes_only_relocated_role_paths_to_consumer(tmp_path: Path) -> None:
    profile, path_map = _relocated(tmp_path)
    result = v17.verify_relocated_profile(profile, path_map, full_replay=True)
    assert result["status"] == "FULL_REPLAY_SOURCE_VERIFIED"
    assert set(result["consumer_input"]["role_to_relocated_path"]) == {"small", "trajectory_h5"}
    assert all(Path(path).resolve() != Path(profile["original_sources"][0]["original_path"]).resolve()
               for path in result["path_map"].values())


def test_original_absolute_path_cannot_be_used_as_overlay_fallback(tmp_path: Path) -> None:
    profile, path_map = _relocated(tmp_path)
    path_map["small"] = profile["original_sources"][0]["original_path"]
    with pytest.raises(v17.PortableV17BindingError, match="original source"):
        v17.verify_relocated_profile(profile, path_map, full_replay=False)


def test_same_size_wrong_hdf5_content_is_rejected_on_full_replay(tmp_path: Path) -> None:
    profile, path_map = _relocated(tmp_path)
    wrong = tmp_path / "wrong.h5"
    wrong.write_bytes(b"synthetic-hdf5-byteX")
    assert wrong.stat().st_size == profile["trajectory_h5"]["bytes"]
    path_map["trajectory_h5"] = str(wrong)
    with pytest.raises(v17.PortableV17BindingError, match="SHA differs"):
        v17.verify_relocated_profile(profile, path_map, full_replay=True)


def test_existing_nonempty_bundle_root_is_never_overwritten(tmp_path: Path) -> None:
    profile = _profile(tmp_path)
    root = tmp_path / "existing-bundle"
    root.mkdir()
    sentinel = root / "sentinel.txt"
    sentinel.write_text("keep")
    with pytest.raises(v17.PortableV17BindingError, match="existing bundle root"):
        v17.copy_bundle(profile, root)
    assert sentinel.read_text() == "keep"


def test_existing_empty_bundle_root_is_also_rejected(tmp_path: Path) -> None:
    profile = _profile(tmp_path)
    root = tmp_path / "empty-bundle"
    root.mkdir()
    with pytest.raises(v17.PortableV17BindingError, match="existing bundle root"):
        v17.copy_bundle(profile, root)


def test_existing_output_is_rejected_by_prepare_replay(tmp_path: Path) -> None:
    profile, path_map = _relocated(tmp_path)
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"schema": v17.REQUEST_SCHEMA}) + "\n")
    output = tmp_path / "overlay.json"
    output.write_text("existing\n")
    with pytest.raises(v17.PortableV17BindingError, match="existing destination"):
        v17.prepare_replay(profile, path_map, request, output, full_replay=True)
    assert output.read_text() == "existing\n"


def test_map_role_set_must_be_exact(tmp_path: Path) -> None:
    profile, path_map = _relocated(tmp_path)
    del path_map["small"]
    with pytest.raises(v17.PortableV17BindingError, match="role set"):
        v17.verify_relocated_profile(profile, path_map)
