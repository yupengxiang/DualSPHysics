from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import pytest


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import ds_data02_stage2_f2_portable_v23_metadata_probe as probe  # noqa: E402


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: str | dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, dict):
        path.write_text(json.dumps(value, sort_keys=True) + "\n")
    else:
        path.write_text(value)


def _synthetic_v22_bundle(tmp_path: Path) -> tuple[dict, dict, dict]:
    roles = sorted(probe.REQUIRED_METADATA_ROLES | {
        "completed_v15_report_json", "v16_flux_forward_sidecar", "initial_csv",
        "native_runparts", "native_partout",
    })
    originals = tmp_path / "originals"
    copied = tmp_path / "copied"
    original_sources = []
    path_map: dict[str, str] = {}
    records: list[dict] = []
    files: dict[str, Path] = {}
    for role in roles:
        source = originals / role / ("payload.json" if role.endswith("receipt") else "payload.txt")
        target = copied / role / source.name
        if role == "current_catalog":
            payload: str | dict = {
                "cases": [{"unused": i} for i in range(78)] + [{
                    "family_id": "F2",
                    "physical_case_id": "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090",
                    "runtime_case_alias": "F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT090_DP010_SPATIAL_REFERENCE_SAVE010",
                    "frames": 401, "particles": 418104,
                    "trajectory": {"producer_declared_sha256": "a" * 64},
                }]
            }
        elif role == "scientific_scan_sidecar":
            payload = {"family_id": "F2", "physical_case_id": "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090", "full_saved_timeline_scanned": True}
        elif role in {"gencase_receipt", "solver_receipt"}:
            payload = {"status": "completed", "returncode": 0,
                       "input_hashes_at_launch": {}, "input_hashes_after_run": {}}
        elif role == "native_reconciliation_receipt":
            payload = {"status": "completed", "returncode": 0,
                       "input_hashes_at_launch": {}, "input_hashes_after_run": {}}
        elif role == "native_reconciliation":
            payload = "reconciliation"
        elif role == "manifest":
            payload = "manifest"
        else:
            payload = f"{role}\n"
        _write(source, payload)
        _write(target, payload)
        files[role] = target
        digest = _sha(target)
        original_sources.append({"role": role, "original_path": str(source),
                                 "content_sha256": digest, "bytes": target.stat().st_size,
                                 "original_mtime_ns": source.stat().st_mtime_ns,
                                 "bundle_relative_path": f"sources/{role}/{source.name}"})
        path_map[role] = str(target)
        records.append({"role": role, "original_path": str(source),
                        "relocated_path": str(target), "expected_sha256": digest,
                        "content_sha256": digest, "content_hash_verified": True,
                        "bytes": target.stat().st_size})

    # Make the exact metadata relationships that v15/v14 consume.
    scan_original = next(item["original_path"] for item in original_sources if item["role"] == "scientific_scan_sidecar")
    scan_sha = next(item["content_sha256"] for item in original_sources if item["role"] == "scientific_scan_sidecar")
    motion_original = next(item["original_path"] for item in original_sources if item["role"] == "motion_dat")
    motion_sha = next(item["content_sha256"] for item in original_sources if item["role"] == "motion_dat")
    metadata_original = next(item["original_path"] for item in original_sources if item["role"] == "source_metadata")
    metadata_sha = next(item["content_sha256"] for item in original_sources if item["role"] == "source_metadata")
    for role in ("gencase_receipt", "solver_receipt"):
        payload = {"status": "completed", "returncode": 0,
                   "input_hashes_at_launch": {motion_original: motion_sha, metadata_original: metadata_sha},
                   "input_hashes_after_run": {motion_original: motion_sha, metadata_original: metadata_sha}}
        _write(files[role], payload)
        source = next(item["original_path"] for item in original_sources if item["role"] == role)
        _write(Path(source), payload)
        digest = _sha(files[role])
        for item in original_sources:
            if item["role"] == role:
                item["content_sha256"] = digest
        for record in records:
            if record["role"] == role:
                record["content_sha256"] = digest
    payload = {"status": "completed", "returncode": 0,
               "input_hashes_at_launch": {scan_original: scan_sha},
               "input_hashes_after_run": {scan_original: scan_sha}}
    _write(files["native_reconciliation_receipt"], payload)
    source = next(item["original_path"] for item in original_sources if item["role"] == "native_reconciliation_receipt")
    _write(Path(source), payload)
    digest = _sha(files["native_reconciliation_receipt"])
    for item in original_sources:
        if item["role"] == "native_reconciliation_receipt":
            item["content_sha256"] = digest
    for record in records:
        if record["role"] == "native_reconciliation_receipt":
            record["content_sha256"] = digest
    h5_source = originals / "trajectory.h5"
    h5_target = copied / "trajectory" / "trajectory.h5"
    _write(h5_source, "synthetic-h5")
    _write(h5_target, "synthetic-h5")
    h5_sha = _sha(h5_target)
    trajectory_entry = {
        "role": "trajectory_h5", "original_path": str(h5_source),
        "expected_content_sha256": h5_sha, "producer_declared_sha256": h5_sha,
        "bytes": h5_target.stat().st_size, "original_mtime_ns": h5_source.stat().st_mtime_ns,
        "bundle_relative_path": "trajectory/trajectory.h5",
    }
    path_map["trajectory_h5"] = str(h5_target)
    records.append({"role": "trajectory_h5", "original_path": str(h5_source),
                    "relocated_path": str(h5_target), "expected_sha256": h5_sha,
                    "content_sha256": h5_sha, "content_hash_verified": True,
                    "bytes": h5_target.stat().st_size})
    # Update CURRENT after the H5 digest is known.
    current_path = files["current_catalog"]
    current = json.loads(current_path.read_text())
    current["cases"][78]["trajectory"]["producer_declared_sha256"] = h5_sha
    _write(current_path, current)
    current_source = next(item["original_path"] for item in original_sources if item["role"] == "current_catalog")
    _write(Path(current_source), current)
    current_digest = _sha(current_path)
    for item in original_sources:
        if item["role"] == "current_catalog":
            item["content_sha256"] = current_digest
    for record in records:
        if record["role"] == "current_catalog":
            record["content_sha256"] = current_digest
    profile = {
        "schema": "ds02.stage2.f2-s1-portable-source-profile.v22",
        "original_sources": original_sources,
        "supporting_sources": [],
        "trajectory_h5": trajectory_entry,
    }
    copy_result = {"schema": "ds02.stage2.f2-s1-portable-copy-result.v22", "path_map": path_map}
    replay_input = {"schema": "ds02.stage2.f2-s1-portable-replay-input.v22", "source_records": records}
    return profile, copy_result, replay_input


def test_actual_transitive_alias_logic_keeps_scan_original_key_as_provenance(tmp_path: Path) -> None:
    profile, copy_result, replay_input = _synthetic_v22_bundle(tmp_path)
    result = probe._verify_inherited_bundle(profile, copy_result, replay_input)
    assert result["case_index"] == 78
    assert result["trajectory_h5_read_by_probe"] is False
    assert result["native_reconciliation_scan_aliases"]
    alias = result["native_reconciliation_scan_aliases"][0]
    assert alias["path_semantics"] == "ACTIONABLE_ROLE_ALIAS"
    assert alias["original_input_path"] != alias["relocated_input_path"]
    assert result["gencase_solver_control_support"]["gencase_receipt"]["launch_and_finish_supported"] is True


def test_unbound_scan_hash_is_rejected_even_when_receipt_is_completed(tmp_path: Path) -> None:
    profile, copy_result, replay_input = _synthetic_v22_bundle(tmp_path)
    receipt = next(item for item in replay_input["source_records"]
                   if item["role"] == "native_reconciliation_receipt")
    target = Path(copy_result["path_map"]["native_reconciliation_receipt"])
    value = json.loads(target.read_text())
    value["input_hashes_after_run"] = {"/unbound/producer/scan.json": "b" * 64}
    target.write_text(json.dumps(value) + "\n")
    receipt["content_sha256"] = _sha(target)
    with pytest.raises(probe.MetadataProbeError, match="scientific-scan SHA alias"):
        probe._verify_inherited_bundle(profile, copy_result, replay_input)


def test_h5_inherited_receipt_is_required(tmp_path: Path) -> None:
    profile, copy_result, replay_input = _synthetic_v22_bundle(tmp_path)
    replay_input["source_records"] = [item for item in replay_input["source_records"]
                                      if item["role"] != "trajectory_h5"]
    with pytest.raises(probe.MetadataProbeError, match="full-copy HDF5"):
        probe._verify_inherited_bundle(profile, copy_result, replay_input)
