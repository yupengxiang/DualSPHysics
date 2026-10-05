#!/usr/bin/env python3
"""Metadata-only contract test for the fresh069 F3 typed-NVMe handoff.

The test reads JSON/XML/source metadata and hashes only small source files. It
never opens BI4, CSV, H5, HDF5, NPY, or NPZ payloads; their registered receipt
hashes remain opaque inputs for the future strict worker.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
DATA_F3 = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3")
ARRAY_SUFFIXES = {".bi4", ".csv", ".h5", ".hdf5", ".npy", ".npz"}
OPAQUE_BASENAMES = {"python", "bi4_dump", "PartVTK_linux64"}
CASES = (
    "F3_STAGE1_DP006_P1000_AY0360",
    "F3_STAGE1_DP006_P1000_AY0370",
    "F3_STAGE1_DP006_P1000_AY0410",
    "F3_STAGE1_DP006_P1000_AY0430",
    "F3_STAGE1_DP006_P1000_AY0440",
    "F3_STAGE1_DP006_P1000_AY0480",
    "F3_STAGE1_DP006_P1000_AY0520",
)
EXPECTED_RECEIPT_SHA = {
    "AY0360": "bb2ef366bff712639db09b2172dc504125c1108d75db767fdb92c799f2225bb6",
    "AY0370": "744676718a1fef8a9d1e8d528748ef0e5b5e7cdea8c8294561bd48471b64358f",
    "AY0410": "79a6e70182984c0708824b1e15ce4e3a2cbd5b08a95349df4c4db8c02b6943d9",
    "AY0430": "82730035c1b2cf11dca69dd5ecf056309f76d91c27e31d17de14636caa09ff81",
    "AY0440": "5c3e6901d8ba5f785f00694e5fa9249d02dda6d79231b0d0f6eb7136396225fb",
    "AY0480": "215aa80db3d66ac96c245c87c05018fc82105f597297dcd507de59a038d1e192",
    "AY0520": "1e066ebced91f565b54c1085026d498a119ec6a2e085eb8f4ca900efba6751f9",
}
EXPECTED_CONDITIONS = {
    "AY0360": "e1779de1d681fcb4441bd24dafdabf47d0177c6932d57e59be46203f9bafe747",
    "AY0370": "b80a00f01937b4eb1e15ed7beea7ee9948bcff6f49eeb867a77e27b51164fa68",
    "AY0410": "1b0d5a5251addf08c2258bee955d32f16f02b2ce6fbdf6be7c86ee4b93cfa1c1",
    "AY0430": "f861a003d6da2f768a2415d5e667758f0ddefb45d3d67d09c180e138a9bafc0e",
    "AY0440": "fe318413eb5f06b5cb66f28d48e1a44f7421034887d643b5a916d3041d3b07af",
    "AY0480": "f1dc6721f15a0d5cf61f7a468a3d51758e0f7c04732b5da6612a0431da3f632b",
    "AY0520": "93b6f9dddeaef47e95da97d884f10a4faadd8cdd3ff0184b0e9cb49f3e117263",
}


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
    assert set(files) == set(hashes), "request input/hash closure is incomplete"
    for raw in files:
        path = Path(raw)
        assert path.is_file(), f"missing request input: {path}"
        if path.suffix.lower() in ARRAY_SUFFIXES or path.name in OPAQUE_BASENAMES:
            assert isinstance(hashes[raw], str) and len(hashes[raw]) == 64
            continue
        assert digest(path) == hashes[raw], f"small source hash mismatch: {path}"


def check_native(owner: dict, case: str) -> None:
    suffix = case.rsplit("_", 1)[-1]
    native = owner["native_full836"]
    receipt_path = Path(native["receipt"]["path"])
    assert receipt_path.is_file()
    assert digest(receipt_path) == EXPECTED_RECEIPT_SHA[suffix]
    assert native["receipt"]["sha256"] == EXPECTED_RECEIPT_SHA[suffix]
    assert native["status"] == "completed"
    assert native["returncode"] == 0
    assert native["expected_saved_frames"] == 836
    actual = load(receipt_path)
    actual_request = actual["request"]
    assert actual["status"] == "completed"
    assert actual["returncode"] == 0
    assert actual_request["case_id"] == case
    assert actual_request["physical_condition_sha256"] == EXPECTED_CONDITIONS[suffix]
    assert actual_request["expected_saved_frames"] == 836
    assert actual_request["initial_native_reference"]["actual_3d"] is True
    assert actual_request["initial_native_reference"]["native_particles"] == 179208
    assert actual_request["initial_native_reference"]["native_fluid"] == 67500
    assert actual_request["initial_native_reference"]["native_fixed"] == 111708
    assert actual_request["initial_native_reference"]["mass_normalization"] == "none"
    command = actual["command"]
    assert "-mdbc_noslip:1" in command
    assert "-tmax:8.35" in command
    assert "-tout:0.01" in command
    assert any("DualSPHysics5.4_linux64" in str(item) for item in command)
    assert any(str(item).startswith("-gpu:") for item in command)


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
    assert command[command.index("--owner-metadata") + 1] == str(HERE / "owners" / f'{request["case_id"]}.json')
    assert not any(str(item).startswith("-gpu:") for item in command)
    assert "DualSPHysics5.4_linux64" not in command


def main() -> int:
    manifest = load(HERE / "manifest.json")
    binding = load(HERE / "source-binding.json")
    assert manifest["fresh_id"] == binding["fresh_id"] == "fresh069"
    assert manifest["case_ids"] == list(CASES)
    assert manifest["case_count"] == len(CASES) == 7
    assert manifest["source_only"] is True
    assert manifest["all_native_full836_completed_zero"] is True
    assert manifest["all_typed_requests_disabled"] is True
    assert manifest["production_scope_approval"] is False
    assert manifest["independent_case_count_increment"] == 0
    assert manifest["future_typed_receipt_sha256"] is None
    assert manifest["future_h5_sha256"] is None
    assert binding["worker"]["array_reading_by_source_builder"] is False
    assert binding["worker"]["solver_invocation_by_source_builder"] is False
    assert binding["typed_identity_policy"]["identity_key"] == "(Zone,Idp)"
    assert binding["typed_identity_policy"]["preserve_native_zone_id"] is True
    assert binding["typed_identity_policy"]["preserve_native_idp"] is True
    assert binding["native_quality_policy"]["native_particles"] == 179208
    assert binding["native_quality_policy"]["native_fluid_particles"] == 67500
    assert binding["native_quality_policy"]["mass_rescale"] is False
    guards = manifest["resource_guards"]
    assert guards["home_min_free_bytes"] == 536870912000
    assert guards["home_min_free_gib"] == 500
    assert guards["nvme_stage_limit_bytes"] == 25769803776
    assert guards["nvme_worker_floor_bytes"] == 107374182400
    assert guards["shared_cpu_thread_cap"] == 64
    assert guards["conversion_concurrency_cap"] == 2
    assert guards["parent_gpu_seconds"] == 1843200
    assert guards["parent_cpu_core_seconds"] == 13824000
    assert guards["qualification_attempts"] == 1024
    assert guards["production_attempts"] == 720
    assert guards["deadline_utc"] == "2026-10-14T07:23:48+00:00"
    assert guards["live_conversion_protection"]["must_not_touch_existing_p01_p03_conversions"] is True

    owner_paths = {Path(row["path"]) for row in manifest["owner_paths"]}
    request_paths = {Path(row["path"]) for row in manifest["request_paths"]}
    assert owner_paths == {HERE / "owners" / f"{case}.json" for case in CASES}
    assert request_paths == {HERE / "requests" / f"{case}.json" for case in CASES}

    for case in CASES:
        owner_path = HERE / "owners" / f"{case}.json"
        request_path = HERE / "requests" / f"{case}.json"
        owner = load(owner_path)
        request = load(request_path)
        assert digest(owner_path) == next(row["sha256"] for row in manifest["owner_paths"] if row["path"] == str(owner_path))
        assert digest(request_path) == next(row["sha256"] for row in manifest["request_paths"] if row["path"] == str(request_path))
        assert owner["case_id"] == request["case_id"] == case
        assert owner["fresh_id"] == request["fresh_id"] == "fresh069"
        assert owner["source_only"] is True
        assert owner["status"].startswith("disabled_source_only")
        assert owner["typed_identity_policy"] == binding["typed_identity_policy"]
        assert owner["resource_guards"] == guards
        assert owner["native_quality_policy"] == binding["native_quality_policy"]
        check_native(owner, case)
        assert Path(owner["genuine_gencase_receipt"]["path"]).is_file()
        assert Path(owner["parent_initial_qa"]["path"]).is_file()
        assert owner["parent_initial_qa"]["sha256"] == "7ff19bd2db1b731071ec0eeaa8dfe43bbb0cc27ecc5c2dc9d1bb8c0cb5f60349"
        assert Path(owner["source_owner"]["path"]).is_file()
        assert owner["prepared_input"]["generated_xml"]["sha256"] == "1162322010c42b9a084d76db0e20de571111cb009eb3afb699f2ee4c17d37406"
        assert owner["prepared_input"]["initial_bi4"]["sha256"] == "c9c3fb8315dad402f77dd015539be376c3df68f332f3ed6d03e6c174e4c57d80"
        assert owner["canonical_condition"]["physical_case_id"] == owner["physical_case_id"]
        assert owner["canonical_condition"]["physical_condition_sha256"] == request["physical_condition_sha256"]
        assert request["native_full836_binding"]["receipt"] == owner["native_full836"]["receipt"]
        assert request["root134_enabling_manifest"] == owner["root134_enabling_manifest"]
        assert request["launch_allowed"] is False
        assert request["execution_allowed"] is False
        assert request["production_approval"] == "none"
        assert request["q_n"] == "not_granted"
        assert request["numerical_precision_status"] == "not_accepted"
        assert request["independent_case_count_increment"] == 0
        assert request["status"].startswith("disabled_source_only")
        assert request["typed_identity_policy"] == binding["typed_identity_policy"]
        assert request["resource_guards"] == guards
        future = request["future_typed_outputs"]
        assert future["typed_execution_receipt"]["sha256"] is None
        assert future["conversion_report"]["sha256"] is None
        assert future["trajectory_h5"]["sha256"] is None
        assert future["partvtk_validation"]["sha256"] is None
        assert future["visual_decision"] is None
        assert future["full_visual_evidence"] is None
        check_command(request, owner)
        check_input_closure(request)

    payloads = [
        path
        for path in HERE.rglob("*")
        if path.is_file() and path.suffix.lower() in ARRAY_SUFFIXES
    ]
    assert not payloads, f"raw array-bearing payload was copied: {payloads}"
    print("fresh069 static contract: PASS (7 actual Root134 native full836 bindings, 7 disabled NVMe requests, no raw payloads)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
