#!/usr/bin/env python3
"""Prepare and audit the L2-R F5 fresh runtime-domain confirmation.

The historical C3 F5 run showed a very specific failure: native ``NpOutPos``
records appeared when the splash reached the finite numerical upper face.  This
entry point materializes a new F5 definition with an explicit, larger runtime
domain and provides a read-only post-run identity ledger.

The default ``preflight`` command only copies/edits XML and writes a separate
report.  It does not call GenCase, DualSPHysics, PartVTK, or ``l2_resume``.
The ``audit`` command also does not launch a solver; it consumes an already
completed fresh attempt, a normalized HDF5, a PartOut CSV export, and the
native RunPARTs/Run.out files.  A missing or historical artifact is reported as
blocked rather than being relabelled as a new L2-R execution.
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
from typing import Any, Iterable
import xml.etree.ElementTree as ET

import h5py
import numpy as np


LAB = Path(__file__).resolve().parents[1]
CAMPAIGN = LAB / "campaigns" / "l2-multifamily"
RESUME_ROOT = CAMPAIGN / "resume-c6b28c8"

LEGACY_CASE_ID = "L2_C3_F5_low_weir_nominal"
FRESH_CASE_ID = "L2R_F5_runtime_domain_confirmation"
FRESH_RECIPE_ID = "L2R_F5_runtime_domain_explicit_v1_dp0p0075"
FRESH_LINEAGE_ID = "lineage_L2R_F5_runtime_domain_confirmation_v1"
FRESH_BACKGROUND_ID = "paired_F5R_runtime_domain_confirmation_v1"
LEGACY_ATTEMPT_ID = "20260913T171349.867087Z-00b76b61"

LEGACY_REPORT = CAMPAIGN / "reports" / "c3-bounded-anchors.json"
LEGACY_EVIDENCE_REPORT = RESUME_ROOT / "c3r-evidence.json"
LEGACY_DEFINITION = CAMPAIGN / "c3-canary" / "cases" / f"{LEGACY_CASE_ID}_Def.xml"
DEFAULT_ROOT = RESUME_ROOT / "f5r-confirmation"
DEFAULT_XML = DEFAULT_ROOT / "cases" / f"{FRESH_CASE_ID}_Def.xml"
DEFAULT_PREFLIGHT = RESUME_ROOT / "f5r-confirmation-preflight.json"
DEFAULT_AUDIT = RESUME_ROOT / "f5r-confirmation-audit.json"

# The C3 generated particle envelope was approximately
# [0, 1.2] x [0, .3975] x [0, .6].  The old default expressions resolved to a
# numerical upper z face of 1.05162 m, and the last valid missing identities
# reached z=1.051571965... m.  All six faces are explicit here.  This is a
# numerical domain change only: the physical top/open-face and low-weir
# geometry are copied unchanged from the C3 definition.
HISTORICAL_RUNTIME_DOMAIN = {
    "xmin": -0.300974,
    "xmax": 1.500974,
    "ymin": -0.100349,
    "ymax": 0.497849,
    "zmin": -0.150974,
    "zmax": 1.05162,
}
F5R_RUNTIME_DOMAIN = {
    "xmin": -0.30,
    "xmax": 1.50,
    "ymin": -0.099375,
    "ymax": 0.496875,
    "zmin": -0.15,
    "zmax": 1.35,
}

REQUIRED_RUNPARTS_COLUMNS = (
    "Part",
    "TimeStep [s]",
    "NpOut",
    "NpOutPos",
    "NpOutRho",
    "NpOutMov",
)
REQUIRED_PARTOUT_COLUMNS = ("Idp", "PartOut")
REQUIRED_HDF5_DATASETS = ("time", "valid", "particle_id", "position", "velocity", "mass")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _repo_relative(path: Path) -> str:
    path = Path(path)
    try:
        return str(path.resolve().relative_to(LAB.parent.resolve()))
    except ValueError:
        return str(path)


def _git_head() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=LAB.parent,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


def file_evidence(path: Path) -> dict[str, Any]:
    path = Path(path)
    evidence: dict[str, Any] = {
        "path": _repo_relative(path),
        "absolute_path": str(path.resolve()),
        "exists": path.is_file(),
    }
    if path.is_file():
        evidence.update({"bytes": path.stat().st_size, "sha256": _sha256(path)})
    return evidence


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    partial.replace(path)


def _finite_domain(domain: dict[str, Any]) -> dict[str, float]:
    required = ("xmin", "xmax", "ymin", "ymax", "zmin", "zmax")
    result: dict[str, float] = {}
    for key in required:
        try:
            value = float(domain[key])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"runtime domain value {key!r} is not numeric") from error
        if not math.isfinite(value):
            raise ValueError(f"runtime domain value {key!r} is not finite")
        result[key] = value
    for axis in "xyz":
        if result[f"{axis}min"] >= result[f"{axis}max"]:
            raise ValueError(f"runtime domain {axis}min must be below {axis}max")
    return result


def _simulation_domain(root: ET.Element) -> ET.Element:
    node = root.find(".//execution/parameters/simulationdomain")
    if node is None:
        raise ValueError("F5 definition has no execution/parameters/simulationdomain")
    if node.find("posmin") is None or node.find("posmax") is None:
        raise ValueError("F5 simulationdomain must contain posmin and posmax")
    return node


def _physical_signature(path: Path) -> str:
    """Hash the XML after removing only the numerical simulation-domain node."""

    tree = ET.parse(path)
    root = tree.getroot()

    def canonical(node: ET.Element) -> Any:
        children = [canonical(child) for child in list(node) if child.tag != "simulationdomain"]
        text = (node.text or "").strip()
        return [node.tag, sorted(node.attrib.items()), text, children]

    return hashlib.sha256(
        json.dumps(canonical(root), ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def read_runtime_domain(path: Path) -> dict[str, Any]:
    """Read numeric simulation-domain faces and preserve nonnumeric expressions."""

    path = Path(path)
    if not path.is_file():
        return {"path": _repo_relative(path), "exists": False, "status": "missing"}
    try:
        root = ET.parse(path).getroot()
        node = _simulation_domain(root)
    except (ET.ParseError, ValueError) as error:
        return {
            "path": _repo_relative(path),
            "exists": True,
            "status": "malformed",
            "error": f"{error.__class__.__name__}: {error}",
        }
    minimum = node.find("posmin")
    maximum = node.find("posmax")
    assert minimum is not None and maximum is not None
    expressions = {
        "min": {axis: minimum.attrib.get(axis) for axis in "xyz"},
        "max": {axis: maximum.attrib.get(axis) for axis in "xyz"},
    }
    numeric: dict[str, float] = {}
    errors: list[str] = []
    for side, element in (("min", minimum), ("max", maximum)):
        for axis in "xyz":
            raw = element.attrib.get(axis)
            try:
                value = float(raw)
            except (TypeError, ValueError):
                errors.append(f"{side}{axis}_not_numeric")
                continue
            if not math.isfinite(value):
                errors.append(f"{side}{axis}_not_finite")
                continue
            numeric[f"{axis}{side}"] = value
    result: dict[str, Any] = {
        "path": _repo_relative(path),
        "exists": True,
        "expressions": expressions,
        "all_faces_explicit": not errors and len(numeric) == 6,
        "errors": errors,
    }
    if result["all_faces_explicit"]:
        result["domain"] = {key: numeric[key] for key in ("xmin", "xmax", "ymin", "ymax", "zmin", "zmax")}
        result["status"] = "explicit"
    else:
        result["status"] = "symbolic_or_incomplete"
    return result


def configure_runtime_domain(
    source_xml: Path,
    destination_xml: Path,
    *,
    runtime_domain: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write a fresh XML copy with six explicit numerical domain faces.

    Only the ``simulationdomain`` attributes and its audit comment are changed.
    The source file is never edited, and the physical signature is checked
    before returning.
    """

    source_xml = Path(source_xml)
    destination_xml = Path(destination_xml)
    if not source_xml.is_file():
        raise FileNotFoundError(source_xml)
    target_domain = _finite_domain(runtime_domain or F5R_RUNTIME_DOMAIN)
    source_signature = _physical_signature(source_xml)
    tree = ET.parse(source_xml)
    root = tree.getroot()
    node = _simulation_domain(root)
    minimum = node.find("posmin")
    maximum = node.find("posmax")
    assert minimum is not None and maximum is not None
    for axis in "xyz":
        minimum.set(axis, f"{target_domain[axis + 'min']:.9g}")
        maximum.set(axis, f"{target_domain[axis + 'max']:.9g}")
    node.set(
        "comment",
        "L2-R F5 fresh confirmation: explicit numerical runtime domain; "
        "physical low-weir/open-top geometry is unchanged",
    )
    destination_xml.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(tree, space="    ")
    tree.write(destination_xml, encoding="utf-8", xml_declaration=True)
    destination_signature = _physical_signature(destination_xml)
    parsed = read_runtime_domain(destination_xml)
    if not parsed.get("all_faces_explicit") or destination_signature != source_signature:
        raise RuntimeError("configured F5 XML failed explicit-domain or physical-signature check")
    return {
        "source": file_evidence(source_xml),
        "configured": file_evidence(destination_xml),
        "source_physical_signature": source_signature,
        "configured_physical_signature": destination_signature,
        "physical_geometry_unchanged": source_signature == destination_signature,
        "runtime_domain": target_domain,
        "configured_runtime_domain": parsed,
        "solver_invocations": 0,
        "gencase_invocations": 0,
    }


def _legacy_lineage() -> dict[str, Any]:
    report_evidence = file_evidence(LEGACY_REPORT)
    c3r_evidence = file_evidence(LEGACY_EVIDENCE_REPORT)
    legacy_attempt_id = LEGACY_ATTEMPT_ID
    legacy_definition_sha256: str | None = None
    historical_domain = dict(HISTORICAL_RUNTIME_DOMAIN)
    historical_missing_count = 263
    historical_max_last_valid_z = 1.0515719652175903
    if LEGACY_REPORT.is_file():
        try:
            payload = json.loads(LEGACY_REPORT.read_text())
            record = next(
                item for item in payload.get("attempts", []) if item.get("case_id") == LEGACY_CASE_ID
            )
            legacy_attempt = record.get("attempt", {})
            legacy_attempt_id = str(legacy_attempt.get("attempt_id") or legacy_attempt_id)
            legacy_definition_sha256 = record.get("definition_sha256")
            audit = next(
                item for item in payload.get("audits", []) if item.get("case_id") == LEGACY_CASE_ID
            )
            historical_missing_count = int(audit.get("missing_initial_identities_at_final", historical_missing_count))
            historical_domain = {
                **historical_domain,
                "zmax": float(
                    audit.get("independent_audit", {})
                    .get("runtime_domain", {})
                    .get("upper", [None, None, HISTORICAL_RUNTIME_DOMAIN["zmax"]])[2]
                ),
            }
        except (StopIteration, KeyError, TypeError, ValueError, json.JSONDecodeError):
            pass
    if LEGACY_EVIDENCE_REPORT.is_file():
        try:
            payload = json.loads(LEGACY_EVIDENCE_REPORT.read_text())
            root_cause = payload.get("f5_loss_root_cause", {})
            trajectory = root_cause.get("trajectory", {})
            historical_missing_count = int(
                trajectory.get("loss_identity_summary", {}).get(
                    "missing_initial_identity_count", historical_missing_count
                )
            )
            historical_max_last_valid_z = float(
                trajectory.get("loss_identity_summary", {})
                .get("last_valid_position_of_missing", {})
                .get("max_z_m", historical_max_last_valid_z)
            )
            actual_domain = root_cause.get("solver_output", {}).get("run_log", {}).get("runtime_domain", {})
            if actual_domain.get("available"):
                historical_domain["zmax"] = float(actual_domain["upper"][2])
        except (TypeError, ValueError, KeyError, json.JSONDecodeError):
            pass
    return {
        "legacy_case_id": LEGACY_CASE_ID,
        "legacy_attempt_id": legacy_attempt_id,
        "legacy_definition": file_evidence(LEGACY_DEFINITION),
        "legacy_definition_sha256_from_report": legacy_definition_sha256,
        "legacy_report": report_evidence,
        "c3r_evidence_report": c3r_evidence,
        "historical_runtime_domain": historical_domain,
        "historical_missing_identity_count": historical_missing_count,
        "historical_last_valid_missing_max_z_m": historical_max_last_valid_z,
    }


def build_preflight(
    *,
    source_xml: Path = LEGACY_DEFINITION,
    configured_xml: Path = DEFAULT_XML,
    output_report: Path = DEFAULT_PREFLIGHT,
    runtime_domain: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Materialize the F5R configuration and a separate no-execution report."""

    target_domain = _finite_domain(runtime_domain or F5R_RUNTIME_DOMAIN)
    lineage = _legacy_lineage()
    configuration: dict[str, Any] | None = None
    errors: list[str] = []
    try:
        configuration = configure_runtime_domain(
            source_xml,
            configured_xml,
            runtime_domain=target_domain,
        )
    except (OSError, ET.ParseError, RuntimeError, ValueError) as error:
        errors.append(f"configuration:{error.__class__.__name__}:{error}")

    historical = lineage["historical_runtime_domain"]
    expansion = {
        key: target_domain[key] - float(historical[key])
        for key in ("xmin", "xmax", "ymin", "ymax", "zmin", "zmax")
    }
    checks = {
        "source_definition_exists": Path(source_xml).is_file(),
        "configured_definition_exists": bool(configuration),
        "all_runtime_faces_explicit": bool(configuration and configuration["configured_runtime_domain"].get("all_faces_explicit")),
        "physical_geometry_unchanged": bool(configuration and configuration["physical_geometry_unchanged"]),
        "runtime_zmax_expanded_above_historical_ceiling": target_domain["zmax"] > float(historical["zmax"]),
        "runtime_domain_is_finite_and_ordered": True,
    }
    ready = not errors and all(checks.values())
    report = {
        "schema": "l2.f5r.confirmation.v1",
        "stage": "F5R",
        "created_at_utc": utc_now(),
        "current_commit": _git_head(),
        "status": "preflight_ready" if ready else "blocked_preflight",
        "decision": (
            "explicit runtime-domain confirmation configuration prepared; no solver execution"
            if ready
            else "configuration preflight blocked; no solver execution"
        ),
        "errors": errors,
        "execution_policy": {
            "mode": "preflight_only",
            "solver_invocations": 0,
            "gencase_invocations": 0,
            "partvtk_invocations": 0,
            "shared_resume_state_modified": False,
            "new_solver_execution": False,
            "historical_execution_reused_as_new": False,
            "qualification_claim": "none",
        },
        "provenance": {
            "execution_origin": "fresh_confirmation_not_started",
            "historical_artifacts_are_read_only": True,
            "legacy": lineage,
            "fresh_case_id": FRESH_CASE_ID,
            "fresh_recipe_id": FRESH_RECIPE_ID,
            "fresh_lineage_group_id": FRESH_LINEAGE_ID,
            "fresh_paired_background_id": FRESH_BACKGROUND_ID,
            "fresh_attempt_id_required": "must differ from legacy attempt_id and be recorded in a new attempt.json",
        },
        "configuration": configuration or {
            "source": file_evidence(Path(source_xml)),
            "configured": file_evidence(Path(configured_xml)),
            "runtime_domain": target_domain,
        },
        "runtime_domain_contract": {
            "historical_resolved_domain": historical,
            "proposed_explicit_domain": target_domain,
            "delta_from_historical_m": expansion,
            "historical_last_valid_missing_max_z_m": lineage["historical_last_valid_missing_max_z_m"],
            "physical_semantics": "numerical runtime-domain change only; do not close the physical top/open face",
            "required_post_run_check": "Run.out MapRealPos(final) must show the expanded numerical domain, not the old default +75% ceiling",
        },
        "identity_reconciliation_contract": {
            "join_key": "particle_id == PartOut.Idp",
            "native_reason_source": "RunPARTs.csv NpOut/NpOutPos/NpOutRho/NpOutMov joined by PartOut.PartOut",
            "required_runparts_columns": list(REQUIRED_RUNPARTS_COLUMNS),
            "required_partout_columns": list(REQUIRED_PARTOUT_COLUMNS),
            "required_hdf5_datasets": list(REQUIRED_HDF5_DATASETS),
            "hard_rules": [
                "RunPARTs total NpOut equals PartOut row count when exclusions exist",
                "PartOut Idp set equals HDF5 initial identities missing at final; no duplicates or unknown IDs",
                "PartOut.PartOut references a RunPARTs row and its native reason counters",
                "HDF5 active position/velocity/mass values are finite and mass is positive",
                "HDF5 identity lifecycle has no resurrection after invalidation",
                "zero-exclusion runs must record RunPARTs totals of zero and may explicitly report no PartOut rows",
            ],
            "missing_partout_policy": "blocked when HDF5 loses identities or RunPARTs reports exclusions; never infer a pass from HDF5 alone",
        },
        "fresh_execution_contract": {
            "solver_entrypoint": "not implemented in this preflight tool",
            "single_card_required": True,
            "one_new_attempt_directory": str((CAMPAIGN / "runs" / FRESH_CASE_ID / "attempts").resolve()),
            "must_record": ["attempt.json", "Run.out", "RunPARTs.csv", "data/PartOut_*.obi4", "normalized HDF5"],
            "do_not_reuse": [
                str((CAMPAIGN / "runs" / LEGACY_CASE_ID).resolve()),
                str((CAMPAIGN / "c3-canary" / "data" / f"{LEGACY_CASE_ID}.h5").resolve()),
                LEGACY_ATTEMPT_ID,
            ],
            "post_run_audit_command": (
                "scripts/l2_f5r_confirmation.py audit --attempt-dir <fresh-attempt> "
                "--hdf5 <fresh-normalized.h5> --partout-csv <PartOut-export.csv> "
                "--generated-xml <fresh-generated.xml>"
            ),
        },
        "next_action": (
            "Owner reviews the explicit XML, runs exactly one guarded single-GPU fresh attempt with F5R case/recipe IDs, "
            "exports PartOut via PartVTKOut, then runs the read-only audit command."
        ),
    }
    _atomic_json(Path(output_report), report)
    report["report"] = file_evidence(Path(output_report))
    _atomic_json(Path(output_report), report)
    return report


def _number(value: Any) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(str(value).strip().replace(",", ""))
    except ValueError:
        return None


def _integer(value: Any) -> int | None:
    number = _number(value)
    return None if number is None else int(number)


def _normalise_csv_row(row: dict[Any, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in row.items():
        if key is None:
            continue
        clean = str(key).strip().lstrip("\ufeff").rstrip(",")
        result[clean] = value
    return result


def _csv_key(row: dict[str, Any], *names: str) -> Any:
    by_lower = {key.lower(): value for key, value in row.items()}
    for name in names:
        if name.lower() in by_lower:
            return by_lower[name.lower()]
    return None


def parse_runparts(path: Path) -> dict[str, Any]:
    """Parse native exclusion counters without inferring particle identity."""

    path = Path(path)
    if not path.is_file():
        return {"status": "missing", "path": _repo_relative(path), "rows": [], "errors": ["missing_file"]}
    lines = path.read_text(errors="replace").splitlines()
    header_index = next(
        (index for index, line in enumerate(lines) if line.strip().startswith("Part;")),
        None,
    )
    if header_index is None:
        return {"status": "malformed", "path": _repo_relative(path), "rows": [], "errors": ["missing_header"]}
    reader = csv.DictReader(lines[header_index:], delimiter=";")
    header = [str(value).strip() for value in (reader.fieldnames or [])]
    missing_columns = [column for column in REQUIRED_RUNPARTS_COLUMNS if column not in header]
    if missing_columns:
        return {
            "status": "malformed",
            "path": _repo_relative(path),
            "rows": [],
            "columns": header,
            "errors": [f"missing_column:{column}" for column in missing_columns],
        }
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for raw in reader:
        row = _normalise_csv_row(raw)
        # RunPARTs appends comment/summary lines after the tabular section.
        # They are not malformed data rows and must not poison an otherwise
        # exact native-counter/PartOut/HDF5 identity join.
        raw_part = _csv_key(row, "Part")
        if raw_part is None or str(raw_part).strip().startswith("#"):
            continue
        part = _integer(_csv_key(row, "Part"))
        time_s = _number(_csv_key(row, "TimeStep [s]"))
        values = {
            "np_out": _integer(_csv_key(row, "NpOut")),
            "np_out_pos": _integer(_csv_key(row, "NpOutPos")),
            "np_out_rho": _integer(_csv_key(row, "NpOutRho")),
            "np_out_mov": _integer(_csv_key(row, "NpOutMov")),
        }
        if part is None or time_s is None or any(value is None for value in values.values()):
            errors.append("malformed_row")
            continue
        if any(int(value) < 0 for value in values.values()):
            errors.append(f"negative_counter:part={part}")
            continue
        rows.append({"part": part, "time_s": time_s, **{key: int(value) for key, value in values.items()}})
    totals = {
        key: sum(row[key] for row in rows)
        for key in ("np_out", "np_out_pos", "np_out_rho", "np_out_mov")
    }
    first_nonzero = {
        key: next(
            ({"part": row["part"], "time_s": row["time_s"], "count": row[key]} for row in rows if row[key] > 0),
            None,
        )
        for key in ("np_out", "np_out_pos", "np_out_rho", "np_out_mov")
    }
    return {
        "status": "available" if not errors else "available_with_findings",
        "path": _repo_relative(path),
        "file": file_evidence(path),
        "columns": header,
        "rows": rows,
        "totals": totals,
        "first_nonzero": first_nonzero,
        "errors": errors,
    }


def parse_partout_csv(path: Path, runparts: dict[str, Any] | None = None) -> dict[str, Any]:
    """Parse a PartVTKOut CSV and attach native RunPARTs reason labels."""

    path = Path(path)
    if not path.is_file():
        return {"status": "missing", "path": _repo_relative(path), "rows": [], "errors": ["missing_file"]}
    text = path.read_text(errors="replace")
    first_line = next((line for line in text.splitlines() if line.strip()), "")
    delimiter = ";" if first_line.count(";") > first_line.count(",") else ","
    reader = csv.DictReader(text.splitlines(), delimiter=delimiter)
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    runpart_by_part = {
        int(row["part"]): row for row in (runparts or {}).get("rows", []) if "part" in row
    }
    for raw in reader:
        row = _normalise_csv_row(raw)
        particle_id = _integer(_csv_key(row, "Idp", "IDp", "Id"))
        part_out = _integer(_csv_key(row, "PartOut", "Part Out"))
        if particle_id is None or part_out is None:
            errors.append("malformed_row")
            continue
        native = runpart_by_part.get(part_out)
        reason_counts = {
            "position": int(native["np_out_pos"]) if native else 0,
            "density": int(native["np_out_rho"]) if native else 0,
            "movement": int(native["np_out_mov"]) if native else 0,
        }
        active_reasons = [name for name, count in reason_counts.items() if count]
        native_reason = active_reasons[0] if len(active_reasons) == 1 else (
            "multiple" if active_reasons else "unknown"
        )
        rows.append({
            "particle_id": particle_id,
            "part_out": part_out,
            "motive": _integer(_csv_key(row, "Motive")),
            "position_m": [_number(_csv_key(row, f"Pos.{axis} [m]")) for axis in "xyz"],
            "velocity_m_s": [_number(_csv_key(row, f"Vel.{axis} [m/s]")) for axis in "xyz"],
            "density_kg_m3": _number(_csv_key(row, "Rhop [kg/m^3]")),
            "native_reason": native_reason,
            "native_reason_counters": reason_counts,
        })
    ids = [int(row["particle_id"]) for row in rows]
    duplicates = sorted(value for value, count in Counter(ids).items() if count > 1)
    reason_counts = Counter(str(row["native_reason"]) for row in rows)
    return {
        "status": "available" if not errors else "available_with_findings",
        "path": _repo_relative(path),
        "file": file_evidence(path),
        "delimiter": delimiter,
        "rows": rows,
        "particle_ids": ids,
        "duplicate_particle_ids": duplicates,
        "reason_counts": dict(reason_counts),
        "errors": errors,
    }


def audit_hdf5_identity(path: Path) -> dict[str, Any]:
    """Audit normalized HDF5 lifecycle/finite state without editing the file."""

    path = Path(path)
    base: dict[str, Any] = {"path": _repo_relative(path), "file": file_evidence(path)}
    if not path.is_file():
        return {**base, "status": "missing", "errors": ["missing_file"]}
    try:
        with h5py.File(path, "r") as handle:
            missing = [name for name in REQUIRED_HDF5_DATASETS if name not in handle]
            if missing:
                return {**base, "status": "malformed", "errors": [f"missing_dataset:{name}" for name in missing]}
            time_axis = np.asarray(handle["time"][:], dtype=np.float64)
            valid = np.asarray(handle["valid"][:], dtype=bool)
            particle_id = np.asarray(handle["particle_id"][:], dtype=np.int64)
            position = np.asarray(handle["position"][:], dtype=np.float64)
            velocity = np.asarray(handle["velocity"][:], dtype=np.float64)
            mass = np.asarray(handle["mass"][:], dtype=np.float64)
            attrs = {str(key): str(value) for key, value in handle.attrs.items()}
    except (OSError, ValueError) as error:
        return {**base, "status": "malformed", "errors": [f"read_error:{error.__class__.__name__}:{error}"]}

    shape_ok = (
        time_axis.ndim == 1
        and valid.ndim == 2
        and position.shape == (*valid.shape, 3)
        and velocity.shape == (*valid.shape, 3)
        and mass.shape in (valid.shape, (valid.shape[1],))
        and len(time_axis) == valid.shape[0]
        and len(particle_id) == valid.shape[1]
    )
    if not shape_ok:
        return {
            **base,
            "status": "malformed",
            "errors": ["trajectory_shape_mismatch"],
            "shapes": {
                "time": list(time_axis.shape),
                "valid": list(valid.shape),
                "position": list(position.shape),
                "velocity": list(velocity.shape),
                "mass": list(mass.shape),
                "particle_id": list(particle_id.shape),
            },
        }

    mass_frames = np.broadcast_to(mass, valid.shape) if mass.ndim == 1 else mass
    initial_valid = valid[0]
    final_valid = valid[-1]
    missing_final = initial_valid & ~final_valid
    missing_indices = np.flatnonzero(missing_final)
    # A particle may be absent in initial padding, but an initially valid
    # identity must never return after its first invalid state.
    seen_invalid = np.zeros(valid.shape[1], dtype=bool)
    resurrection_count = 0
    for frame in range(valid.shape[0]):
        if frame:
            resurrection_count += int(np.sum(seen_invalid & ~valid[frame - 1] & valid[frame]))
        seen_invalid |= initial_valid & ~valid[frame]
    first_missing_times: list[float] = []
    last_positions: list[np.ndarray] = []
    for index in missing_indices:
        invalid_frames = np.flatnonzero(~valid[:, index])
        first_invalid = int(invalid_frames[0])
        first_missing_times.append(float(time_axis[first_invalid]))
        previous = max(0, first_invalid - 1)
        last_positions.append(position[previous, index])
    last_position_array = np.asarray(last_positions, dtype=np.float64) if last_positions else np.empty((0, 3))
    initial_ids = particle_id[initial_valid]
    final_ids = particle_id[final_valid]
    active_position_finite = bool(np.isfinite(position[valid]).all())
    active_velocity_finite = bool(np.isfinite(velocity[valid]).all())
    active_mass_finite = bool(np.isfinite(mass_frames[valid]).all())
    active_mass_positive = bool((mass_frames[valid] > 0).all())
    time_strictly_increasing = bool(len(time_axis) >= 1 and np.isfinite(time_axis).all() and np.all(np.diff(time_axis) > 0))
    initial_id_hash = hashlib.sha256(",".join(str(int(value)) for value in sorted(initial_ids)).encode()).hexdigest()
    return {
        **base,
        "status": "available",
        "attrs": attrs,
        "frame_count": int(valid.shape[0]),
        "particle_count": int(valid.shape[1]),
        "time_start_s": float(time_axis[0]) if len(time_axis) else None,
        "time_end_s": float(time_axis[-1]) if len(time_axis) else None,
        "identity_key": "particle_id",
        "initial_valid_count": int(initial_valid.sum()),
        "final_valid_count": int(final_valid.sum()),
        "missing_initial_identity_count_at_final": int(missing_final.sum()),
        "missing_particle_ids": [int(value) for value in particle_id[missing_indices]],
        "missing_particle_ids_hash": hashlib.sha256(",".join(str(int(value)) for value in particle_id[missing_indices]).encode()).hexdigest(),
        "initial_identity_set_hash": initial_id_hash,
        "initial_identity_unique": len(np.unique(initial_ids)) == len(initial_ids),
        "final_identity_unique": len(np.unique(final_ids)) == len(final_ids),
        "time_strictly_increasing": time_strictly_increasing,
        "active_position_finite": active_position_finite,
        "active_velocity_finite": active_velocity_finite,
        "active_mass_finite": active_mass_finite,
        "active_mass_positive": active_mass_positive,
        "resurrection_count": resurrection_count,
        "last_valid_missing_max_z_m": float(np.nanmax(last_position_array[:, 2])) if len(last_position_array) else None,
        "first_missing_time_s": min(first_missing_times) if first_missing_times else None,
        "hard_structural_pass": bool(
            time_strictly_increasing
            and len(np.unique(initial_ids)) == len(initial_ids)
            and len(np.unique(final_ids)) == len(final_ids)
            and active_position_finite
            and active_velocity_finite
            and active_mass_finite
            and active_mass_positive
            and resurrection_count == 0
        ),
    }


def _reason_names(row: dict[str, Any]) -> list[str]:
    return [
        name
        for name, key in (("position", "np_out_pos"), ("density", "np_out_rho"), ("movement", "np_out_mov"))
        if int(row.get(key, 0)) > 0
    ]


def reconcile_identity_ledger(
    *,
    runparts: dict[str, Any],
    partout: dict[str, Any],
    hdf5: dict[str, Any],
) -> dict[str, Any]:
    """Join native counters, PartOut identities, and HDF5 lifecycle IDs."""

    if hdf5.get("status") != "available":
        return {"status": "blocked", "errors": ["hdf5_not_available"]}
    if runparts.get("status") not in {"available", "available_with_findings"}:
        return {"status": "blocked", "errors": ["runparts_not_available"]}
    missing_ids = set(int(value) for value in hdf5.get("missing_particle_ids", []))
    runpart_rows = {int(row["part"]): row for row in runparts.get("rows", [])}
    totals = runparts.get("totals", {})
    partout_rows = list(partout.get("rows", [])) if partout.get("status", "").startswith("available") else []
    partout_ids = [int(row["particle_id"]) for row in partout_rows]
    partout_id_set = set(partout_ids)
    duplicate_ids = sorted(value for value, count in Counter(partout_ids).items() if count > 1)
    unknown_ids = sorted(partout_id_set - set(int(value) for value in hdf5.get("missing_particle_ids", [])))
    missing_from_partout = sorted(missing_ids - partout_id_set)
    part_unknown = sorted({int(row["part_out"]) for row in partout_rows} - set(runpart_rows))
    part_overflow: dict[str, int] = {}
    reason_join_errors: list[str] = []
    joined_reason_counts: Counter[str] = Counter()
    for part, native in runpart_rows.items():
        part_rows = [row for row in partout_rows if int(row["part_out"]) == part]
        native_total = int(native["np_out"])
        if len(part_rows) > native_total:
            part_overflow[str(part)] = len(part_rows)
        reasons = _reason_names(native)
        if len(reasons) == 1 and len(part_rows) != int(native["np_out_" + {"position": "pos", "density": "rho", "movement": "mov"}[reasons[0]]]):
            reason_join_errors.append(f"part_{part}_{reasons[0]}_count_mismatch")
        for row in part_rows:
            joined_reason_counts[str(row["native_reason"])] += 1
    runparts_total = int(totals.get("np_out", 0))
    exact_identity_set = not missing_from_partout and not unknown_ids and not duplicate_ids
    reason_totals = {
        "position": int(totals.get("np_out_pos", 0)),
        "density": int(totals.get("np_out_rho", 0)),
        "movement": int(totals.get("np_out_mov", 0)),
    }
    if missing_ids:
        partout_available = partout.get("status", "").startswith("available")
        checks = {
            "partout_required_and_available": partout_available,
            "runparts_parse_errors_absent": not runparts.get("errors"),
            "partout_parse_errors_absent": not partout.get("errors"),
            "runparts_total_matches_partout_rows": runparts_total == len(partout_rows),
            "hdf5_missing_ids_equal_partout_ids": exact_identity_set,
            "partout_parts_reference_runparts": not part_unknown,
            "partout_rows_do_not_exceed_native_part_counts": not part_overflow,
            "reason_join_is_consistent": not reason_join_errors,
            "runparts_has_nonzero_exclusion": runparts_total > 0,
        }
        status = "pass" if all(checks.values()) else "failed"
    else:
        checks = {
            "hdf5_has_no_finally_missing_initial_ids": True,
            "runparts_parse_errors_absent": not runparts.get("errors"),
            "runparts_reports_zero_exclusions": runparts_total == 0,
            "no_unexpected_partout_rows": not partout_rows,
            "no_resurrection": int(hdf5.get("resurrection_count", 0)) == 0,
        }
        status = "pass" if all(checks.values()) else "failed"
    return {
        "status": status,
        "checks": checks,
        "hdf5_missing_identity_count": len(missing_ids),
        "runparts_total_np_out": runparts_total,
        "partout_row_count": len(partout_rows),
        "partout_particle_id_count": len(partout_id_set),
        "missing_ids_not_in_partout": missing_from_partout,
        "unknown_partout_ids": unknown_ids,
        "duplicate_partout_ids": duplicate_ids,
        "unknown_partout_parts": part_unknown,
        "partout_part_overflow": part_overflow,
        "reason_join_errors": reason_join_errors,
        "runparts_reason_totals": reason_totals,
        "partout_joined_reason_counts": dict(joined_reason_counts),
        "join_key": "particle_id == PartOut.Idp",
        "native_reason_join": "PartOut.PartOut -> RunPARTs.Part -> NpOut* counters",
    }


def parse_solver_runtime_domain(path: Path) -> dict[str, Any]:
    path = Path(path)
    if not path.is_file():
        return {"status": "missing", "path": _repo_relative(path), "errors": ["missing_file"]}
    text = path.read_text(errors="replace")
    match = re.search(r"MapRealPos\(final\)=\(([^)]+)\)-\(([^)]+)\)", text)
    if not match:
        return {"status": "missing_in_log", "path": _repo_relative(path), "file": file_evidence(path)}
    try:
        lower = [float(value.strip()) for value in match.group(1).split(",")]
        upper = [float(value.strip()) for value in match.group(2).split(",")]
    except ValueError:
        return {"status": "malformed", "path": _repo_relative(path), "errors": ["malformed_MapRealPos"]}
    if len(lower) != 3 or len(upper) != 3 or not all(math.isfinite(value) for value in lower + upper):
        return {"status": "malformed", "path": _repo_relative(path), "errors": ["nonfinite_MapRealPos"]}
    return {
        "status": "available",
        "path": _repo_relative(path),
        "file": file_evidence(path),
        "lower": lower,
        "upper": upper,
        "finished_code_0": "Finished execution (code=0)" in text,
        "excluded_particles": (
            int(match.group(1).replace(",", ""))
            if (match := re.search(r"Excluded particles\.*:\s*([0-9,]+)", text))
            else None
        ),
    }


def inspect_attempt_freshness(attempt_dir: Path) -> dict[str, Any]:
    """Reject the known C3 attempt and require a separately named fresh run."""

    attempt_dir = Path(attempt_dir)
    manifest_path = attempt_dir / "attempt.json"
    result: dict[str, Any] = {
        "attempt_directory": str(attempt_dir.resolve()),
        "attempt_manifest": file_evidence(manifest_path),
        "fresh_attempt": False,
        "historical_execution_reused_as_new": False,
        "checks": {},
        "errors": [],
    }
    if not manifest_path.is_file():
        result["errors"].append("missing_attempt_json")
        return result
    try:
        payload = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        result["errors"].append(f"attempt_json:{error.__class__.__name__}")
        return result
    attempt_id = str(payload.get("attempt_id") or "")
    command = [str(value) for value in payload.get("command", [])]
    gpu_tokens = [value for value in command if value.startswith("-gpu:")]
    checks = {
        "case_id_is_fresh_f5r_id": payload.get("case_id") == FRESH_CASE_ID,
        "attempt_id_present": bool(attempt_id),
        "attempt_id_differs_from_legacy": attempt_id != LEGACY_ATTEMPT_ID,
        "manifest_status_completed": payload.get("status") == "completed",
        "returncode_zero": payload.get("returncode") == 0,
        "single_gpu_argument_recorded": len(gpu_tokens) == 1,
        "attempt_directory_matches_id": attempt_id in attempt_dir.name,
    }
    result.update({
        "payload": payload,
        "attempt_id": attempt_id,
        "checks": checks,
        "historical_execution_reused_as_new": attempt_id == LEGACY_ATTEMPT_ID,
        "fresh_attempt": all(checks.values()),
    })
    if not result["fresh_attempt"]:
        result["errors"].extend(key for key, value in checks.items() if not value)
    return result


def build_audit(
    *,
    attempt_dir: Path,
    hdf5_path: Path,
    runparts_path: Path | None = None,
    partout_csv: Path | None = None,
    run_log: Path | None = None,
    generated_xml: Path | None = None,
    preflight_report: Path | None = None,
    output_report: Path = DEFAULT_AUDIT,
) -> dict[str, Any]:
    """Audit a completed fresh attempt; never launches or mutates solver state."""

    attempt_dir = Path(attempt_dir)
    runparts_path = Path(runparts_path) if runparts_path else attempt_dir / "RunPARTs.csv"
    run_log = Path(run_log) if run_log else attempt_dir / "Run.out"
    freshness = inspect_attempt_freshness(attempt_dir)
    runparts = parse_runparts(runparts_path)
    partout = parse_partout_csv(Path(partout_csv), runparts) if partout_csv else {
        "status": "missing",
        "path": None,
        "rows": [],
        "errors": ["partout_csv_not_supplied; export PartOut via PartVTKOut before audit"],
    }
    hdf5 = audit_hdf5_identity(Path(hdf5_path))
    identity = reconcile_identity_ledger(runparts=runparts, partout=partout, hdf5=hdf5)
    solver_domain = parse_solver_runtime_domain(run_log)
    generated_domain = read_runtime_domain(Path(generated_xml)) if generated_xml else {
        "status": "missing",
        "path": None,
        "errors": ["generated_xml_not_supplied"],
    }
    planned_domain = dict(F5R_RUNTIME_DOMAIN)
    if preflight_report and Path(preflight_report).is_file():
        try:
            payload = json.loads(Path(preflight_report).read_text())
            planned_domain = dict(payload["runtime_domain_contract"]["proposed_explicit_domain"])
        except (OSError, KeyError, TypeError, json.JSONDecodeError):
            pass
    historical = dict(HISTORICAL_RUNTIME_DOMAIN)
    actual_domain = solver_domain.get("upper") if solver_domain.get("status") == "available" else None
    generated_values = generated_domain.get("domain") if generated_domain.get("status") == "explicit" else None
    runtime_checks = {
        "generated_definition_all_faces_explicit": generated_values is not None,
        "generated_definition_zmax_matches_or_exceeds_plan": bool(
            generated_values is not None and float(generated_values["zmax"]) >= float(planned_domain["zmax"]) - 0.02
        ),
        "solver_log_runtime_domain_available": actual_domain is not None,
        "solver_log_zmax_expanded_above_historical": bool(
            actual_domain is not None and float(actual_domain[2]) > float(historical["zmax"])
        ),
        "solver_log_zmax_matches_or_exceeds_plan": bool(
            actual_domain is not None and float(actual_domain[2]) >= float(planned_domain["zmax"]) - 0.02
        ),
        "solver_log_finished_code_0": solver_domain.get("finished_code_0") is True,
    }
    hard_checks = {
        "fresh_attempt_provenance": bool(freshness.get("fresh_attempt")),
        "runtime_domain_contract": all(runtime_checks.values()),
        "hdf5_hard_structural_pass": hdf5.get("hard_structural_pass") is True,
        "runparts_partout_hdf5_identity_reconciled": identity.get("status") == "pass",
    }
    evidence_present = (
        runparts.get("status") in {"available", "available_with_findings"}
        and hdf5.get("status") in {"available", "available_with_findings"}
        and solver_domain.get("status") in {"available", "available_with_findings"}
        and generated_domain.get("status") == "explicit"
    )
    if not freshness.get("fresh_attempt"):
        status = "blocked_provenance"
    elif not evidence_present:
        status = "blocked_missing_evidence"
    else:
        status = "complete_with_findings"
    report = {
        "schema": "l2.f5r.confirmation.v1",
        "stage": "F5R",
        "created_at_utc": utc_now(),
        "current_commit": _git_head(),
        "status": status,
        "decision": (
            "fresh attempt audited; no qualification claim; inspect hard checks before any downstream use"
            if status == "complete_with_findings"
            else "fresh confirmation cannot be accepted from the supplied evidence"
        ),
        "execution_policy": {
            "mode": "read_only_post_run_audit",
            "solver_invocations_by_this_entrypoint": 0,
            "gencase_invocations_by_this_entrypoint": 0,
            "partvtk_invocations_by_this_entrypoint": 0,
            "shared_resume_state_modified": False,
            "observed_fresh_attempt": bool(freshness.get("fresh_attempt")),
            "new_solver_execution": bool(freshness.get("fresh_attempt")),
            "historical_execution_reused_as_new": bool(freshness.get("historical_execution_reused_as_new")),
            "qualification_claim": "none; F5R confirmation audit only",
        },
        "provenance": {
            "legacy_case_id": LEGACY_CASE_ID,
            "legacy_attempt_id": LEGACY_ATTEMPT_ID,
            "fresh_case_id_required": FRESH_CASE_ID,
            "fresh_recipe_id": FRESH_RECIPE_ID,
            "freshness": freshness,
            "preflight_report": file_evidence(Path(preflight_report)) if preflight_report else None,
        },
        "runtime_domain": {
            "historical_resolved_domain": historical,
            "planned_explicit_domain": planned_domain,
            "generated_definition": generated_domain,
            "solver_log": solver_domain,
            "checks": runtime_checks,
        },
        "artifacts": {
            "attempt": file_evidence(attempt_dir / "attempt.json"),
            "runparts": file_evidence(runparts_path),
            "partout_csv": file_evidence(Path(partout_csv)) if partout_csv else None,
            "hdf5": file_evidence(Path(hdf5_path)),
            "run_log": file_evidence(run_log),
            "generated_xml": file_evidence(Path(generated_xml)) if generated_xml else None,
        },
        "runparts": runparts,
        "partout": partout,
        "hdf5": hdf5,
        "identity_reconciliation": identity,
        "hard_checks": hard_checks,
        "qualification_boundary": (
            "A fresh identity/domain audit is not a family qualification receipt; physical run-up, overtopping, "
            "return-flow and reference/T2 gates remain separate."
        ),
    }
    _atomic_json(Path(output_report), report)
    report["report"] = file_evidence(Path(output_report))
    _atomic_json(Path(output_report), report)
    return report


def _path(raw: str | None, default: Path | None = None) -> Path | None:
    if raw is None:
        return default
    value = Path(raw).expanduser()
    return value if value.is_absolute() else Path.cwd() / value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command")
    preflight = subparsers.add_parser("preflight", help="write explicit-domain configuration; never launch solver")
    preflight.add_argument("--source-definition", default=str(LEGACY_DEFINITION))
    preflight.add_argument("--configured-xml", default=str(DEFAULT_XML))
    preflight.add_argument("--output", default=str(DEFAULT_PREFLIGHT))
    preflight.add_argument("--runtime-zmax", type=float, default=F5R_RUNTIME_DOMAIN["zmax"])

    audit = subparsers.add_parser("audit", help="read-only audit of a completed fresh attempt")
    audit.add_argument("--attempt-dir", required=True)
    audit.add_argument("--hdf5", required=True)
    audit.add_argument("--runparts")
    audit.add_argument("--partout-csv")
    audit.add_argument("--run-log")
    audit.add_argument("--generated-xml")
    audit.add_argument("--preflight-report")
    audit.add_argument("--output", default=str(DEFAULT_AUDIT))

    args = parser.parse_args(argv)
    command = args.command or "preflight"
    if command == "preflight":
        domain = dict(F5R_RUNTIME_DOMAIN)
        domain["zmax"] = getattr(args, "runtime_zmax", F5R_RUNTIME_DOMAIN["zmax"])
        report = build_preflight(
            source_xml=Path(getattr(args, "source_definition", str(LEGACY_DEFINITION))),
            configured_xml=Path(getattr(args, "configured_xml", str(DEFAULT_XML))),
            output_report=Path(getattr(args, "output", str(DEFAULT_PREFLIGHT))),
            runtime_domain=domain,
        )
    else:
        attempt_dir = Path(args.attempt_dir)
        report = build_audit(
            attempt_dir=attempt_dir,
            hdf5_path=Path(args.hdf5),
            runparts_path=Path(args.runparts) if args.runparts else None,
            partout_csv=Path(args.partout_csv) if args.partout_csv else None,
            run_log=Path(args.run_log) if args.run_log else None,
            generated_xml=Path(args.generated_xml) if args.generated_xml else None,
            preflight_report=Path(args.preflight_report) if args.preflight_report else None,
            output_report=Path(args.output),
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
