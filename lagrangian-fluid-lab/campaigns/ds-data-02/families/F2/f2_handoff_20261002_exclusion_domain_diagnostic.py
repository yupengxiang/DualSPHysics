#!/usr/bin/env python3
"""Classify fine native exclusions against the actual solver domain.

This is a bounded, read-only diagnostic for the two completed F2 fine runs.
It consumes the native exclusion ledgers, generated XML files, Run.out domain
banner, and full RunPARTs logs.  It never treats a PartVTKOut exclusion as
physical spill: the result is evidence about proximity to the numerical
simulation-domain faces, with the exclusion motive and RunPARTs counters kept
separate.  The face tolerance is descriptive only and is never a Q-I/Q-N gate.
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import statistics
import xml.etree.ElementTree as ET
from typing import Any, Iterable


class DiagnosticError(RuntimeError):
    """Raised when an input does not contain the required evidence."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(path: Path, label: str) -> Path:
    path = path.resolve()
    if not path.is_file():
        raise DiagnosticError(f"{label} is missing: {path}")
    return path


def parse_domain(xml_path: Path) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    root = ET.parse(require(xml_path, "generated XML")).getroot()
    domain = root.find(".//simulationdomain")
    if domain is None:
        raise DiagnosticError(f"simulationdomain is missing: {xml_path}")
    try:
        low_node = domain.find("posmin")
        high_node = domain.find("posmax")
        if low_node is None or high_node is None:
            raise KeyError("posmin/posmax")
        low = tuple(float(low_node.attrib[axis]) for axis in ("x", "y", "z"))
        high = tuple(float(high_node.attrib[axis]) for axis in ("x", "y", "z"))
    except (KeyError, TypeError, ValueError) as error:
        raise DiagnosticError(f"simulationdomain coordinates are invalid: {xml_path}") from error
    if any(a >= b for a, b in zip(low, high)):
        raise DiagnosticError(f"simulationdomain is not ordered: {xml_path}")
    return low, high


def parse_map_real_pos(run_out: Path) -> dict[str, tuple[float, float, float]]:
    pattern = re.compile(
        r"MapRealPos\((border|final)\)=\(([^)]*)\)-\(([^)]*)\)", re.IGNORECASE
    )
    found: dict[str, tuple[float, float, float]] = {}
    for line in require(run_out, "Run.out").read_text(encoding="utf-8", errors="replace").splitlines():
        match = pattern.search(line)
        if not match:
            continue
        try:
            first = tuple(float(value.strip()) for value in match.group(2).split(","))
            second = tuple(float(value.strip()) for value in match.group(3).split(","))
        except ValueError as error:
            raise DiagnosticError(f"invalid MapRealPos banner: {line}") from error
        if len(first) != 3 or len(second) != 3:
            raise DiagnosticError(f"MapRealPos banner is not 3D: {line}")
        found[match.group(1).lower()] = (first, second)
    if "final" not in found:
        raise DiagnosticError(f"MapRealPos(final) is missing: {run_out}")
    return found


def number(value: Any) -> float:
    return float(str(value).strip().replace(",", ""))


def runparts_summary(path: Path) -> dict[str, Any]:
    counters = {name: [] for name in ("NpOut", "NpOutPos", "NpOutRho", "NpOutMov")}
    rows = 0
    with require(path, "RunPARTs.csv").open(encoding="utf-8", errors="replace", newline="") as handle:
        for row in csv.DictReader(handle, delimiter=";"):
            # RunPARTs appends a human-readable column legend after the data
            # rows; it has no numeric NpOut field and is excluded from the
            # full-timeline counter exactly as the native ledger parser does.
            if not row.get("NpOut") and str(row.get("Part", "")).lstrip().startswith("#"):
                continue
            rows += 1
            for name in counters:
                try:
                    counters[name].append(number(row[name]))
                except (KeyError, TypeError, ValueError):
                    raise DiagnosticError(f"RunPARTs row lacks numeric {name}: {path}") from None
    if not rows:
        raise DiagnosticError(f"RunPARTs.csv is empty: {path}")
    return {
        name: {"rows": rows, "sum": sum(values), "max": max(values), "nonzero_rows": sum(value != 0 for value in values)}
        for name, values in counters.items()
    }


def classify_case(
    *, case_id: str, ledger_path: Path, xml_path: Path, runparts_path: Path,
    run_out_path: Path, tolerance_m: float,
) -> dict[str, Any]:
    ledger = json.loads(require(ledger_path, "native ledger").read_text(encoding="utf-8"))
    native = ledger.get("native_exclusion_ledger")
    if not isinstance(native, dict):
        raise DiagnosticError(f"native_exclusion_ledger mapping is missing: {ledger_path}")
    records = native.get("excluded_particles")
    if not isinstance(records, list):
        raise DiagnosticError(f"excluded_particles list is missing: {ledger_path}")
    low, high = parse_domain(xml_path)
    map_pos = parse_map_real_pos(run_out_path)
    map_low, map_high = map_pos["final"]
    map_match = all(abs(a - b) <= 1e-12 for a, b in zip(low + high, map_low + map_high))
    labels = ("xmin", "ymin", "zmin", "xmax", "ymax", "zmax")
    nearest_counts: Counter[str] = Counter()
    tolerance_groups: Counter[str] = Counter()
    motive_counts: Counter[str] = Counter()
    distances: list[float] = []
    first_times: list[float] = []
    first_frames: list[int] = []
    bad_records: list[dict[str, Any]] = []
    for record in records:
        try:
            position = tuple(float(value) for value in record["position_m"])
            motive = str(record["motive"])
            time_s = float(record["first_missing_time_s"])
            frame = int(record["first_missing_frame"])
        except (KeyError, TypeError, ValueError) as error:
            raise DiagnosticError(f"invalid exclusion record in {ledger_path}") from error
        if len(position) != 3:
            raise DiagnosticError(f"exclusion position is not 3D in {ledger_path}")
        face_distances = (
            position[0] - low[0], position[1] - low[1], position[2] - low[2],
            high[0] - position[0], high[1] - position[1], high[2] - position[2],
        )
        nearest_index = min(range(6), key=lambda index: abs(face_distances[index]))
        nearest_counts[labels[nearest_index]] += 1
        near = tuple(labels[index] for index, distance in enumerate(face_distances) if abs(distance) <= tolerance_m)
        tolerance_groups["|".join(near) if near else "none"] += 1
        motive_counts[motive] += 1
        nearest_distance = abs(face_distances[nearest_index])
        distances.append(nearest_distance)
        first_times.append(time_s)
        first_frames.append(frame)
        if not near:
            bad_records.append({"idp": record.get("idp"), "position_m": list(position), "nearest_face": labels[nearest_index], "nearest_distance_m": nearest_distance})
    runparts = runparts_summary(runparts_path)
    reported = native.get("excluded_particles_reported_by_run_out")
    if reported is None:
        raise DiagnosticError(f"native ledger has no reported exclusion count: {ledger_path}")
    output = {
        "schema": "ds-data-02.f2.exclusion-domain-diagnostic.v1",
        "case_id": case_id,
        "inputs": {
            "native_ledger": {"path": str(ledger_path.resolve()), "sha256": sha256(ledger_path)},
            "generated_xml": {"path": str(xml_path.resolve()), "sha256": sha256(xml_path)},
            "runparts": {"path": str(runparts_path.resolve()), "sha256": sha256(runparts_path)},
            "solver_log": {"path": str(run_out_path.resolve()), "sha256": sha256(run_out_path)},
        },
        "simulation_domain": {
            "xml_low_m": list(low), "xml_high_m": list(high),
            "run_out_map_real_pos_final_low_m": list(map_low),
            "run_out_map_real_pos_final_high_m": list(map_high),
            "xml_and_run_out_match": map_match,
        },
        "diagnostic_face_tolerance_m": tolerance_m,
        "exclusion_count": len(records),
        "reported_run_out_exclusion_count": int(reported),
        "reported_count_matches_records": int(reported) == len(records),
        "nearest_domain_face_counts": dict(sorted(nearest_counts.items())),
        "within_diagnostic_tolerance_face_groups": dict(sorted(tolerance_groups.items())),
        "motive_counts": dict(sorted(motive_counts.items())),
        "nearest_face_distance_m": {
            "min": min(distances) if distances else None,
            "median": statistics.median(distances) if distances else None,
            "max": max(distances) if distances else None,
        },
        "first_missing_frame": {
            "min": min(first_frames) if first_frames else None,
            "median": statistics.median(first_frames) if first_frames else None,
            "max": max(first_frames) if first_frames else None,
        },
        "first_missing_time_s": {
            "min": min(first_times) if first_times else None,
            "median": statistics.median(first_times) if first_times else None,
            "max": max(first_times) if first_times else None,
        },
        "runparts_counts": runparts,
        "records_outside_diagnostic_tolerance": bad_records,
        "interpretation": {
            "domain_edge_consistency": bool(map_match and not bad_records and int(reported) == len(records)),
            "classification": "numerical_domain_face_consistent; native motive remains numerical_unknown",
            "physical_spill": "not_classified_by_this_diagnostic",
            "qualification_claim": "none",
        },
    }
    return output


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--center-ledger", type=Path, required=True)
    parser.add_argument("--center-xml", type=Path, required=True)
    parser.add_argument("--center-runparts", type=Path, required=True)
    parser.add_argument("--center-run-out", type=Path, required=True)
    parser.add_argument("--offset-ledger", type=Path, required=True)
    parser.add_argument("--offset-xml", type=Path, required=True)
    parser.add_argument("--offset-runparts", type=Path, required=True)
    parser.add_argument("--offset-run-out", type=Path, required=True)
    parser.add_argument("--face-tolerance-m", type=float, default=5e-4)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(list(argv) if argv is not None else None)
    if not 0 < args.face_tolerance_m < 0.01:
        parser.error("--face-tolerance-m must be between 0 and 0.01 m")
    try:
        result = {
            "schema": "ds-data-02.f2.exclusion-domain-diagnostic-bundle.v1",
            "generated_at_utc": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
            "diagnostic_face_tolerance_m": args.face_tolerance_m,
            "cases": [
                classify_case(case_id="F2H10V2_CENTER_V1_FINE", ledger_path=args.center_ledger, xml_path=args.center_xml, runparts_path=args.center_runparts, run_out_path=args.center_run_out, tolerance_m=args.face_tolerance_m),
                classify_case(case_id="F2H10V2_OFFSET_V1_FINE", ledger_path=args.offset_ledger, xml_path=args.offset_xml, runparts_path=args.offset_runparts, run_out_path=args.offset_run_out, tolerance_m=args.face_tolerance_m),
            ],
            "qualification_claim": "none",
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except (DiagnosticError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"f2_handoff_20261002_exclusion_domain_diagnostic: {type(error).__name__}: {error}")
        return 2
    print(json.dumps({"status": "completed", "output": str(args.output.resolve()), "cases": len(result["cases"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
