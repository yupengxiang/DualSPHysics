#!/usr/bin/env python3
"""Run the bounded F2-S1 full-window typed conversion and control audit.

This wrapper is a CPU-only post-solver task.  It invokes the already reviewed
direct BI4 converter on the immutable 401-frame raw tree, then records the
saved-window ``RunPARTs.csv`` summaries and corrected motion semantics.  The
RunPARTs file reports per-save-window DtMin/DtMax and DTsMin only; the wrapper
therefore records the effective full step sequence and individual clamp events
as UNKNOWN instead of reconstructing them from CFL or output timestamps.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import math
import re
from typing import Any
import xml.etree.ElementTree as ET


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {"path": str(path.resolve()), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": sha256_file(path)}


def number(value: Any) -> float | None:
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def parse_runparts(path: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8", errors="replace") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        if reader.fieldnames is None:
            raise ValueError(f"RunPARTs has no header: {path}")
        required = {"Part", "TimeStep [s]", "DTsMin", "DtMin [s]", "DtMax [s]"}
        missing = sorted(required - set(reader.fieldnames))
        if missing:
            raise ValueError(f"RunPARTs missing fields {missing}: {path}")
        for raw in reader:
            part = number(raw.get("Part"))
            time_s = number(raw.get("TimeStep [s]"))
            dts_min = number(raw.get("DTsMin"))
            dt_min = number(raw.get("DtMin [s]"))
            dt_max = number(raw.get("DtMax [s]"))
            if None in (part, time_s, dts_min, dt_min, dt_max):
                raise ValueError(f"non-numeric RunPARTs row: {raw}")
            rows.append({"part": int(part), "time_s": time_s, "DTsMin_s": dts_min, "DtMin_s": dt_min, "DtMax_s": dt_max})
    if not rows:
        raise ValueError(f"RunPARTs contains no data rows: {path}")
    times = [float(row["time_s"]) for row in rows]
    if any(later <= earlier for earlier, later in zip(times, times[1:])):
        raise ValueError("RunPARTs saved times are not strictly increasing")
    dtmins = [float(row["DtMin_s"]) for row in rows]
    dtmaxs = [float(row["DtMax_s"]) for row in rows]
    dtsmins = [float(row["DTsMin_s"]) for row in rows]
    file_node = mvrot.find("file")
    return {
        "source": record(path),
        "rows": len(rows),
        "part_first_last": [rows[0]["part"], rows[-1]["part"]],
        "saved_time_window_s": [times[0], times[-1]],
        "saved_time_monotonic": True,
        "dt_min_per_save_window_s": {"min": min(dtmins), "max": max(dtmins)},
        "dt_max_per_save_window_s": {"min": min(dtmaxs), "max": max(dtmaxs)},
        "DTsMin_s": {"min": min(dtsmins), "max": max(dtsmins), "unique": sorted(set(dtsmins))},
        "dt_sequence_status": "UNKNOWN_FULL_STEP_SEQUENCE; RunPARTs stores saved-window summaries only",
        "clamp_event_status": "UNKNOWN_INDIVIDUAL_CLAMP_EVENTS; DTsMin summary is not a step-level clamp trace",
        "cfl_extrapolation_used": False,
        "time_output_comparison_status": "STRUCTURAL_WINDOW_ONLY_UNTIL_OBSERVER_CALIBRATION",
        "rows_detail": rows,
    }


def load_converter(path: Path):
    spec = importlib.util.spec_from_file_location("stage2_ds02_direct_convert", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import converter: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def motion_semantics(xml_path: Path, motion_path: Path, correction_path: Path) -> dict[str, Any]:
    root = ET.parse(xml_path).getroot()
    mvrot = root.find(".//mvrotfile")
    if mvrot is None:
        raise ValueError("generated XML has no mvrotfile")
    rows = []
    for line in motion_path.read_text(encoding="utf-8", errors="replace").splitlines():
        pieces = [piece for piece in re.split(r"[;,\\s]+", line.strip()) if piece]
        if not pieces or pieces[0].startswith("#"):
            continue
        if len(pieces) < 2:
            raise ValueError(f"invalid motion row: {line!r}")
        rows.append([float(pieces[0]), float(pieces[1])])
    if len(rows) < 2:
        raise ValueError("motion input lacks two numeric rows")
    correction = json.loads(correction_path.read_text(encoding="utf-8"))
    semantics = correction["control_semantics_correction"]
    return {
        "correction_source": record(correction_path),
        "motion_input": record(motion_path),
        "xml_mvrotfile": {"duration_s": number(mvrot.get("duration")), "anglesunits": mvrot.get("anglesunits"), "declared_file": None if file_node is None else file_node.get("name")},
        "motion_table": {"rows": len(rows), "time_window_s": [rows[0][0], rows[-1][0]], "angle_deg": [rows[0][1], rows[-1][1]]},
        "effective_control": semantics["effective_control"],
        "interpretation": semantics["interpretation_policy"],
        "source_motion_sha256": semantics["motion_input"]["sha256"],
        "motion_sha256_matches_correction": sha256_file(motion_path) == semantics["motion_input"]["sha256"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--converter", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--generated-xml", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--decoder", type=Path, required=True)
    parser.add_argument("--partvtk", type=Path, required=True)
    parser.add_argument("--validation-dir", type=Path, required=True)
    parser.add_argument("--solver-log", type=Path, required=True)
    parser.add_argument("--runparts", type=Path, required=True)
    parser.add_argument("--solver-receipt", type=Path, required=True)
    parser.add_argument("--gencase-receipt", type=Path, required=True)
    parser.add_argument("--owner-metadata", type=Path, required=True)
    parser.add_argument("--motion", type=Path, required=True)
    parser.add_argument("--control-correction", type=Path, required=True)
    parser.add_argument("--audit-output", type=Path, required=True)
    parser.add_argument("--particle-chunk", type=int, default=65536)
    args = parser.parse_args()
    converter = load_converter(args.converter)
    report = converter.convert_direct(
        data_root=args.data_root,
        generated_xml=args.generated_xml,
        output=args.output,
        report_path=args.report,
        decoder=args.decoder,
        partvtk=args.partvtk,
        validation_dir=args.validation_dir,
        solver_log=args.solver_log,
        solver_receipt=args.solver_receipt,
        gencase_receipt=args.gencase_receipt,
        owner_metadata=args.owner_metadata,
        particle_chunk=args.particle_chunk,
    )
    runparts = parse_runparts(args.runparts)
    motion = motion_semantics(args.generated_xml, args.motion, args.control_correction)
    audit = {
        "schema": "ds-data-02.stage2.f2-s1.full401-conversion-audit.v1",
        "status": "COMPLETED_CONVERSION_AND_CONTROL_AUDIT",
        "conversion_report": record(args.report),
        "typed_output": record(args.output),
        "solver_receipt": record(args.solver_receipt),
        "gencase_receipt": record(args.gencase_receipt),
        "source_generated_xml": record(args.generated_xml),
        "raw_data_root": str(args.data_root.resolve()),
        "full_window_expected": {"frames": 401, "time_s": [0.0, 4.0], "query_times_s": [0.0, 1.0, 2.0, 3.0, 4.0]},
        "conversion_report_summary": {
            "conversion_status": report.get("conversion_status"),
            "frames": report.get("frames"),
            "particles": report.get("particles"),
            "time_evidence": report.get("time_evidence"),
            "initial_exclusion_ledger": report.get("typed_identity", {}).get("initial_exclusion_ledger"),
            "partvtk_all_passed": report.get("partvtk_validation", {}).get("all_passed"),
            "qi_status": report.get("q_i_status"),
            "qn_status": report.get("q_n_status"),
            "production_eligibility": report.get("production_eligibility"),
        },
        "runparts_dt_clamp_audit": runparts,
        "motion_control_semantics": motion,
        "quality_scope": {
            "status": "STRUCTURAL_AND_PROVENANCE_ONLY",
            "observer_calibration": "NOT_RUN",
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
            "time_error": "UNKNOWN_UNTIL_COMMON_QUERY_OBSERVER",
            "output_error": "UNKNOWN_UNTIL_COMMON_QUERY_OBSERVER",
            "event_observables": "UNKNOWN",
            "policy": "Do not infer full step dt/clamp sequence from CFL, saved timestamps, or RunPARTs summaries.",
        },
    }
    args.audit_output.parent.mkdir(parents=True, exist_ok=True)
    if args.audit_output.exists():
        raise FileExistsError(args.audit_output)
    args.audit_output.write_text(json.dumps(audit, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": audit["status"], "frames": report.get("frames"), "particles": report.get("particles"), "audit": str(args.audit_output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
