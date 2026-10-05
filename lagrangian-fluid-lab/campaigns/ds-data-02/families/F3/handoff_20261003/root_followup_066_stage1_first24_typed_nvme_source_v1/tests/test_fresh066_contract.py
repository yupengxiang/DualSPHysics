#!/usr/bin/env python3
"""Static source-only contract test for fresh066.

The test hashes only small source/metadata files.  BI4, CSV, H5, HDF5, NPY,
and NPZ payloads are validated through their registered receipt digests without
opening them.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
ARRAY_SUFFIXES = {".bi4", ".csv", ".h5", ".hdf5", ".npy", ".npz"}
OPAQUE_BASENAMES = {"python", "bi4_dump", "PartVTK_linux64"}
CASES = (
    "F3_STAGE1_DP006_P1000_AY0270",
    "F3_STAGE1_DP006_P1000_AY0290",
    "F3_STAGE1_DP006_P1000_AY0300",
    "F3_STAGE1_DP006_P1000_AY0340",
    "F3_STAGE1_DP006_P1000_AY0640",
)


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


def check_command(request: dict, owner: dict) -> None:
    command = request["command"]
    assert command[0].endswith("/.venv/bin/python")
    assert command[1].endswith("/scripts/ds_data02_nvme_convert_v1.py")
    assert "--staging-root" in command
    assert command[command.index("--staging-root") + 1] == "/tmp/ds02-nvme-conversion"
    assert command[command.index("--staging-limit-bytes") + 1] == "25769803776"
    assert command[command.index("--data-root") + 1] == owner["native_full836"]["data_root"]
    assert command[command.index("--generated-xml") + 1] == owner["prepared_input"]["generated_xml"]["path"]
    assert command[command.index("--solver-receipt") + 1] == owner["native_full836"]["receipt"]["path"]
    assert command[command.index("--gencase-receipt") + 1] == owner["genuine_gencase_receipt"]["path"]
    assert command[command.index("--owner-metadata") + 1] == str(
        HERE / "owners" / f'{request["case_id"]}.json'
    )
    assert "-gpu:0" not in command


def main() -> int:
    manifest = load(HERE / "manifest.json")
    binding = load(HERE / "source-binding.json")
    assert manifest["fresh_id"] == binding["fresh_id"] == "fresh066"
    assert manifest["case_ids"] == list(CASES)
    assert manifest["case_count"] == len(CASES)
    assert manifest["source_only"] is True
    assert manifest["all_native_full836_completed_zero"] is True
    assert manifest["all_typed_requests_disabled"] is True
    assert manifest["production_scope_approval"] is False
    assert manifest["independent_case_count_increment"] == 0
    assert manifest["future_typed_receipt_sha256"] is None
    assert manifest["future_h5_sha256"] is None
    assert binding["worker"]["array_reading_by_source_builder"] is False
    assert binding["worker"]["solver_invocation_by_source_builder"] is False

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
        assert owner["source_only"] is True
        assert owner["status"].startswith("disabled_source_only")
        native = owner["native_full836"]
        assert native["status"] == "completed"
        assert native["returncode"] == 0
        assert native["expected_saved_frames"] == 836
        assert Path(native["receipt"]["path"]).is_file()
        assert Path(owner["genuine_gencase_receipt"]["path"]).is_file()
        assert Path(owner["parent_initial_qa"]["path"]).is_file()
        assert Path(owner["source_owner"]["path"]).is_file()
        assert owner["prepared_input"]["generated_xml"]["sha256"]
        assert owner["prepared_input"]["initial_bi4"]["sha256"]
        assert owner["canonical_condition"]["physical_case_id"] == owner["physical_case_id"]
        assert owner["canonical_condition"]["physical_condition_sha256"] == request["physical_condition_sha256"]
        assert request["native_full836_binding"]["receipt"] == native["receipt"]
        assert request["launch_allowed"] is False
        assert request["execution_allowed"] is False
        assert request["production_approval"] == "none"
        assert request["q_n"] == "not_granted"
        assert request["numerical_precision_status"] == "not_accepted"
        assert request["independent_case_count_increment"] == 0
        assert request["status"].startswith("disabled_source_only")
        future = request["future_typed_outputs"]
        assert future["typed_execution_receipt"]["sha256"] is None
        assert future["conversion_report"]["sha256"] is None
        assert future["trajectory_h5"]["sha256"] is None
        assert future["partvtk_validation"]["sha256"] is None
        check_command(request, owner)
        check_input_closure(request)

    payloads = [
        path
        for path in HERE.rglob("*")
        if path.is_file() and path.suffix.lower() in ARRAY_SUFFIXES
    ]
    assert not payloads, f"raw array-bearing payload was copied: {payloads}"
    print("fresh066 static contract: PASS (5 actual native full836 bindings, 5 disabled NVMe requests, no raw payloads)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
