#!/usr/bin/env python3
"""Register every native F3 BI4 frame before streaming post-processing.

The manifest is deliberately metadata-only.  It enumerates every top-level
``Part_####.bi4`` file, records its byte count, and checks the native time
ledger and solver receipt.  The direct converter performs its own full raw
tree hash while reading the data; this preflight therefore avoids a second
multi-gigabyte hash pass and says so explicitly in the resulting evidence.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import resource
from pathlib import Path
from typing import Any, Mapping
import xml.etree.ElementTree as ET


FRAME_RE = re.compile(r"^Part_(\d{4,})\.bi4$")
SCHEMA = "ds02.f3.raw-frame-manifest.v1"


class RawManifestError(RuntimeError):
    """Raised when the closed native frame contract is incomplete."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _ref(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "exists": path.is_file(),
        "bytes": path.stat().st_size if path.is_file() else None,
        "sha256": _sha256(path) if path.is_file() else None,
    }


def _usage() -> dict[str, float]:
    result: dict[str, float] = {}
    for who, label in ((resource.RUSAGE_SELF, "self"), (resource.RUSAGE_CHILDREN, "children")):
        value = resource.getrusage(who)
        result[f"{label}_user_seconds"] = float(value.ru_utime)
        result[f"{label}_system_seconds"] = float(value.ru_stime)
        result[f"{label}_max_rss_kib"] = float(value.ru_maxrss)
    return result


def _float(row: Mapping[str, str], key: str, path: Path) -> float:
    value = row.get(key)
    if value in (None, ""):
        raise RawManifestError(f"RunPARTs row missing {key}: {path}")
    try:
        result = float(value.replace(",", ""))
    except ValueError as exc:
        raise RawManifestError(f"RunPARTs field {key} is not numeric: {value!r}") from exc
    if not result == result or result in (float("inf"), float("-inf")):
        raise RawManifestError(f"RunPARTs field {key} is not finite: {value!r}")
    return result


def parse_runparts(path: Path, expected_frames: int, expected_end_s: float) -> dict[str, Any]:
    rows: list[dict[str, str]] = []
    with path.open(newline="") as handle:
        for row in csv.DictReader(handle, delimiter=";"):
            try:
                int(row.get("Part", ""))
            except (TypeError, ValueError):
                continue
            rows.append(row)
    if len(rows) != expected_frames:
        raise RawManifestError(f"RunPARTs frame rows {len(rows)} != expected {expected_frames}")
    times = [_float(row, "TimeStep [s]", path) for row in rows]
    if not times or abs(times[0]) > 1e-10 or times[-1] < expected_end_s:
        raise RawManifestError(f"RunPARTs does not cover 0-{expected_end_s:g}s: {times[:1]}..{times[-1:]}")
    if any(right <= left for left, right in zip(times, times[1:])):
        raise RawManifestError("RunPARTs save times are not strictly increasing")
    npout = sum(int(_float(row, "NpOut", path)) for row in rows)
    steps = sum(int(_float(row, "Steps", path)) for row in rows)
    dt_values = [_float(row, "DtMin [s]", path) for row in rows]
    dt_max_values = [_float(row, "DtMax [s]", path) for row in rows]
    return {
        "source": _ref(path),
        "saved_frames": len(rows),
        "time_start_s": times[0],
        "time_end_s": times[-1],
        "save_interval_min_s": min(b - a for a, b in zip(times, times[1:])),
        "save_interval_max_s": max(b - a for a, b in zip(times, times[1:])),
        "internal_steps": steps,
        "actual_internal_dt_min_s": min(dt_values),
        "actual_internal_dt_max_s": max(dt_max_values),
        "excluded_interval_sum_NpOut": npout,
        "initial_total_particles": int(_float(rows[0], "NpSim", path)),
        "initial_fluid_particles": int(_float(rows[0], "NpfSim", path)),
        "final_total_particles": int(_float(rows[-1], "NpSim", path)),
        "final_fluid_particles": int(_float(rows[-1], "NpfSim", path)),
    }


def parse_run_csv(path: Path, expected_frames: int) -> dict[str, Any]:
    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter=";"))
    if len(rows) != 1:
        raise RawManifestError(f"Run.csv must contain one summary row: {path}")
    row = rows[0]
    try:
        part_files = int(row["PartFiles"].replace(",", ""))
        particles = int(row["Np"].replace(",", ""))
        steps = int(row["Steps"].replace(",", ""))
        physical_time = float(row["PhysicalTime"])
        dp = float(row["Dp"])
    except (KeyError, ValueError) as exc:
        raise RawManifestError(f"Run.csv summary is malformed: {path}") from exc
    if part_files != expected_frames:
        raise RawManifestError(f"Run.csv PartFiles {part_files} != expected {expected_frames}")
    return {
        "source": _ref(path),
        "part_files": part_files,
        "particles": particles,
        "steps": steps,
        "physical_time_s": physical_time,
        "dp_m": dp,
        "configuration": row.get("Configuration"),
    }


def parse_run_out(path: Path) -> dict[str, Any]:
    text = path.read_text(errors="replace")
    if not re.search(r"\*\*\s*3D-Simulation parameters", text, re.IGNORECASE):
        raise RawManifestError("Run.out lacks actual 3-D simulation evidence")
    if re.search(r"\*\*\s*2D-Simulation parameters", text, re.IGNORECASE):
        raise RawManifestError("Run.out contains conflicting 2-D simulation evidence")

    def match(*keys: str) -> float | None:
        pattern = r"^(?:" + "|".join(map(re.escape, keys)) + r")=([0-9.eE+-]+)"
        found = re.search(pattern, text, re.MULTILINE)
        return None if found is None else float(found.group(1))

    return {
        "source": _ref(path),
        "actual_3d_banner": True,
        "dt_min_s": match("DtMin"),
        "time_out_s": match("TimePart", "TimeOut"),
        "time_max_s": match("TimeMax"),
        "steps_reported": match("Steps"),
    }


def make_manifest(
    *,
    data_root: Path,
    runparts: Path,
    run_csv: Path,
    run_out: Path,
    solver_receipt: Path,
    generated_xml: Path,
    prepared_source_manifest: Path,
    output: Path,
    expected_frames: int,
    expected_end_s: float = 10.0,
) -> dict[str, Any]:
    before = _usage()
    paths = (data_root, runparts, run_csv, run_out, solver_receipt, generated_xml, prepared_source_manifest)
    if not data_root.is_dir():
        raise RawManifestError(f"missing BI4 data directory: {data_root}")
    for path in paths[1:]:
        if not path.is_file():
            raise RawManifestError(f"missing raw-manifest input: {path}")
    receipt = json.loads(solver_receipt.read_text())
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise RawManifestError("solver receipt is not completed successfully")
    frames: list[tuple[int, Path]] = []
    for path in sorted(data_root.glob("Part_*.bi4")):
        match = FRAME_RE.match(path.name)
        if match and path.is_file():
            frames.append((int(match.group(1)), path))
    if [index for index, _ in frames] != list(range(expected_frames)):
        observed = [index for index, _ in frames]
        raise RawManifestError(f"raw BI4 frame indices/count are not 0..{expected_frames - 1}: {observed[:3]}..{observed[-3:]}")
    part_info = data_root / "PartInfo.ibi4"
    if not part_info.is_file():
        raise RawManifestError(f"missing PartInfo.ibi4: {part_info}")
    root = ET.parse(generated_xml).getroot()
    control_node = root.find(".//acctimesfile")
    if control_node is None or not control_node.get("value"):
        raise RawManifestError("generated XML lacks acctimesfile reference")
    control_path = generated_xml.parent / control_node.get("value")
    if not control_path.is_file():
        raise RawManifestError(f"prepared XML control reference is not beside XML: {control_path}")
    runparts_evidence = parse_runparts(runparts, expected_frames, expected_end_s)
    run_csv_evidence = parse_run_csv(run_csv, expected_frames)
    run_out_evidence = parse_run_out(run_out)
    if runparts_evidence["initial_total_particles"] <= 0 or runparts_evidence["initial_fluid_particles"] <= 0:
        raise RawManifestError("native frame ledger has no particles")
    if output.exists():
        raise RawManifestError(f"refusing to overwrite raw-frame manifest: {output}")
    frame_rows = [{"path": path.name, "frame": index, "bytes": path.stat().st_size} for index, path in frames]
    all_files = [{"path": part_info.name, "bytes": part_info.stat().st_size}] + frame_rows
    result: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "completed_actual_read_only",
        "claim_boundary": "raw-frame enumeration and native ledger binding only; no conversion/Q-N/production claim",
        "case_id": receipt.get("request", {}).get("case_id"),
        "solver_attempt_id": receipt.get("request", {}).get("attempt_id"),
        "solver_receipt": _ref(solver_receipt),
        "generated_xml": _ref(generated_xml),
        "prepared_source_manifest": _ref(prepared_source_manifest),
        "control_reference": {"xml_attribute": control_node.get("value"), "resolved": _ref(control_path)},
        "raw_source": {
            "root": str(data_root.resolve()),
            "frame_pattern": "Part_####.bi4",
            "frame_count": len(frames),
            "part_info": _ref(part_info),
            "files": all_files,
            "total_bytes": sum(row["bytes"] for row in all_files),
            "hash_policy": "metadata_only_no_full_raw_rehash",
            "full_tree_hash_deferred_to_direct_converter": True,
        },
        "expected": {"saved_frames": expected_frames, "window_s": [0.0, expected_end_s]},
        "native_ledger": {"runparts": runparts_evidence, "run_csv": run_csv_evidence, "run_out": run_out_evidence},
        "q_n_status": "not_assessed",
        "resource_usage": {"before": before, "after": _usage()},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--runparts", type=Path, required=True)
    parser.add_argument("--run-csv", type=Path, required=True)
    parser.add_argument("--run-out", type=Path, required=True)
    parser.add_argument("--solver-receipt", type=Path, required=True)
    parser.add_argument("--generated-xml", type=Path, required=True)
    parser.add_argument("--prepared-source-manifest", type=Path, required=True)
    parser.add_argument("--expected-frames", type=int, required=True)
    parser.add_argument("--expected-end-s", type=float, default=10.0)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = make_manifest(
            data_root=args.data_root, runparts=args.runparts, run_csv=args.run_csv, run_out=args.run_out,
            solver_receipt=args.solver_receipt, generated_xml=args.generated_xml,
            prepared_source_manifest=args.prepared_source_manifest, output=args.output,
            expected_frames=args.expected_frames, expected_end_s=args.expected_end_s,
        )
    except (OSError, ValueError, json.JSONDecodeError, ET.ParseError, RawManifestError) as exc:
        print(f"F3 raw manifest failed: {exc}")
        return 2
    print(json.dumps({"output": str(args.output.resolve()), "frames": result["raw_source"]["frame_count"], "q_n_status": "not_assessed"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
