#!/usr/bin/env python3
"""Prepare the post-ROOT273 native-observer intake for the F1-S2 pair.

ROOT271 is a source-only pair request.  This module is deliberately a second
stage: it accepts the two *terminal* receipts and RunPARTs files produced by
the parent, derives frame IDs from those actual saved times, and emits a
launch-disabled observer request.  It never opens, stats, or hashes a BI4
file.  BI4 records are deferred to the parent's after-reservation snapshot
and enforcer, so a request made before ROOT273 finishes cannot accidentally
invent a source SHA or a frame count.

The registered queries are 0, 0.25, and 0.5 seconds.  For every query the
request retains the exact saved frame or both native frame IDs that bracket
the query.  The result is a diagnostic bracket; it is not an interpolation
instruction and it does not turn a bracket width into an error bound.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any, Iterable


SCHEMA = "ds02.stage2.f1-s2.root271-pair-native-intake.v1"
CONTRACT_SCHEMA = "ds02.stage2.f1-s2.root271-pair-native-intake-contract.v1"
STATUS_TEMPLATE = "TEMPLATE_WAITING_FOR_ROOT273_TERMINAL_RECEIPTS"
STATUS_READY = "SOURCE_PREPARED_PARENT_NATIVE_SNAPSHOT_REQUIRED"
REQUEST_SCHEMA = "ds02.request.v1"

QUERIES_S = (0.0, 0.25, 0.5)
MAX_METADATA_BYTES = 8 * 1024 * 1024
MAX_RUNPARTS_BYTES = 16 * 1024 * 1024
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")

HERE = Path(__file__).resolve()
REFERENCE = HERE.parent
PHYSICAL_OBSERVER = REFERENCE / "stage2_native_physical_observer_v2.py"
SELECTED_OBSERVER = REFERENCE / "stage2_f1_native_selected_observer_v1.py"
CONTRACT_PATH = REFERENCE / "stage2_f1_s2_root271_pair_native_intake_contract_v1.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _regular(path: Path, label: str, *, max_bytes: int = MAX_METADATA_BYTES) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular file: {path}")
    if path.stat().st_size > max_bytes:
        raise ValueError(f"{label} exceeds bounded metadata limit: {path}")
    return path


def _record(path: Path, label: str, *, max_bytes: int = MAX_METADATA_BYTES) -> dict[str, Any]:
    path = _regular(path, label, max_bytes=max_bytes)
    stat = path.stat()
    return {
        "path": str(path),
        "label": label,
        "bytes": stat.st_size,
        "sha256": _sha256(path),
        "stat": {
            "dev": stat.st_dev,
            "ino": stat.st_ino,
            "mtime_ns": stat.st_mtime_ns,
            "ctime_ns": stat.st_ctime_ns,
            "bytes": stat.st_size,
        },
        "stable_read": True,
        "payload_read_by_intake": False,
    }


def _load_json(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _regular(path, label)
    before = path.stat()
    value = json.loads(path.read_text(encoding="utf-8"))
    after = path.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
        after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns
    ):
        raise ValueError(f"{label} changed while being read: {path}")
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain a JSON object: {path}")
    return value, _record(path, label)


def _find_key(value: Any, names: Iterable[str]) -> Any:
    wanted = set(names)
    if isinstance(value, dict):
        for key in wanted:
            if key in value:
                return value[key]
        for child in value.values():
            result = _find_key(child, wanted)
            if result is not None:
                return result
    elif isinstance(value, list):
        for child in value:
            result = _find_key(child, wanted)
            if result is not None:
                return result
    return None


def _terminal_receipt(value: dict[str, Any], label: str) -> dict[str, Any]:
    status = _find_key(value, ("status",))
    returncode = _find_key(value, ("returncode", "return_code", "exit_code"))
    if isinstance(status, str):
        completed = status.lower() in {"completed", "completed_development_unknown", "success", "succeeded"} or "completed" in status.lower()
    else:
        completed = False
    if returncode is not None and returncode != 0:
        raise ValueError(f"{label} has nonzero returncode: {returncode}")
    if not completed or (returncode is not None and int(returncode) != 0):
        raise ValueError(f"{label} is not a terminal completed receipt: status={status!r}, returncode={returncode!r}")
    output_root = _find_key(value, ("output_root", "actual_output_root"))
    if not isinstance(output_root, str) or not output_root:
        raise ValueError(f"{label} has no output_root")
    return {"status": status, "returncode": returncode if returncode is not None else 0, "output_root": str(Path(output_root).expanduser().resolve())}


def parse_runparts(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Read only the small RunPARTs CSV and return contiguous native IDs."""
    path = _regular(path, "RunPARTs.csv", max_bytes=MAX_RUNPARTS_BYTES)
    before = path.stat()
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter=";")
        if not reader.fieldnames or "Part" not in reader.fieldnames or "TimeStep [s]" not in reader.fieldnames:
            raise ValueError("RunPARTs.csv must contain Part and TimeStep [s]")
        for raw in reader:
            token = str(raw.get("Part", "")).strip()
            if not token or token.startswith("#"):
                continue
            frame = int(token)
            time_s = float(str(raw.get("TimeStep [s]", "")).strip())
            if frame < 0 or not math.isfinite(time_s):
                raise ValueError("RunPARTs contains a nonfinite frame/time")
            rows.append({"frame": frame, "time_s": time_s})
    after = path.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
        after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns
    ):
        raise ValueError("RunPARTs changed while being read")
    rows.sort(key=lambda item: item["frame"])
    if not rows or [row["frame"] for row in rows] != list(range(len(rows))):
        raise ValueError("RunPARTs frame IDs must be contiguous from zero")
    if rows[0]["time_s"] != 0.0:
        raise ValueError("RunPARTs must begin at saved time zero")
    if any(cur["time_s"] < prev["time_s"] for prev, cur in zip(rows, rows[1:])):
        raise ValueError("RunPARTs saved times are not monotone")
    return rows, _record(path, "RunPARTs.csv", max_bytes=MAX_RUNPARTS_BYTES)


def query_bracket(rows: list[dict[str, Any]], query_s: float) -> dict[str, Any]:
    if not rows:
        raise ValueError("cannot bracket an empty RunPARTs table")
    if query_s < rows[0]["time_s"] or query_s > rows[-1]["time_s"]:
        return {
            "query_time_s": query_s,
            "status": "OUT_OF_RANGE",
            "lower_frame": None,
            "upper_frame": None,
            "lower_time_s": None,
            "upper_time_s": None,
            "bracket_width_s": None,
        }
    for index, row in enumerate(rows):
        if row["time_s"] == query_s:
            return {
                "query_time_s": query_s,
                "status": "EXACT",
                "lower_frame": row["frame"],
                "upper_frame": row["frame"],
                "lower_time_s": row["time_s"],
                "upper_time_s": row["time_s"],
                "bracket_width_s": 0.0,
            }
        if row["time_s"] > query_s:
            lower = rows[index - 1]
            return {
                "query_time_s": query_s,
                "status": "BRACKETED",
                "lower_frame": lower["frame"],
                "upper_frame": row["frame"],
                "lower_time_s": lower["time_s"],
                "upper_time_s": row["time_s"],
                "bracket_width_s": row["time_s"] - lower["time_s"],
            }
    raise AssertionError("bracket search did not return")


def _deferred_frame(raw_root: Path, frame: int) -> dict[str, Any]:
    path = raw_root / f"Part_{frame:04d}.bi4"
    return {
        "native_frame_id": frame,
        "path": str(path),
        "sha256": "PARENT_AFTER_RESERVATION_REQUIRED",
        "bytes": "UNKNOWN_UNTIL_PARENT_SNAPSHOT",
        "stat": "PARENT_PRE_DECODE_AND_POST_DECODE_FULL_STAT_REQUIRED",
        "payload_read_by_intake": False,
        "identity_semantics": "native Part ID from this member's RunPARTs.csv; never selected-array index",
    }


def _member(
    mode: str,
    receipt_path: Path,
    runparts_path: Path,
    raw_root: Path,
    proof_path: Path | None,
    pair_manifest_path: Path | None,
) -> dict[str, Any]:
    receipt, receipt_record = _load_json(receipt_path, f"{mode} terminal receipt")
    terminal = _terminal_receipt(receipt, f"{mode} terminal receipt")
    # A DualSPHysics solver tree places native frames at
    # ``<attempt>/solver_output/data``; the receipt's output_root is the
    # attempt root, two parents above this deferred raw root.
    resolved_raw_root = raw_root.expanduser().resolve()
    output_root = resolved_raw_root.parent.parent
    if terminal["output_root"] != str(output_root):
        raise ValueError(
            f"{mode} raw root is not under terminal receipt output_root: {raw_root} vs {terminal['output_root']}"
        )
    rows, runparts_record = parse_runparts(runparts_path)
    brackets = [query_bracket(rows, query) for query in QUERIES_S]
    selected: set[int] = {0, rows[-1]["frame"]}
    for bracket in brackets:
        if bracket["status"] in {"EXACT", "BRACKETED"}:
            selected.add(int(bracket["lower_frame"]))
            selected.add(int(bracket["upper_frame"]))
    selected_ids = sorted(selected)
    proof_record: dict[str, Any] | None = None
    proof_status = "NOT_BOUND"
    if proof_path is not None:
        proof, proof_record = _load_json(proof_path, f"{mode} terminal proof")
        proof_status = str(proof.get("status", proof.get("verification_status", "UNKNOWN")))
        if "failure" in proof_status.lower() or "failed" in proof_status.lower():
            raise ValueError(f"{mode} proof is a failure artifact, not a terminal success proof")
    return {
        "mode": mode,
        "terminal_status": terminal,
        "terminal_receipt": receipt_record,
        "terminal_proof": proof_record,
        "terminal_proof_status": proof_status,
        "runparts": runparts_record,
        "raw_root": str(resolved_raw_root),
        "runparts_first_time_s": rows[0]["time_s"],
        "runparts_last_time_s": rows[-1]["time_s"],
        "runparts_frame_count": len(rows),
        "query_brackets": brackets,
        "selected_native_frame_ids": selected_ids,
        "selected_native_frames": [_deferred_frame(resolved_raw_root, frame) for frame in selected_ids],
        "pair_manifest": _record(pair_manifest_path, f"{mode} ROOT271 pair manifest") if pair_manifest_path else None,
        "actual_time_policy": {
            "source": "this member's terminal RunPARTs.csv",
            "native_frame_ids": True,
            "selected_array_indices_are_not_native_ids": True,
            "interpolation": "FORBIDDEN",
            "extrapolation": "FORBIDDEN",
            "bracket_width_is_not_an_error_bound": True,
        },
    }


def _source_record(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        return {"path": str(path), "label": label, "status": "MISSING_UNTIL_PRIMARY_REBIND"}
    return _record(path, label)


def build_template() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "request_schema": REQUEST_SCHEMA,
        "status": STATUS_TEMPLATE,
        "source_only": True,
        "launch_disabled": True,
        "solver_started": False,
        "native_payload_read": False,
        "hdf5_read": False,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "sentinel_id": "F1-S2",
        "family_id": "F1",
        "physical_case_id": "F1_DUAL_HEAD_340_UNCHANGED_MOTHER_GEOMETRY_V1",
        "root271_pair_source": {
            "schema": "ds02.stage2.f1-s2.medium-savedt-cfl-pair-source-request.v1",
            "same_member_terminal_receipt": "PARENT_ROOT273_SAME_CFL_TERMINAL_RECEIPT_REQUIRED",
            "half_member_terminal_receipt": "PARENT_ROOT273_HALF_CFL_TERMINAL_RECEIPT_REQUIRED",
            "same_member_cfl": ["0.2", "0.2"],
            "half_member_cfl": ["0.1", "0.1"],
            "common_savedt_s": 0.005,
            "common_tout_s": 0.005,
            "window_s": [0.0, 0.5],
            "source_copy": "ROOT273 parent must copy the original BI4/XML to new attempt inodes and prove pre/post SHA/stat",
        },
        "registered_queries_s": list(QUERIES_S),
        "time_semantics": {
            "native_frame_id_source": "actual terminal RunPARTs.csv Part column",
            "selected_frame_policy": "frame zero, actual final frame, and both native endpoints of each exact/bracketed query",
            "no_interpolation": True,
            "no_extrapolation": True,
            "async_same_half_is_unknown_until_actual_pair": True,
            "selected_array_index_is_not_native_frame_id": True,
        },
        "calibration_provenance": {
            "ROOT207_native_header_selected": {
                "proof_sha256": "c2016d5a36922230eafc57c49baadaeff3a2bc920bb953b5fef215eb9fda30ab",
                "scope": "native header/MassFluid/MassBound/Dp/role arithmetic and storage calibration; not this pair's terminal evidence",
            },
            "ROOT217_official_writer": {
                "proof_sha256": "7df9b02c339e3b3eb8bae8f108c16d5db0fd2b6cb3f03d192c4edc827ae1bdf0",
                "scope": "manufactured writer/decoder six-particle calibration; does not assign producer world-axis Q",
            },
            "world_axis": "UNKNOWN",
            "continuum_owner_mass": "340 kg owner contract; native sample mass remains separate",
        },
        "worker_contract": {
            "worker": _source_record(SELECTED_OBSERVER, "existing F1 native selected observer worker"),
            "physical_observer_dependency": _source_record(PHYSICAL_OBSERVER, "existing native physical observer dependency"),
            "literal_python": str(PYTHON),
            "deferred_source_snapshot": "parent must supply selected BI4 SHA/stat after reservation, before decode, and after decode",
            "decoded_fields": ["Idp", "Pos", "Vel", "Rhop", "MassFluid", "MassBound when exposed", "typed role/MK counts", "weighted COM/velocity/KE"],
            "xml_mass_fallback": "FORBIDDEN",
            "native_mass_scope": "native MassFluid/MassBound only; no continuum-owner rescale",
        },
        "resource_guard": {
            "cpu_threads": 1,
            "gpu": "parent-selected only; this request does not launch",
            "memory_bytes": 2 * 1024 * 1024 * 1024,
            "scratch_bytes": 256 * 1024 * 1024,
            "max_wall_seconds": 1800,
            "log_cap_bytes": 64 * 1024,
            "source_read_scope": "selected Part files only after parent reservation; no full native tree/H5/VTK",
        },
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "qualification_limits": [
            "A .5 s same/half pair is a bounded CFL/output diagnostic, not a full-window qualification.",
            "Saved-time brackets are retained as observations and are not interpolated.",
            "Different saved times do not receive time/integration credit.",
            "Neighboring spatial grids are not truth references.",
            "ROOT207/217 calibration evidence is not a producer world-axis proof for this pair.",
        ],
    }


def build_actual(args: argparse.Namespace) -> dict[str, Any]:
    same = _member("same_cfl", args.same_receipt, args.same_runparts, args.same_raw_root, args.same_proof, args.pair_manifest)
    half = _member("half_cfl", args.half_receipt, args.half_runparts, args.half_raw_root, args.half_proof, args.pair_manifest)
    shared_brackets = []
    for same_bracket, half_bracket in zip(same["query_brackets"], half["query_brackets"]):
        same_times = (same_bracket["lower_time_s"], same_bracket["upper_time_s"])
        half_times = (half_bracket["lower_time_s"], half_bracket["upper_time_s"])
        shared_brackets.append({
            "query_time_s": same_bracket["query_time_s"],
            "same": same_bracket,
            "half": half_bracket,
            "alignment": "EXACT_SHARED_SAVED_TIME" if same_times == half_times and same_bracket["status"] == half_bracket["status"] == "EXACT" else "ASYNC_TIME_ALIGNMENT_UNKNOWN",
            "interpolation": "NOT_PERFORMED",
        })
    result = build_template()
    result.update({
        "status": STATUS_READY,
        "same_cfl": same,
        "half_cfl": half,
        "pair_time_alignment": shared_brackets,
        "source_pair_terminal_join": {
            "both_terminal_receipts": True,
            "both_runparts_stable_metadata": True,
            "native_source_sha_status": "PARENT_AFTER_RESERVATION_REQUIRED",
            "same_half_control_comparison": "actual receipt argv and ReadXmlRun must be checked by parent; XML overlay alone is insufficient",
        },
    })
    return result


def self_test() -> dict[str, Any]:
    rows = [{"frame": i, "time_s": i * 0.1} for i in range(6)]
    assert query_bracket(rows, 0.0)["status"] == "EXACT"
    assert query_bracket(rows, 0.25)["status"] == "BRACKETED"
    assert query_bracket(rows, 0.25)["lower_frame"] == 2
    assert query_bracket(rows, 0.5)["status"] == "EXACT"
    assert query_bracket(rows, 0.5)["status"] == "EXACT"
    assert query_bracket(rows, 0.7)["status"] == "OUT_OF_RANGE"
    with tempfile.TemporaryDirectory(prefix="ds02-root271-intake-") as td:
        root = Path(td)
        receipt = root / "receipt.json"
        receipt.write_text(json.dumps({"status": "completed", "returncode": 0, "output_root": str(root / "attempt")}), encoding="utf-8")
        runparts = root / "RunPARTs.csv"
        runparts.write_text("Part;TimeStep [s]\n0;0.0\n1;0.25\n2;0.5\n", encoding="utf-8")
        raw = root / "attempt" / "solver_output" / "data"
        actual = _member("same_cfl", receipt, runparts, raw, None, None)
        assert actual["selected_native_frame_ids"] == [0, 1, 2]
        assert actual["query_brackets"][1]["status"] == "EXACT"
        assert all(frame["sha256"] == "PARENT_AFTER_RESERVATION_REQUIRED" for frame in actual["selected_native_frames"])
    return {"status": "PASS", "native_payload_read": False, "queries_s": list(QUERIES_S), "bracket_semantics": "native frame IDs / exact or bracketed / no interpolation"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--template", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--same-receipt", type=Path)
    parser.add_argument("--half-receipt", type=Path)
    parser.add_argument("--same-runparts", type=Path)
    parser.add_argument("--half-runparts", type=Path)
    parser.add_argument("--same-raw-root", type=Path)
    parser.add_argument("--half-raw-root", type=Path)
    parser.add_argument("--same-proof", type=Path)
    parser.add_argument("--half-proof", type=Path)
    parser.add_argument("--pair-manifest", type=Path)
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), indent=2))
        return 0
    if args.output is None:
        parser.error("--output is required")
    if args.template:
        value = build_template()
    else:
        required = (args.same_receipt, args.half_receipt, args.same_runparts, args.half_runparts, args.same_raw_root, args.half_raw_root)
        if any(item is None for item in required):
            parser.error("actual mode requires both receipt, RunPARTs, and raw-root paths")
        value = build_actual(args)
    output = args.output.expanduser().resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite immutable output: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": value["status"], "output": str(output), "native_payload_read": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
