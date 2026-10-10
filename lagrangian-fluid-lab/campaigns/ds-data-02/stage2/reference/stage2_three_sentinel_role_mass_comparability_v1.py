#!/usr/bin/env python3
"""Compare three-grid role counts with native per-particle header masses.

This is a bounded metadata diagnostic for the ROOT719 retained-header output.
It does not read BI4, VTK, H5, Part arrays, generated products, or forcing
payloads.  ``MassFluid`` and ``MassBound`` are treated as per-particle header
values.  The products ``count * header_mass`` are explicitly labelled
header-implied diagnostics; they are not a continuous-owner integral and do
not grant QI/QN/QE.

The source manifest is used to prove the intended three-grid source/control
lineage.  It is still only a preflight: generated XML/products and the exact
parent-side F3 forcing copy remain deferred.  In particular, a staged F3
forcing record is not silently promoted to the canonical 14.9 MB forcing
source.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import tempfile
from typing import Any


CAP = 10 * 1024 * 1024
HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
HEADER_SCHEMA = "ds02.stage2.native-header-probe.reparsed.v1"
SOURCE_SCHEMA = "ds02.stage2.three-sentinel.owner-grid-source-manifest.v3"
SOURCE_STATUS = "PREPARED_SOURCE_OWNER_GRID_AUDIT_V3"
OUT_SCHEMA = "ds02.stage2.three-sentinel.role-mass-comparability.v1"
TARGETS = ("F2-S2", "F3-S1", "F5-S1")
GRIDS = ("original", "coarse", "fine")
ROW_KEYS = {f"{sid}:{grid}" for sid in TARGETS for grid in GRIDS}
NO_CREDIT = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "scientific_credit": 0}
PYTHON = "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python"


class RoleMassFailure(RuntimeError):
    pass


def _abs(path: str | Path) -> Path:
    return Path(path).expanduser().absolute()


def _stat(path: Path) -> dict[str, int]:
    st = path.stat()
    return {
        "device": int(st.st_dev),
        "inode": int(st.st_ino),
        "bytes": int(st.st_size),
        "mtime_ns": int(st.st_mtime_ns),
        "ctime_ns": int(st.st_ctime_ns),
    }


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _record(path: str | Path, label: str, *, read: bool = True) -> dict[str, Any]:
    path = _abs(path)
    if path.is_symlink() or not path.is_file():
        raise RoleMassFailure(f"{label} is not a regular file: {path}")
    before = _stat(path)
    # A deferred forcing/control may legitimately exceed the 10 MiB read cap.
    # It is allowed here only as stat-only metadata; any bounded byte read
    # remains capped.
    if read and before["bytes"] > CAP:
        raise RoleMassFailure(f"{label} exceeds the 10 MiB metadata cap: {path}")
    if read:
        raw = path.read_bytes()
        after = _stat(path)
        if before != after or len(raw) != before["bytes"]:
            raise RoleMassFailure(f"{label} changed during bounded read: {path}")
        digest = _sha(raw)
    else:
        after = _stat(path)
        if before != after:
            raise RoleMassFailure(f"{label} changed during stat-only read: {path}")
        digest = None
    return {
        "path": str(path),
        "sha256": digest,
        "bytes": before["bytes"],
        "stat": after,
        "read_scope": "bounded_small_source_bytes" if read else "stat_only_deferred_payload",
    }


def _json(path: str | Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _abs(path)
    if path.is_symlink() or not path.is_file():
        raise RoleMassFailure(f"{label} is not a regular file: {path}")
    before = _stat(path)
    if before["bytes"] > CAP:
        raise RoleMassFailure(f"{label} exceeds the 10 MiB metadata cap: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    if before != after or len(raw) != before["bytes"]:
        raise RoleMassFailure(f"{label} changed during bounded read: {path}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RoleMassFailure(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise RoleMassFailure(f"{label} must be a JSON object")
    return value, {"path": str(path), "sha256": _sha(raw), "bytes": len(raw),
                   "stat": after, "read_scope": "bounded_small_metadata"}


def _declared_record(value: Any, label: str, *, read: bool) -> dict[str, Any]:
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        raise RoleMassFailure(f"{label} has no path record")
    rec = _record(value["path"], label, read=read)
    declared = value.get("sha256")
    if read:
        if not isinstance(declared, str) or not HEX64.fullmatch(declared):
            raise RoleMassFailure(f"{label} lacks a declared SHA")
        if rec["sha256"].lower() != declared.lower():
            raise RoleMassFailure(f"{label} SHA differs from source manifest")
    elif isinstance(declared, str) and HEX64.fullmatch(declared):
        rec["declared_sha256"] = declared
    return rec


def _finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise RoleMassFailure(f"{label} is boolean")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise RoleMassFailure(f"{label} is not numeric") from exc
    if not math.isfinite(result):
        raise RoleMassFailure(f"{label} is non-finite")
    return result


def _integer(value: Any, label: str) -> int:
    result = _finite_number(value, label)
    if result != int(result):
        raise RoleMassFailure(f"{label} is not integral")
    if result < 0:
        raise RoleMassFailure(f"{label} is negative")
    return int(result)


def _validate_header_report(report: dict[str, Any], report_record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if report.get("schema") != HEADER_SCHEMA:
        raise RoleMassFailure(f"unexpected header report schema: {report.get('schema')!r}")
    if report.get("status") != "COMPLETE_RETAINED_DECODER_XML_HEADER_REPARSE_DIAGNOSTIC":
        raise RoleMassFailure("header report is not a completed retained-XML reparse")
    if report.get("native_payload_reread") is not False or report.get("xml_mass_is_not_native") is not True:
        raise RoleMassFailure("header report read-scope or mass semantics are not strict")
    rows = report.get("cases")
    if not isinstance(rows, list) or {r.get("row_key") for r in rows if isinstance(r, dict)} != ROW_KEYS:
        raise RoleMassFailure("header report does not contain the exact nine row keys")
    by_key: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("row_key") not in ROW_KEYS:
            raise RoleMassFailure("malformed header row")
        if row.get("status") != "PASS_NATIVE_HEADER_FIELDS_REPARSED_FROM_RETAINED_DECODER_XML":
            raise RoleMassFailure(f"{row.get('row_key')} is not a retained-header success")
        if row.get("mass_semantics") != "JPartDataHead_per_particle_header_value; not case_total":
            raise RoleMassFailure(f"{row.get('row_key')} has unsafe mass semantics")
        values = row.get("decoder_values")
        counts = row.get("role_counts")
        if not isinstance(values, dict) or not isinstance(counts, dict):
            raise RoleMassFailure(f"{row.get('row_key')} lacks values/counts")
        for name in ("Dp", "MassFluid", "MassBound"):
            _finite_number(values.get(name), f"{row['row_key']}.{name}")
        for name in ("total", "fixed", "moving", "floating", "fluid"):
            _integer(counts.get(name), f"{row['row_key']}.role_counts.{name}")
        total = _integer(counts["total"], f"{row['row_key']}.total")
        role_sum = sum(_integer(counts[name], f"{row['row_key']}.{name}") for name in ("fixed", "moving", "floating", "fluid"))
        if role_sum != total:
            raise RoleMassFailure(f"{row['row_key']} role counts do not sum to total")
        by_key[row["row_key"]] = row
    return by_key


def _validate_source_manifest(source: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    if source.get("schema") != SOURCE_SCHEMA or source.get("status") != SOURCE_STATUS:
        raise RoleMassFailure("source manifest schema/status mismatch")
    cases = source.get("cases")
    if not isinstance(cases, list) or {r.get("sentinel_id") for r in cases if isinstance(r, dict)} != set(TARGETS):
        raise RoleMassFailure("source manifest does not contain the exact three sentinels")
    by_sid: dict[str, dict[str, Any]] = {}
    for case in cases:
        sid = case.get("sentinel_id")
        if sid not in TARGETS or sid in by_sid:
            raise RoleMassFailure("duplicate or unknown sentinel in source manifest")
        _declared_record(case.get("source_xml"), f"{sid} source XML", read=True)
        _declared_record(case.get("source_def"), f"{sid} source Def", read=True)
        grids = case.get("grids")
        if not isinstance(grids, list) or {g.get("label") for g in grids if isinstance(g, dict)} != set(GRIDS):
            raise RoleMassFailure(f"{sid} source manifest lacks exact three grids")
        grid_rows: dict[str, dict[str, Any]] = {}
        control_records: dict[str, dict[str, Any]] = {}
        for grid in grids:
            label = grid.get("label")
            if label not in GRIDS:
                raise RoleMassFailure(f"{sid} has malformed grid")
            _declared_record(grid.get("candidate_def"), f"{sid}/{label} candidate Def", read=True)
            motion = grid.get("motion_or_forcing")
            if not isinstance(motion, dict) or not isinstance(motion.get("path"), str):
                raise RoleMassFailure(f"{sid}/{label} lacks motion/forcing record")
            # Controls are intentionally stat-only: F3's canonical 14.9 MB
            # forcing is deferred and must never be read by this builder.
            control_records[label] = _declared_record(motion, f"{sid}/{label} motion/forcing", read=False)
            grid_rows[label] = grid
        control_sha = {v.get("declared_sha256") for v in control_records.values()}
        source_control_same = len(control_sha) == 1 and None not in control_sha
        by_sid[sid] = {"case": case, "grids": grid_rows,
                       "control_records": control_records,
                       "source_control_same_within_grids": source_control_same,
                       "source_control_scope": "declared_SHA_only; payload_deferred"}
    return by_sid, {"source_control_equivalence": "within_sentinel_declared_SHA_only",
                    "canonical_control_identity": "UNKNOWN_UNTIL_PARENT_RUNTIME_BINDING",
                    "generated_geometry": "DEFERRED_PARENT_PRODUCTS"}


def _relative_spread(values: list[float]) -> float | None:
    if not values:
        return None
    scale = max(abs(v) for v in values)
    if scale == 0:
        return 0.0
    return (max(values) - min(values)) / scale


def build(header_report_path: Path, source_manifest_path: Path, output_dir: Path) -> dict[str, Any]:
    header, header_record = _json(header_report_path, "ROOT719 retained-header report")
    source, source_record = _json(source_manifest_path, "owner-grid source manifest")
    header_rows = _validate_header_report(header, header_record)
    source_rows, source_scope = _validate_source_manifest(source)
    cases: list[dict[str, Any]] = []
    for sid in TARGETS:
        rows: list[dict[str, Any]] = []
        for grid in GRIDS:
            key = f"{sid}:{grid}"
            h = header_rows[key]
            vals = h["decoder_values"]
            counts = h["role_counts"]
            fluid_n = int(counts["fluid"])
            bound_n = int(counts["fixed"]) + int(counts["moving"]) + int(counts["floating"])
            mf = float(vals["MassFluid"])
            mb = float(vals["MassBound"])
            rows.append({
                "row_key": key,
                "grid": grid,
                "dp_m": float(vals["Dp"]),
                "role_counts": {name: int(counts[name]) for name in ("total", "fluid", "fixed", "moving", "floating")},
                "header_mass_fluid_kg_per_particle": mf,
                "header_mass_bound_kg_per_particle": mb,
                "header_implied_fluid_mass_kg": fluid_n * mf,
                "header_implied_bound_mass_kg": bound_n * mb,
                "header_implied_total_role_mass_kg": fluid_n * mf + bound_n * mb,
                "mass_semantics": "per_particle_header_times_typed_role_count; diagnostic_only",
                "generated_product": "DEFERRED_PARENT_GUARD",
            })
        fluid_masses = [r["header_implied_fluid_mass_kg"] for r in rows]
        bound_masses = [r["header_implied_bound_mass_kg"] for r in rows]
        dp_values = [r["dp_m"] for r in rows]
        cases.append({
            "sentinel_id": sid,
            "grids": rows,
            "diagnostic_spread": {
                "fluid_implied_mass_relative_spread": _relative_spread(fluid_masses),
                "bound_implied_mass_relative_spread": _relative_spread(bound_masses),
                "dp_relative_spread": _relative_spread(dp_values),
            },
            "source_contract": {
                "source_xml": source_rows[sid]["case"]["source_xml"],
                "source_def": source_rows[sid]["case"]["source_def"],
                "candidate_defs": {g: source_rows[sid]["grids"][g]["candidate_def"] for g in GRIDS},
                "control_records": source_rows[sid]["control_records"],
                "control_same_within_grids": source_rows[sid]["source_control_same_within_grids"],
                "control_scope": source_rows[sid]["source_control_scope"],
            },
            "continuous_owner_mass_kg": "UNKNOWN_UNTIL_SOURCE_GEOMETRY_INTEGRAL",
            "owner_comparability": "SOURCE_PREFLIGHT_ONLY_GENERATED_GEOMETRY_DEFERRED",
        })
    value = {
        "schema": OUT_SCHEMA,
        "status": "READY_FOR_PARENT_GUARDED_ROLE_MASS_COMPARABILITY_DIAGNOSTIC",
        "source_report": header_record,
        "owner_source_manifest": source_record,
        "cases": cases,
        "source_scope": source_scope,
        "scientific_scope": {
            **NO_CREDIT,
            "native_header_mass": "per_particle_only",
            "continuous_owner": "UNKNOWN",
            "world_axis": "UNKNOWN",
            "generated_geometry": "DEFERRED",
            "no_xml_mass_fallback": True,
            "no_mass_rescale": True,
        },
        "read_scope": {
            "small_json": True,
            "small_source_xml_and_def": True,
            "motion_forcing_payload": False,
            "native_bi4": False,
            "vtk": False,
            "hdf5": False,
            "part_arrays": False,
            "solver_launch": False,
            "gencase_launch": False,
        },
    }
    output_dir = _abs(output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise RoleMassFailure(f"refusing non-empty output directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "role-mass-comparability-manifest-v1.json"
    request_path = output_dir / "role-mass-comparability-request-v1.json"
    manifest_path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    request = {
        "schema": "ds02.stage2.role-mass-comparability-request.v1",
        "status": "SOURCE_PREPARED_REQUIRES_PARENT_FORWARD_BINDING",
        "execution_allowed": False,
        "command_template": [PYTHON, str(Path(__file__).absolute()), "--run", "--manifest", "{root_forward_manifest_path}"],
        "manifest": {"path": str(manifest_path), "sha256": _sha(manifest_path.read_bytes()), "bytes": manifest_path.stat().st_size},
        "resource_scope": {"cpu_threads": 1, "memory_bytes": 2 * 1024**3, "timeout_seconds": 900,
                           "metadata_cap_bytes": CAP, "native_payload_reads": 0},
        "parent_requirements": [
            "ROOT719 retained-header report exact SHA/path join",
            "ROOT718 or equivalent F3 source-bound product lineage",
            "actual generated XML/BI4/VTK remain deferred to parent guard",
            "canonical F3 forcing path/SHA must be rebound after reservation",
        ],
        "scientific_scope": {**NO_CREDIT, "continuous_owner": "UNKNOWN", "Q_policy": "diagnostic_only"},
    }
    request_path.write_text(json.dumps(request, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return {"manifest": str(manifest_path), "request": str(request_path), "rows": 9,
            "status": value["status"], "execution_allowed": False}


def run(manifest_path: Path, output_path: Path) -> dict[str, Any]:
    manifest, record = _json(manifest_path, "role-mass comparability manifest")
    if manifest.get("schema") != OUT_SCHEMA:
        raise RoleMassFailure("unexpected role-mass manifest schema")
    if manifest.get("status") != "READY_FOR_PARENT_GUARDED_ROLE_MASS_COMPARABILITY_DIAGNOSTIC":
        raise RoleMassFailure("role-mass manifest is not source-prepared")
    output = dict(manifest)
    output["status"] = "COMPLETE_ROLE_MASS_COMPARABILITY_DIAGNOSTIC_NO_SCIENTIFIC_Q"
    output["manifest_record"] = record
    output["scientific_scope"] = {**manifest.get("scientific_scope", {}), **NO_CREDIT,
                                  "diagnostic_only": True}
    output_path = _abs(output_path)
    if output_path.exists() or output_path.is_symlink():
        raise RoleMassFailure(f"refusing to overwrite {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return output


def _self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="role-mass-comparability-") as td:
        root = Path(td)
        xml = root / "source.xml"; xml.write_text("<source/>\n", encoding="utf-8")
        deff = root / "source_Def.xml"; deff.write_text("<def/>\n", encoding="utf-8")
        control = root / "control.dat"; control.write_text("deferred\n", encoding="utf-8")
        def rec(p: Path) -> dict[str, Any]:
            raw = p.read_bytes(); st = _stat(p)
            return {"path": str(p), "sha256": _sha(raw), "stat_after": st}
        source_cases = []
        for sid in TARGETS:
            grids = []
            for grid in GRIDS:
                cand = root / f"{sid}-{grid}-Def.xml"; cand.write_text(f"<{sid}-{grid}/>\n", encoding="utf-8")
                grids.append({"label": grid, "candidate_def": rec(cand), "motion_or_forcing": rec(control)})
            source_cases.append({"sentinel_id": sid, "source_xml": rec(xml), "source_def": rec(deff), "grids": grids})
        source = {"schema": SOURCE_SCHEMA, "status": SOURCE_STATUS, "cases": source_cases}
        source_path = root / "source.json"; source_path.write_text(json.dumps(source), encoding="utf-8")
        header_cases = []
        for sid in TARGETS:
            for grid in GRIDS:
                header_cases.append({"row_key": f"{sid}:{grid}",
                                     "status": "PASS_NATIVE_HEADER_FIELDS_REPARSED_FROM_RETAINED_DECODER_XML",
                                     "mass_semantics": "JPartDataHead_per_particle_header_value; not case_total",
                                     "decoder_values": {"Dp": 0.01, "MassFluid": 0.0002, "MassBound": 0.0002},
                                     "role_counts": {"total": 12, "fluid": 4, "fixed": 8, "moving": 0, "floating": 0}})
        header = {"schema": HEADER_SCHEMA,
                  "status": "COMPLETE_RETAINED_DECODER_XML_HEADER_REPARSE_DIAGNOSTIC",
                  "native_payload_reread": False, "xml_mass_is_not_native": True,
                  "cases": header_cases}
        header_path = root / "header.json"; header_path.write_text(json.dumps(header), encoding="utf-8")
        result = build(header_path, source_path, root / "built")
        assert result["rows"] == 9 and result["execution_allowed"] is False
        request = json.loads((root / "built" / "role-mass-comparability-request-v1.json").read_text())
        assert request["scientific_scope"]["QI"] == "UNKNOWN"
        assert request["parent_requirements"][-1].startswith("canonical F3 forcing")
        print("PASS_ROLE_MASS_COMPARABILITY_V1_FIXTURE")


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build", action="store_true")
    mode.add_argument("--run", action="store_true")
    parser.add_argument("--header-report", type=Path)
    parser.add_argument("--source-manifest", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if args.self_test:
            _self_test()
            return 0
        if args.build:
            if not args.header_report or not args.source_manifest or not args.output_dir:
                parser.error("--build requires --header-report --source-manifest --output-dir")
            print(json.dumps(build(args.header_report, args.source_manifest, args.output_dir), sort_keys=True))
            return 0
        if not args.manifest or not args.output:
            parser.error("--run requires --manifest --output")
        result = run(args.manifest, args.output)
        print(json.dumps({"status": result["status"], "output": str(_abs(args.output))}, sort_keys=True))
        return 0
    except RoleMassFailure as exc:
        print(f"FAILED_ROLE_MASS_COMPARABILITY_V1: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
