#!/usr/bin/env python3
"""Static validator for F4 fresh103; never opens deferred scientific payloads."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = {".bi4", ".h5", ".vtk", ".vtu", ".vtp", ".csv", ".dat"}
HEX = set("0123456789abcdef")

def load(path: Path):
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"metadata object required: {path}")
    return value

def digest(path: Path) -> str:
    if path.suffix.lower() in RAW:
        raise AssertionError(f"validator would hash scientific payload: {path}")
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def sha_ok(value):
    return isinstance(value, str) and len(value) == 64 and set(value.lower()) <= HEX

def main() -> None:
    idx = load(ROOT / "requests/index.json")
    assert idx["case_count"] == 24 and idx["request_count"] == 72
    assert idx["all_disabled"] is True and idx["launch_allowed"] is False
    rows = idx["rows"]
    assert len(rows) == 72 and len({(r["kind"], r["case_id"]) for r in rows}) == 72
    case_ids = {r["case_id"] for r in rows}
    assert len(case_ids) == 24
    kinds = {"gencase-basic-initial-qa", "full1201-native-root230", "native-frame0-partvtk-vz"}
    assert {r["kind"] for r in rows} == kinds
    bindings = {"basic": {}, "native": {}, "frame": {}}
    for row in rows:
        request_path = Path(row["path"])
        assert request_path.is_file() and digest(request_path) == row["sha256"]
        request = load(request_path)
        assert request["disabled"] and not request["launch"] and not request["launch_allowed"]
        assert request["execution_allowed"] is False and request["source_only"] is True
        assert request["jobs_started_by_source"] is False and request["arrays_read_by_source"] is False
        assert request["case_id"] == row["case_id"]
        for path_text, expected in request["input_sha256"].items():
            path = Path(path_text)
            assert path.is_file(), path
            assert path.suffix.lower() not in RAW, path
            assert sha_ok(expected) and digest(path) == expected, path
        assert all(value is None for value in request.get("deferred_input_sha256", {}).values())
        kind = row["kind"]
        if kind == "gencase-basic-initial-qa":
            bindings["basic"][row["case_id"]] = request
            assert request["cpu_task_kind"] == "audit"
            assert len(request["depends_on_attempts"]) == 1
            assert request["expected"]["total_particles_from_gencase"] is None
            assert request["expected"]["fluid_particles_from_gencase"] is None
            assert request["expected"]["generated_bi4_sha256"] is None
        elif kind == "full1201-native-root230":
            bindings["native"][row["case_id"]] = request
            assert request["kind"] == "gpu" and request["cpu_task_kind"] == "native_solver"
            assert len(request["depends_on_attempts"]) == 2
            assert request["expected"]["total_particles"] is None
            assert request["expected"]["fluid_particles"] is None
            assert request["expected"]["native_frame_count"] == 1201
            assert request["recipe"]["solver_options"] == ["-tmax:1.2", "-tout:0.001"]
            assert request["outputs"]["all_future_sha256"] is None
        else:
            bindings["frame"][row["case_id"]] = request
            assert request["cpu_task_kind"] == "audit"
            assert len(request["depends_on_attempts"]) == 1
            assert request["expected"]["actual_total_particles_from_basic_qa"] is None
            assert request["expected"]["raw_mk_type_observed"] is None
            assert request["expected"]["raw_velocity_observed"] is None
    for group in bindings.values():
        assert set(group) == case_ids
    for case in sorted(case_ids):
        basic_cmd = bindings["basic"][case]["command"]
        basic_binding = Path(basic_cmd[basic_cmd.index("--binding") + 1])
        b = load(basic_binding)
        assert b["expected"]["total_particles"] is None
        assert b["expected"]["fluid_particles"] is None
        assert b["execution_allowed"] is False and b["source_only"] is True
        native_cmd = bindings["native"][case]["command"]
        native_binding = ROOT / "bindings" / f"{case}.native-input-binding.json"
        nb = load(native_binding)
        assert nb["expected"]["total_particles"] is None
        assert nb["expected"]["fluid_particles"] is None
        assert nb["basic_qa_gate"]["pass"] is None
        frame_cmd = bindings["frame"][case]["command"]
        frame_binding = Path(frame_cmd[frame_cmd.index("--binding") + 1])
        fb = load(frame_binding)
        assert fb["native_solver_status"] == "WAIT"
        assert fb["cases"] and len(fb["cases"]) == 1
        assert fb["cases"][0]["actual_total_particles"] is None
        assert fb["cases"][0]["expected_velocity_by_mk"] is None
        assert fb["future_report_sha256"] is None
    # The source package must not smuggle a historical count into a future template.
    forbidden_historical_count = "832" + "33"
    for path in ROOT.rglob("*"):
        if path.is_file() and path.suffix.lower() in {".json", ".py", ".md"}:
            assert forbidden_historical_count not in path.read_text(encoding="utf-8"), path
    print("fresh103 source contract: PASS (24 cases, 72 disabled requests, null future counts/hashes, static input closure)")

if __name__ == "__main__":
    main()
