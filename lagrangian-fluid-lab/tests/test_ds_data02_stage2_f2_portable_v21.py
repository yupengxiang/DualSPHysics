from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import sys

import pytest


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import ds_data02_stage2_f2_portable_v21 as v21  # noqa: E402
import ds_data02_stage2_f2_replay_runner_v21 as runner_v21  # noqa: E402


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _profile(tmp_path: Path) -> dict:
    small = tmp_path / "source.txt"
    small.write_bytes(b"portable-small-source\n")
    h5 = tmp_path / "trajectory.h5"
    h5.write_bytes(b"synthetic-hdf5-bytes")
    profile = {
        "schema": v21.PROFILE_SCHEMA,
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
    profile["sha256"] = v21.canonical_sha(profile)
    return profile


def _relocated(tmp_path: Path) -> tuple[dict, dict[str, str]]:
    profile = _profile(tmp_path)
    small = tmp_path / "relocated-small.txt"
    small.write_bytes(b"portable-small-source\n")
    h5 = tmp_path / "relocated.h5"
    h5.write_bytes(b"synthetic-hdf5-bytes")
    return profile, {"small": str(small), "trajectory_h5": str(h5)}


def _rebind(profile: dict) -> dict:
    profile["sha256"] = v21.canonical_sha(profile)
    return profile


def test_modified_profile_is_rejected_even_when_all_files_are_valid(tmp_path: Path) -> None:
    profile = _profile(tmp_path)
    profile["profile_id"] = "modified-after-build"
    with pytest.raises(v21.PortableV21BindingError, match="canonical SHA"):
        v21.validate_profile(profile)


def test_duplicate_role_is_rejected_after_recanonicalizing(tmp_path: Path) -> None:
    profile = _profile(tmp_path)
    profile["original_sources"].append(copy.deepcopy(profile["original_sources"][0]))
    _rebind(profile)
    with pytest.raises(v21.PortableV21BindingError, match="duplicate"):
        v21.validate_profile(profile)


def test_unsafe_relative_path_is_rejected_after_recanonicalizing(tmp_path: Path) -> None:
    profile = _profile(tmp_path)
    profile["original_sources"][0]["bundle_relative_path"] = "sources/../outside.txt"
    _rebind(profile)
    with pytest.raises(v21.PortableV21BindingError, match="escape"):
        v21.validate_profile(profile)


def test_overlay_passes_only_relocated_role_paths_to_consumer(tmp_path: Path) -> None:
    profile, path_map = _relocated(tmp_path)
    result = v21.verify_relocated_profile(profile, path_map, full_replay=True)
    assert result["status"] == "FULL_REPLAY_SOURCE_VERIFIED"
    assert set(result["consumer_input"]["role_to_relocated_path"]) == {"small", "trajectory_h5"}
    assert all(Path(path).resolve() != Path(profile["original_sources"][0]["original_path"]).resolve()
               for path in result["path_map"].values())


def test_original_absolute_path_cannot_be_used_as_overlay_fallback(tmp_path: Path) -> None:
    profile, path_map = _relocated(tmp_path)
    path_map["small"] = profile["original_sources"][0]["original_path"]
    with pytest.raises(v21.PortableV21BindingError, match="original source"):
        v21.verify_relocated_profile(profile, path_map, full_replay=False)


def test_same_size_wrong_hdf5_content_is_rejected_on_full_replay(tmp_path: Path) -> None:
    profile, path_map = _relocated(tmp_path)
    wrong = tmp_path / "wrong.h5"
    wrong.write_bytes(b"synthetic-hdf5-byteX")
    assert wrong.stat().st_size == profile["trajectory_h5"]["bytes"]
    path_map["trajectory_h5"] = str(wrong)
    with pytest.raises(v21.PortableV21BindingError, match="SHA differs"):
        v21.verify_relocated_profile(profile, path_map, full_replay=True)


def test_existing_nonempty_bundle_root_is_never_overwritten(tmp_path: Path) -> None:
    profile = _profile(tmp_path)
    root = tmp_path / "existing-bundle"
    root.mkdir()
    sentinel = root / "sentinel.txt"
    sentinel.write_text("keep")
    with pytest.raises(v21.PortableV21BindingError, match="existing bundle root"):
        v21.copy_bundle(profile, root)
    assert sentinel.read_text() == "keep"


def test_existing_empty_bundle_root_is_also_rejected(tmp_path: Path) -> None:
    profile = _profile(tmp_path)
    root = tmp_path / "empty-bundle"
    root.mkdir()
    with pytest.raises(v21.PortableV21BindingError, match="existing bundle root"):
        v21.copy_bundle(profile, root)


def test_two_real_sources_sharing_one_new_parent_are_copied(tmp_path: Path) -> None:
    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    first.write_text("first\n")
    second.write_text("second\n")
    trajectory = tmp_path / "trajectory.h5"
    trajectory.write_bytes(b"synthetic-hdf5-bytes")
    profile = {
        "schema": v21.PROFILE_SCHEMA,
        "profile_id": "shared-parent-fixture",
        "original_sources": [
            {"role": "first", "original_path": str(first), "content_sha256": _sha(first),
             "bytes": first.stat().st_size, "original_mtime_ns": first.stat().st_mtime_ns,
             "bundle_relative_path": "runtime/shared/first.py"},
            {"role": "second", "original_path": str(second), "content_sha256": _sha(second),
             "bytes": second.stat().st_size, "original_mtime_ns": second.stat().st_mtime_ns,
             "bundle_relative_path": "runtime/shared/second.py"},
        ],
        "trajectory_h5": {"role": "trajectory_h5", "original_path": str(trajectory),
                           "expected_content_sha256": _sha(trajectory), "bytes": trajectory.stat().st_size,
                           "original_mtime_ns": trajectory.stat().st_mtime_ns,
                           "bundle_relative_path": "trajectory/trajectory.h5"},
    }
    profile["sha256"] = v21.canonical_sha(profile)
    bundle = tmp_path / "bundle"
    result = v21.copy_bundle(profile, bundle, copy_hdf5=False)
    assert Path(result["path_map"]["first"]).read_text() == "first\n"
    assert Path(result["path_map"]["second"]).read_text() == "second\n"
    assert Path(result["path_map"]["first"]).parent == Path(result["path_map"]["second"]).parent


def test_existing_target_file_is_still_rejected_after_shared_parent_exists(tmp_path: Path) -> None:
    profile = _profile(tmp_path)
    destination = tmp_path / "bundle" / "runtime" / "shared" / "source.txt"
    destination.parent.mkdir(parents=True)
    destination.write_text("historical\n")
    with pytest.raises(v21.PortableV21BindingError, match="overwrite"):
        v21._copy_new(Path(profile["original_sources"][0]["original_path"]), destination)
    assert destination.read_text() == "historical\n"


def test_existing_output_is_rejected_by_prepare_replay(tmp_path: Path) -> None:
    profile, path_map = _relocated(tmp_path)
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"schema": v21.REQUEST_SCHEMA}) + "\n")
    output = tmp_path / "overlay.json"
    output.write_text("existing\n")
    with pytest.raises(v21.PortableV21BindingError, match="existing destination"):
        v21.prepare_replay(profile, path_map, request, output, full_replay=True)
    assert output.read_text() == "existing\n"


def test_map_role_set_must_be_exact(tmp_path: Path) -> None:
    profile, path_map = _relocated(tmp_path)
    del path_map["small"]
    with pytest.raises(v21.PortableV21BindingError, match="role set"):
        v21.verify_relocated_profile(profile, path_map)


def _engine_fixture(tmp_path: Path) -> tuple[dict, dict[str, str], dict]:
    profile = _profile(tmp_path)
    request = {
        "schema": v21.REQUEST_SCHEMA,
        "source_files": [{
            "role": "small",
            "path": profile["original_sources"][0]["original_path"],
            "sha256": profile["original_sources"][0]["content_sha256"],
        }],
        "trajectory_h5": {
            "path": profile["trajectory_h5"]["original_path"],
            "producer_declared_sha256": profile["trajectory_h5"]["expected_content_sha256"],
        },
    }
    path_map = _relocated(tmp_path)[1]
    official = {}
    for role in ("motion_engine_jmotion_data", "motion_engine_jmotion_mov", "motion_engine_jmotion_obj"):
        original = tmp_path / f"{role}.h"
        original.write_text(role)
        relocated = tmp_path / "bundle" / "runtime" / "engine" / original.name
        relocated.parent.mkdir(parents=True, exist_ok=True)
        relocated.write_text(role)
        profile.setdefault("supporting_sources", []).append({
            "role": role,
            "original_path": str(original),
            "content_sha256": _sha(original),
            "bytes": original.stat().st_size,
            "original_mtime_ns": original.stat().st_mtime_ns,
            "bundle_relative_path": f"runtime/engine/{role}.h",
        })
        path_map[role] = str(relocated)
        official[role] = {"path": str(original), "sha256": _sha(original)}
    request["motion_engine_sources"] = copy.deepcopy(official)
    request["source_code_binding"] = {"official_motion_engine": copy.deepcopy(official)}
    h5 = Path(profile["trajectory_h5"]["original_path"])
    request["trajectory_h5"] = {
        "path": str(h5),
        "bytes": h5.stat().st_size,
        "mtime_ns": h5.stat().st_mtime_ns,
        "producer_declared_sha256": _sha(h5),
        "hash_mode": "producer_attested_only_no_content_hash",
    }
    request["portable_migration"] = {
        "expected_trajectory_content_sha256": _sha(h5),
    }
    _rebind(profile)
    return profile, path_map, request


def test_nested_motion_engine_paths_are_rebound_before_v15_preflight(tmp_path: Path) -> None:
    profile, path_map, request = _engine_fixture(tmp_path)
    target_h5 = Path(path_map["trajectory_h5"])
    overlay = {"source_records": [{
        "role": "trajectory_h5", "content_hash_verified": True,
        "content_sha256": _sha(target_h5),
    }]}
    bound = v21.relocate_request_for_consumer(request, profile, path_map,
                                              overlay_receipt=overlay)
    for role, item in bound["motion_engine_sources"].items():
        assert item["path"] == path_map[role]
    for role, item in bound["source_code_binding"]["official_motion_engine"].items():
        assert item["path"] == path_map[role]
    assert all(original not in json.dumps(bound)
               for original in [entry["original_path"] for entry in profile["supporting_sources"]])
    assert bound["relocation"]["original_path_fallback"] == "FORBIDDEN"


def test_nested_engine_role_missing_from_overlay_is_rejected(tmp_path: Path) -> None:
    profile, path_map, request = _engine_fixture(tmp_path)
    del path_map["motion_engine_jmotion_obj"]
    with pytest.raises(v21.PortableV21BindingError, match="role set"):
        v21.relocate_request_for_consumer(request, profile, path_map)


def test_v12_request_schema_cannot_enter_v15_consumer(tmp_path: Path) -> None:
    profile, path_map, request = _engine_fixture(tmp_path)
    request["schema"] = "ds02.stage2.f2-s1-replay-request.v12"
    with pytest.raises(v21.PortableV21BindingError, match="v15 replay request"):
        v21.relocate_request_for_consumer(request, profile, path_map)


def test_python_open_audit_allows_relocated_role_and_records_it(tmp_path: Path) -> None:
    profile, path_map = _relocated(tmp_path)
    audit = runner_v21.AccessAudit(profile, {"source_files": []}, path_map)
    audit.install()
    # Call the same hook signature used by sys.addaudithook.  The relocated
    # path is inside the bundle overlay and must be recorded as allowed.
    audit._hook("open", (path_map["small"], "r", 0))
    audit.deactivate()
    summary = audit.summary()
    assert summary["observed_open_file_count"] == 1
    assert summary["rejected_open_file_count"] == 0
    assert summary["reason_counts"]["ALLOWED_BUNDLE_RUNTIME_OR_DEPENDENCY"] == 1


def test_installed_python_open_audit_rejects_original_source_and_keeps_receipt(tmp_path: Path) -> None:
    profile, path_map = _relocated(tmp_path)
    original = profile["original_sources"][0]["original_path"]
    audit = runner_v21.AccessAudit(profile, {"source_files": [{"path": original}]}, path_map)
    audit.install()
    try:
        # This is an actual Python open call, rather than a direct invocation
        # of the helper.  The audit hook must reject it before the file is read.
        with pytest.raises(runner_v21.ReplayV21AccessAuditViolation, match="FORBIDDEN_ORIGINAL_SOURCE_PATH"):
            with Path(original).open("rb"):
                pass
    finally:
        audit.deactivate()
    summary = audit.summary()
    assert summary["rejected_open_file_count"] == 1
    assert summary["rejected_open_files"] == [str(Path(original).resolve())]
    assert summary["reason_counts"]["FORBIDDEN_ORIGINAL_SOURCE_PATH"] == 1


def test_full_hash_migration_binds_target_mtime_and_preserves_producer_stat(tmp_path: Path) -> None:
    profile, path_map, request = _engine_fixture(tmp_path)
    source_h5 = Path(profile["trajectory_h5"]["original_path"])
    target_h5 = Path(path_map["trajectory_h5"])
    # copyfile gives the overlay a distinct mtime; the content remains the
    # producer-declared bytes.  A migrated request must bind this new stat.
    target_h5.touch()
    os_mtime = source_h5.stat().st_mtime_ns + 987654321
    import os
    os.utime(target_h5, ns=(os_mtime, os_mtime))
    request["portable_migration"] = {
        "expected_trajectory_content_sha256": _sha(target_h5),
    }
    request["trajectory_h5"] = {
        "path": str(source_h5),
        "bytes": source_h5.stat().st_size,
        "mtime_ns": source_h5.stat().st_mtime_ns,
        "producer_declared_sha256": _sha(source_h5),
        "hash_mode": "producer_attested_only_no_content_hash",
    }
    target_h5 = Path(path_map["trajectory_h5"])
    overlay = {"source_records": [{
        "role": "trajectory_h5", "content_hash_verified": True,
        "content_sha256": _sha(target_h5),
    }]}
    bound = v21.relocate_request_for_consumer(request, profile, path_map,
                                              overlay_receipt=overlay)
    assert bound["trajectory_h5"]["path"] == str(target_h5.resolve())
    assert bound["trajectory_h5"]["mtime_ns"] == target_h5.stat().st_mtime_ns
    assert bound["trajectory_h5"]["mtime_ns"] != request["trajectory_h5"]["mtime_ns"]
    receipt = bound["relocation"]["trajectory_h5"]
    assert receipt["original_mtime_ns"] == request["trajectory_h5"]["mtime_ns"]
    assert receipt["relocated_mtime_ns"] == target_h5.stat().st_mtime_ns
    assert receipt["producer_mtime_is_provenance_only"] is True
    assert bound["relocation"]["status"].startswith("PORTABLE_FULL_CONTENT_HASH")


def test_full_hash_migration_rejects_same_size_wrong_content_even_with_new_stat(tmp_path: Path) -> None:
    profile, path_map, request = _engine_fixture(tmp_path)
    source_h5 = Path(profile["trajectory_h5"]["original_path"])
    target_h5 = Path(path_map["trajectory_h5"])
    wrong = tmp_path / "wrong-relocated.h5"
    wrong.write_bytes(b"synthetic-hdf5-byteX")
    assert wrong.stat().st_size == source_h5.stat().st_size
    path_map["trajectory_h5"] = str(wrong)
    request["portable_migration"] = {
        "expected_trajectory_content_sha256": _sha(source_h5),
    }
    request["trajectory_h5"] = {
        "path": str(source_h5),
        "bytes": source_h5.stat().st_size,
        "mtime_ns": source_h5.stat().st_mtime_ns,
        "producer_declared_sha256": _sha(source_h5),
        "hash_mode": "producer_attested_only_no_content_hash",
    }
    with pytest.raises(v21.PortableV21BindingError, match="content SHA-256 differs"):
        v21.relocate_request_for_consumer(request, profile, path_map,
                                          io_slot_approved=True)


def test_metadata_migration_requires_preverified_overlay_receipt_without_h5_read(tmp_path: Path) -> None:
    profile, path_map, request = _engine_fixture(tmp_path)
    with pytest.raises(v21.PortableV21BindingError, match="full overlay content-SHA receipt"):
        v21.relocate_request_for_consumer(request, profile, path_map)
