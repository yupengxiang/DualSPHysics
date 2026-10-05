#!/usr/bin/env python3
"""Metadata-only contract test for the fresh070 AY0540 handoff."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
ARRAY_SUFFIXES = {".bi4", ".csv", ".h5", ".hdf5", ".npy", ".npz"}
OPAQUE_BASENAMES = {"python", "bi4_dump", "PartVTK_linux64"}
CASE = "F3_STAGE1_DP006_P1000_AY0540"
RECEIPT_SHA = "06c0dc29d67f36800600129e0a8b030caae5f75ba369a5d631b8fe8144b1ec04"
CONDITION_SHA = "b02eacdeb834e0b65ccb7121e3cd196b6af8f95983e2f0c27060939124745259"
ROOT140_REQUEST_SHA = "bfd8d3fa9b72f00e54b5e918fe8ac02c01a67c4037f4c1b55f049750554d312f"
QA_SHA = "7ff19bd2db1b731071ec0eeaa8dfe43bbb0cc27ecc5c2dc9d1bb8c0cb5f60349"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def check_input_closure(request: dict) -> None:
    files = request["input_files"]
    hashes = request["input_sha256"]
    assert set(files) == set(hashes)
    for raw in files:
        path = Path(raw)
        assert path.is_file(), path
        if path.suffix.lower() in ARRAY_SUFFIXES or path.name in OPAQUE_BASENAMES:
            assert isinstance(hashes[raw], str) and len(hashes[raw]) == 64
        else:
            assert digest(path) == hashes[raw], path


def check_native(owner: dict, request: dict) -> None:
    native = owner["native_full836"]
    receipt_path = Path(native["receipt"]["path"])
    assert receipt_path.is_file()
    assert digest(receipt_path) == RECEIPT_SHA
    assert native["receipt"]["sha256"] == RECEIPT_SHA
    assert native["status"] == "completed"
    assert native["returncode"] == 0
    assert native["expected_saved_frames"] == 836
    actual = load(receipt_path)
    actual_request = actual["request"]
    assert actual["status"] == "completed" and actual["returncode"] == 0
    assert actual_request["case_id"] == CASE
    assert actual_request["physical_condition_sha256"] == CONDITION_SHA
    assert actual_request["expected_saved_frames"] == 836
    initial = actual_request["initial_native_reference"]
    assert initial["actual_3d"] is True
    assert initial["native_particles"] == 179208
    assert initial["native_fluid"] == 67500
    assert initial["native_fixed"] == 111708
    assert initial["mass_normalization"] == "none"
    command = actual["command"]
    assert "-mdbc_noslip:1" in command
    assert "-tmax:8.35" in command and "-tout:0.01" in command
    assert any(str(item).startswith("-gpu:") for item in command)
    assert request["physical_condition_sha256"] == CONDITION_SHA


def check_command(request: dict, owner: dict) -> None:
    command = request["command"]
    assert command[0].endswith("/.venv/bin/python")
    assert command[1].endswith("/scripts/ds_data02_nvme_convert_v1.py")
    assert command[command.index("--staging-root") + 1] == "/tmp/ds02-nvme-conversion"
    assert command[command.index("--staging-limit-bytes") + 1] == "25769803776"
    assert command[command.index("--data-root") + 1] == owner["native_full836"]["data_root"]
    assert command[command.index("--generated-xml") + 1] == owner["prepared_input"]["generated_xml"]["path"]
    assert command[command.index("--solver-receipt") + 1] == owner["native_full836"]["receipt"]["path"]
    assert command[command.index("--gencase-receipt") + 1] == owner["genuine_gencase_receipt"]["path"]
    assert command[command.index("--owner-metadata") + 1] == str(HERE / "owners" / f"{CASE}.json")
    assert not any(str(item).startswith("-gpu:") for item in command)


def main() -> int:
    manifest = load(HERE / "manifest.json")
    binding = load(HERE / "source-binding.json")
    assert manifest["fresh_id"] == binding["fresh_id"] == "fresh070"
    assert manifest["case_ids"] == [CASE] and manifest["case_count"] == 1
    assert manifest["source_only"] is True
    assert manifest["all_native_full836_completed_zero"] is True
    assert manifest["all_typed_requests_disabled"] is True
    assert manifest["production_scope_approval"] is False
    assert manifest["independent_case_count_increment"] == 0
    assert binding["worker"]["array_reading_by_source_builder"] is False
    assert binding["worker"]["solver_invocation_by_source_builder"] is False
    assert binding["typed_identity_policy"]["identity_key"] == "(Zone,Idp)"
    assert binding["native_quality_policy"]["native_particles"] == 179208
    assert binding["native_quality_policy"]["native_fluid_particles"] == 67500
    assert binding["native_quality_policy"]["mass_rescale"] is False
    root140 = Path(manifest["root140_launch_request"]["path"])
    assert root140.is_file() and digest(root140) == ROOT140_REQUEST_SHA
    profile = manifest["root142_home_floor_profile"]
    assert profile["profile"] == "root_home_floor_no_legacy_dataset_walk_v1"
    assert profile["root_cpu_only"] is True
    assert profile["runtime_core_unchanged"] is True
    assert profile["actual_check_count"] == 14
    assert profile["source_enabling_only"] is True
    guards = manifest["resource_guards"]
    assert guards["home_min_free_bytes"] == 536870912000
    assert guards["nvme_stage_limit_bytes"] == 25769803776
    assert guards["nvme_worker_floor_bytes"] == 107374182400
    assert guards["shared_cpu_thread_cap"] == 64
    assert guards["conversion_concurrency_cap"] == 2
    assert guards["parent_gpu_seconds"] == 1843200
    assert guards["parent_cpu_core_seconds"] == 13824000
    assert guards["qualification_attempts"] == 1024
    assert guards["production_attempts"] == 720
    assert guards["deadline_utc"] == "2026-10-14T07:23:48+00:00"

    owner_path = HERE / "owners" / f"{CASE}.json"
    request_path = HERE / "requests" / f"{CASE}.json"
    owner = load(owner_path)
    request = load(request_path)
    assert digest(owner_path) == manifest["owner_paths"][0]["sha256"]
    assert digest(request_path) == manifest["request_paths"][0]["sha256"]
    assert owner["case_id"] == request["case_id"] == CASE
    assert owner["fresh_id"] == request["fresh_id"] == "fresh070"
    assert owner["root140_launch_request"] == manifest["root140_launch_request"]
    assert owner["root142_home_floor_profile"] == profile
    assert request["root140_launch_request"] == manifest["root140_launch_request"]
    assert request["root142_home_floor_profile"] == profile
    assert owner["parent_initial_qa"]["sha256"] == QA_SHA
    assert owner["prepared_input"]["generated_xml"]["sha256"] == "1162322010c42b9a084d76db0e20de571111cb009eb3afb699f2ee4c17d37406"
    assert owner["prepared_input"]["initial_bi4"]["sha256"] == "c9c3fb8315dad402f77dd015539be376c3df68f332f3ed6d03e6c174e4c57d80"
    assert request["launch_allowed"] is False and request["execution_allowed"] is False
    assert request["launch_owner"] == "root"
    assert request["production_approval"] == "none"
    assert request["q_n"] == "not_granted"
    assert request["numerical_precision_status"] == "not_accepted"
    assert request["independent_case_count_increment"] == 0
    assert request["native_full836_binding"]["receipt"] == owner["native_full836"]["receipt"]
    assert request["typed_identity_policy"] == binding["typed_identity_policy"]
    assert request["native_quality_policy"] == binding["native_quality_policy"]
    assert request["resource_guards"] == guards
    check_native(owner, request)
    check_command(request, owner)
    check_input_closure(request)
    future = request["future_typed_outputs"]
    assert future["typed_execution_receipt"]["sha256"] is None
    assert future["conversion_report"]["sha256"] is None
    assert future["trajectory_h5"]["sha256"] is None
    assert future["partvtk_validation"]["sha256"] is None
    assert future["visual_decision"] is None and future["full_visual_evidence"] is None

    payloads = [path for path in HERE.rglob("*") if path.is_file() and path.suffix.lower() in ARRAY_SUFFIXES]
    assert not payloads, payloads
    print("fresh070 static contract: PASS (AY0540 Root140 native binding, root-owned disabled NVMe request, Root142 profile, no raw payloads)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
