#!/usr/bin/env python3
"""Build the launch-disabled ROOT204 F1 native selected-observer request.

Only the existing F1 observer/proof/request/receipt/XML/RunPARTs sidecars are
read here.  No Part file, H5, VTK, or native directory is opened.  The
selected native paths are deferred to a future parent guard, which must hash
and stat them before and after the child observer.  This request deliberately
uses five already-completed S1/S2 producer cases and five sparse selected
frames per case; it is not a new solver and it does not repeat the old nine
frame reports in full.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any

import stage2_f1_com_observer_calibration_request_v1 as root202


REQUEST_SCHEMA = "ds02.request.v1"
MANIFEST_SCHEMA = "ds02.stage2.f1.native-selected-observer-manifest.v1"
VARIANT_SCHEMA = "ds02.stage2.f1.native-selected-observer-request.v1"
REPO = Path(__file__).resolve().parents[5]
PRIMARY = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
WORKER = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f1_native_selected_observer_v1.py"
BUILDER = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f1_native_selected_observer_request_v1.py"
BASE_OBSERVER = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_native_physical_observer_v2.py"
ROOT202_BUILDER = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f1_com_observer_calibration_request_v1.py"
ROOT202_CONTRACT = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f1_com_observer_calibration_contract_v1.json"
CONTRACT = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f1_native_selected_observer_contract_v1.json"
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
BI4_WRITER_CPP = Path("/home/jade/Projects/DualSPHysics/src/source/JPartDataBi4.cpp")
BI4_WRITER_H = Path("/home/jade/Projects/DualSPHysics/src/source/JPartDataBi4.h")
DECODER_SOURCE_FALLBACK = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/scripts/native/bi4_dump.cpp")

# The first five entries are the completed canonical S1/S2 source cases.  The
# owner-centred dp=.005/.0025 observer products are intentionally not repeated
# by this small header calibration request.
CASE_SPECS = tuple(root202.CASE_SPECS[:5])
SELECTED_OBSERVATION_INDICES = (0, 2, 4, 6, 8)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def regular(path: Path, label: str, *, allow_json_payload_name: bool = True) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} is not a regular file: {path}")
    if path.suffix.lower() in {".bi4", ".h5", ".hdf5", ".vtk", ".vtu"}:
        raise ValueError(f"{label} unexpectedly binds a native/H5/VTK payload: {path}")
    return path


def record(path: Path, label: str) -> dict[str, Any]:
    path = regular(path, label)
    stat = path.stat()
    return {
        "path": str(path),
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "ctime_ns": stat.st_ctime_ns,
        "device": stat.st_dev,
        "inode": stat.st_ino,
        "sha256": sha256_file(path),
    }


def read_json(path: Path, label: str) -> dict[str, Any]:
    path = regular(path, label)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} is not an object")
    return value


def write_exclusive(path: Path, value: Any) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if fd >= 0:
            os.close(fd)


def _declared_record(path: Path, label: str, declared: dict[str, Any] | None = None) -> dict[str, Any]:
    result = record(path, label)
    if declared:
        for key in ("bytes", "mtime_ns", "sha256"):
            if key in declared and declared[key] != result[key]:
                raise ValueError(f"{label} {key} differs from producer record")
    return result


def _path_from_record(value: Any, label: str) -> Path:
    if isinstance(value, str):
        return regular(Path(value), label)
    if isinstance(value, dict) and isinstance(value.get("path"), str):
        return regular(Path(value["path"]), label)
    raise ValueError(f"{label} has no path")


def _source_record_from_report(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        raise ValueError(f"{label} has no declared path")
    return _declared_record(Path(value["path"]), label, value)


def _selected_frames(report: dict[str, Any], label: str) -> tuple[list[int], list[float], int, float, int, list[dict[str, Any]]]:
    observations = report.get("observations")
    if not isinstance(observations, list) or len(observations) < len(SELECTED_OBSERVATION_INDICES):
        raise ValueError(f"{label} has too few producer observations")
    selected = [observations[index] for index in SELECTED_OBSERVATION_INDICES]
    frames: list[int] = []
    times: list[float] = []
    for row in selected:
        if not isinstance(row, dict):
            raise ValueError(f"{label} has a malformed observation")
        frame = int(row["frame"])
        time = row.get("time", {})
        decoded = float(time["decoded_s"])
        if frame < 0 or not (decoded >= 0.0):
            raise ValueError(f"{label} has an invalid selected frame/time")
        frames.append(frame)
        times.append(decoded)
    scope = report.get("scope", {})
    window = report.get("time_window", {})
    frame_count = int(scope["runparts_frame_count"])
    final_time = float(window["last_saved_time_s"])
    source_records = report.get("source", {}).get("selected_part_records", [])
    record_by_frame: dict[int, dict[str, Any]] = {}
    for item in source_records:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            continue
        stem = Path(item["path"]).stem
        if stem.startswith("Part_"):
            try:
                record_by_frame[int(stem.split("_", 1)[1])] = item
            except ValueError:
                continue
    selected_bytes = 0
    for frame in frames:
        item = record_by_frame.get(frame)
        if not isinstance(item, dict) or not isinstance(item.get("bytes"), int):
            raise ValueError(f"{label} lacks a stat record for selected native frame {frame}")
        selected_bytes += int(item["bytes"])
    return frames, times, frame_count, final_time, selected_bytes, selected


def _axis_source_record_paths(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    paths: list[tuple[Path, str]] = [
        (ROOT202_CONTRACT, "ROOT202 coordinate contract"),
        (CONTRACT, "ROOT204 native selected observer contract"),
        (ROOT202_BUILDER, "ROOT202 source binding builder"),
        (WORKER, "ROOT204 worker"),
        (BUILDER, "ROOT204 request builder"),
        (BASE_OBSERVER, "official typed-range/decoder adapter source"),
        (BI4_WRITER_CPP, "official BI4 writer source"),
        (BI4_WRITER_H, "official BI4 writer header"),
    ]
    for case in cases:
        paths.append((Path(case["generated_xml"]), f"{case['label']} generated XML"))
        for key in ("solver_request", "solver_receipt"):
            value = case.get(key)
            if isinstance(value, str):
                paths.append((Path(value), f"{case['label']} {key}"))
        decoder_source = case.get("decoder_source")
        if isinstance(decoder_source, str):
            paths.append((Path(decoder_source), f"{case['label']} decoder source"))
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path, label in paths:
        path = regular(path, label)
        if str(path) not in seen:
            seen.add(str(path))
            output.append(record(path, label))
    return output


def build_manifest() -> tuple[dict[str, Any], list[Path]]:
    cases: list[dict[str, Any]] = []
    source_inputs: list[Path] = [ROOT202_CONTRACT, CONTRACT, ROOT202_BUILDER, WORKER, BUILDER, BASE_OBSERVER, BI4_WRITER_CPP, BI4_WRITER_H]
    for spec in CASE_SPECS:
        bound_case, report, case_inputs = root202.make_observer_binding(spec)
        source = report["source"]
        runparts = _source_record_from_report(source["runparts"], f"{spec['label']} RunPARTs")
        generated_xml = _source_record_from_report(source["generated_xml"], f"{spec['label']} generated XML")
        decoder = _source_record_from_report(source["decoder"], f"{spec['label']} decoder")
        decoder_source_value = source.get("decoder_interface", {}).get("source")
        if not isinstance(decoder_source_value, dict):
            decoder_source = _declared_record(DECODER_SOURCE_FALLBACK, f"{spec['label']} decoder source fallback")
        else:
            decoder_source = _source_record_from_report(decoder_source_value, f"{spec['label']} decoder source")
        frames, times, frame_count, final_time, selected_native_read_bytes, selected_observations = _selected_frames(report, spec["label"])
        solver_request = bound_case.get("solver_evidence", {}).get("request", {}).get("path")
        solver_receipt = bound_case.get("solver_evidence", {}).get("receipt", {}).get("path")
        case = {
            "label": spec["label"],
            "identity": {
                "family_id": "F1",
                "sentinel_id": spec["sentinel_id"],
                "physical_case_id": spec["physical_case_id"],
                "grid": spec["grid"],
            },
            "raw_root": str(Path(source["raw_root"]).expanduser().resolve()),
            "runparts": runparts["path"],
            "generated_xml": generated_xml["path"],
            "decoder": decoder["path"],
            "decoder_source": decoder_source["path"],
            "expected_frame_count": frame_count,
            "expected_final_time_s": final_time,
            "selected_native_read_bytes": selected_native_read_bytes,
            "selected_frames": frames,
            "query_times": times,
            "scratch_root": "{attempt_root}/scratch/native_f1_selected/" + spec["label"],
            "output_name": spec["label"].lower() + ".json",
            "selected_native_frame_paths": [
                str((Path(source["raw_root"]).expanduser().resolve() / f"Part_{frame:04d}.bi4"))
                for frame in frames
            ],
            "selected_native_frame_metadata": [
                {
                    "frame": int(item["frame"]),
                    "time_s": float(item["time"]["decoded_s"]),
                    "producer_field_digest_sha256": item.get("raw_field_digest_sha256", "UNKNOWN_UNBOUND_NATIVE_BYTES"),
                }
                for item in selected_observations
            ],
            "solver_request": solver_request,
            "solver_receipt": solver_receipt,
            "solver_evidence": bound_case.get("solver_evidence", {}),
            "old_observer_provenance": bound_case["observer"],
        }
        cases.append(case)
        source_inputs.extend(case_inputs)
        source_inputs.extend([Path(runparts["path"]), Path(generated_xml["path"]), Path(decoder["path"]), Path(decoder_source["path"])])
        if solver_request:
            source_inputs.append(Path(solver_request))
        if solver_receipt:
            source_inputs.append(Path(solver_receipt))

    unique: list[Path] = []
    seen: set[str] = set()
    for path in source_inputs:
        path = regular(path, "ROOT204 source input")
        if str(path) not in seen:
            seen.add(str(path))
            unique.append(path)
    axis_records = _axis_source_record_paths(cases)
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "status": "PREPARED_ROOT204_SOURCE_BOUND_METADATA_ONLY",
        "preparation_scope": {
            "production_native_payload_read_by_builder": False,
            "hdf5_read": False,
            "vtk_read": False,
            "solver_launch": False,
            "selected_case_count": len(cases),
            "selected_frames_per_case": len(SELECTED_OBSERVATION_INDICES),
        },
        "axis_authority": {
            "coordinate_contract": {
                "frame": "world_cartesian_right_handed",
                "axis_labels": ["x", "y", "z"],
                "position_unit": "m",
                "velocity_unit": "m/s",
                "mass_unit": "kg",
                "time_unit": "s",
                "rotation_to_world": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
            },
            "source_records": axis_records,
            "gravity_m_s2": [0.0, 0.0, -9.81],
            "status_reason": "writer/parser/XML/gravity/control records are bound; producer axis-orientation metadata is absent and must remain UNKNOWN",
            "producer_axis_orientation_metadata": "REQUIRED_NOT_PROVIDED_BY_EXISTING_F1_PRODUCERS",
            "axis_calibration": "UNKNOWN",
        },
        "cases": cases,
        "source_inputs": [record(path, "ROOT204 manifest input") for path in unique],
        "native_deferred_policy": {
            "parent_after_reservation_first_sha_and_stat": True,
            "parent_after_child_post_sha_and_stat": True,
            "selected_frame_paths_only": True,
            "full_native_tree_hash": "NOT_REQUESTED",
            "source_replacement_or_stat_change": "FAIL",
        },
        "mass_semantics": {
            "MassFluid": "required native BI4 metadata",
            "MassBound": "reported when decoder exposes it; otherwise UNKNOWN",
            "Dp": "required native BI4 metadata",
            "Idp": "decoded native identity array/digest, not a scalar header",
            "XML_mass_fallback": "FORBIDDEN",
            "continuum_mass": "UNKNOWN_NOT_DERIVED_FROM_PARTICLE_SUM",
            "rigid_body_mass_inertia": "UNKNOWN_NOT_INFERRED_FROM_PARTICLE_SAMPLE",
        },
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    return manifest, unique


def build_request(manifest_path: Path, input_paths: list[Path], *, case_id: str, attempt_id: str) -> dict[str, Any]:
    unique_inputs: list[Path] = []
    seen_inputs: set[str] = set()
    for path in input_paths:
        path = path.expanduser().resolve()
        if str(path) not in seen_inputs:
            seen_inputs.add(str(path))
            unique_inputs.append(path)
    input_records = [record(path, "ROOT204 request input") for path in unique_inputs]
    manifest_value = json.loads(manifest_path.read_text(encoding="utf-8"))
    selected_count = sum(len(case["selected_frames"]) for case in manifest_value["cases"])
    command = [
        str(PYTHON),
        str(WORKER),
        "--manifest", str(manifest_path.expanduser().resolve()),
        "--attempt-root", "{attempt_root}",
        "--output", "{attempt_root}/observer/f1_native_selected_observer_v1.json",
    ]
    return {
        "schema": REQUEST_SCHEMA,
        "variant_schema": VARIANT_SCHEMA,
        "status": "READY_FOR_PARENT_GUARD_SOURCE_BOUND_NATIVE_SELECTED_OBSERVER",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 1,
        "omp_threads": 1,
        "family_id": "F1",
        "sentinel_id": "F1-S1+F1-S2",
        "physical_case_id": "F1_NATIVE_HEADER_SELECTED_DIAGNOSTIC_V1",
        "case_id": case_id,
        "attempt_id": attempt_id,
        "cwd": str(REPO),
        "worktree_root": str(REPO),
        "command": command,
        "input_files": [item["path"] for item in input_records],
        "input_sha256": {item["path"]: item["sha256"] for item in input_records},
        "manifest": record(manifest_path, "ROOT204 manifest"),
        "deferred_input_files": [path for case in manifest_value["cases"] for path in case["selected_native_frame_paths"]],
        "deferred_input_policy": {
            "parent_after_reservation_first_sha_and_stat": True,
            "parent_after_child_post_sha_and_stat": True,
            "source_replace_or_stat_change": "FAIL",
            "full_native_tree_read": False,
            "selected_frame_count": selected_count,
        },
        "max_wall_seconds": 1800,
        "estimated_native_read_bytes": sum(int(case["selected_native_read_bytes"]) for case in manifest_value["cases"]),
        "estimated_hdf5_read_bytes": 0,
        "estimated_storage_bytes": 128 * 1024 * 1024,
        "estimated_peak_memory_bytes": 2 * 1024 * 1024 * 1024,
        "output": {"path": "{attempt_root}/observer/f1_native_selected_observer_v1.json", "atomic": True, "refuse_overwrite": True},
        "axis_authority": {
            "manifest": str(manifest_path.expanduser().resolve()),
            "source_writer_parser_xml_gravity_control_bound": True,
            "producer_axis_orientation_metadata": "MUST_BE_PRESENT_FOR_CALIBRATION; currently UNKNOWN",
            "no_axis_self_assertion": True,
        },
        "source_binding": {
            "observer": "ROOT204 native MassFluid/MassBound/Dp/Idp selected-frame worker",
            "weighted_observables": "native MassFluid only; fixed/moving excluded",
            "time": "actual RunPARTs and decoder TimeStep; no interpolation",
            "old_observer_reports": "provenance sidecars only; never overwritten or treated as native-header evidence",
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
        "launch_disabled": True,
        "execution_allowed": False,
        "solver_started": False,
        "native_payload_read": False,
        "hdf5_read": False,
        "resource_guard": {"gpu": "none", "parent_guard": "required before deferred BI4 reads", "solver_launch": "forbidden"},
    }


def self_test() -> None:
    completed = subprocess.run(
        [str(PYTHON), "-B", str(WORKER), "--self-test"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        raise AssertionError(f"ROOT204 worker self-test failed: {completed.stdout} {completed.stderr}")
    if '"status": "PASS"' not in completed.stdout:
        raise AssertionError(f"ROOT204 worker self-test did not report PASS: {completed.stdout}")
    manifest, inputs = build_manifest()
    if any(Path(item["path"]).suffix.lower() in {".bi4", ".h5", ".hdf5", ".vtk", ".vtu"} for item in manifest["source_inputs"]):
        raise AssertionError("ROOT204 manifest unexpectedly contains a payload")
    if any(path.suffix.lower() in {".bi4", ".h5", ".hdf5", ".vtk", ".vtu"} for path in inputs):
        raise AssertionError("ROOT204 input closure unexpectedly contains a payload")
    print(json.dumps({"status": "PASS", "cases": len(manifest["cases"]), "inputs": len(inputs), "payload_reads": False}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest-output", type=Path)
    parser.add_argument("--request-output", type=Path)
    parser.add_argument("--case-id", default="F1_S1_S2_NATIVE_HEADER_SELECTED_ROOT204")
    parser.add_argument("--attempt-id", default="f1-s1-s2-native-header-selected-root204-001")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.manifest_output is None or args.request_output is None:
        parser.error("--manifest-output and --request-output are required unless --self-test is used")
    manifest, inputs = build_manifest()
    write_exclusive(args.manifest_output, manifest)
    request = build_request(args.manifest_output, inputs + [args.manifest_output], case_id=args.case_id, attempt_id=args.attempt_id)
    write_exclusive(args.request_output, request)
    print(json.dumps({"status": "PREPARED", "manifest": str(args.manifest_output.resolve()), "request": str(args.request_output.resolve()), "cases": len(manifest["cases"]), "payload_reads": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
