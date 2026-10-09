#!/usr/bin/env python3
"""Build a field-grounded fourteen-sentinel dimension index.

The V2 catalog records which small proof was assigned to a dimension, but its
``actual``/``observed`` flags do not by themselves establish that a research
dimension is identifiable.  V3 reads those same bounded proof JSON files and
records the JSON field paths that are actually present, explicit unit/scale
fields, the frozen gate source, and the prerequisites still needed for
recognition.  A row therefore remains ``UNKNOWN_IDENTIFICATION_GATE_NOT_CLOSED``
when it has useful diagnostic fields but lacks the complete source/control,
common-time, native-role, or independent-error evidence required by that
dimension.

Only the V2 catalog, the small V3 frozen-gate registry, and the 41 referenced
proof JSON files are read.  No BI4, VTK, HDF5, solver output, or production
payload is opened; no status word is used to infer a dimension.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any


HERE = Path(__file__).resolve().parent
CATALOG_V2 = HERE / "stage2_fourteen_evidence_dimension_catalog_v2.json"
STATUS_V3 = HERE / "stage2_fourteen_source_status_v3.json"
SCHEMA = "ds02.stage2.fourteen-reference-evidence-dimension-catalog.v3"
V2_SCHEMA = "ds02.stage2.fourteen-reference-evidence-dimension-catalog.v2"
STATUS_SCHEMA = "ds02.stage2.fourteen-source-status.v3"
SMALL_CAP = 10 * 1024 * 1024
UNKNOWN = "UNKNOWN"

DIMENSIONS = (
    "spatial_three_grid", "time_step", "output_sampling", "initial_support",
    "control_initial", "native_fields", "external_anchor",
    "integral_vs_output_separated",
)

DIMENSION_TOKENS: dict[str, tuple[str, ...]] = {
    "spatial_three_grid": ("grid", "dp", "spacing", "centroid", "com", "cross_grid", "three_grid"),
    "time_step": ("dt", "timestep", "time_step", "time", "runparts", "dtall", "cfl", "clamp", "saved"),
    "output_sampling": ("output", "saved", "frame", "query", "bracket", "tout", "cadence", "endpoint"),
    "initial_support": ("initial", "support", "mass", "fluid", "bound", "owner", "inside", "outside", "overlap", "count"),
    "control_initial": ("control", "execution", "parameter", "forcing", "motion", "source", "xml", "cfl", "geometry"),
    "native_fields": ("native", "massfluid", "massbound", "idp", "role", "finite", "velocity", "rhop", "position", "field"),
    "external_anchor": ("anchor", "label", "external", "independent", "proof", "source_current"),
    "integral_vs_output_separated": ("integral", "output", "kinetic", "energy", "centroid", "velocity", "comparison", "async", "saved"),
}

PREREQUISITES: dict[str, tuple[str, ...]] = {
    "spatial_three_grid": (
        "three actual grids with exact source/control/owner closure",
        "common physical query times or explicitly bracketed observations",
        "no neighbor-grid value promoted to a truth/error reference",
    ),
    "time_step": (
        "actual solver execution parameters and dt/clamp trace",
        "saved times joined to RunPARTs/DtAll semantics",
        "integrator and output sampling effects measured separately",
    ),
    "output_sampling": (
        "actual saved-frame times and adjacent native frames",
        "output cadence/override joined to the terminal request and receipt",
        "no interpolation presented as a measured field value",
    ),
    "initial_support": (
        "continuous owner geometry/control definition bound to the same source",
        "native role counts and native MassFluid/MassBound when claimed",
        "fluid/bound containment and overlap checks closed",
    ),
    "control_initial": (
        "exact XML/Def/forcing/motion input hash set",
        "execution parameter overrides joined to the actual receipt",
        "same owner and physical control semantics across compared runs",
    ),
    "native_fields": (
        "official decoder and native field/role schema bound to the producer",
        "native positions, velocities, density, IDs, and mass semantics checked",
        "world-axis/unit mapping proven when world observables are claimed",
    ),
    "external_anchor": (
        "independent anchor source and exact producer/request/proof join",
        "anchor scope separated from physical QI/QN/QE qualification",
    ),
    "integral_vs_output_separated": (
        "integrator quantities and saved output quantities read from distinct fields",
        "common-time or bracket contract closed for both quantities",
        "time/output differences kept separate from spatial/grid differences",
    ),
}

TOLERANCE_DIMENSIONS: dict[str, tuple[str, ...]] = {
    "spatial_three_grid": ("position", "whole_initial_mass"),
    "time_step": ("event_time", "time_output", "velocity_ke"),
    "output_sampling": ("time_output", "event_time"),
    "initial_support": ("regional_mass", "whole_initial_mass"),
    "control_initial": (),
    "native_fields": ("velocity_ke",),
    "external_anchor": (),
    "integral_vs_output_separated": ("time_output", "velocity_ke", "position"),
}


class CatalogFailure(RuntimeError):
    pass


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {"device": int(value.st_dev), "inode": int(value.st_ino),
            "bytes": int(value.st_size), "mtime_ns": int(value.st_mtime_ns),
            "ctime_ns": int(value.st_ctime_ns)}


def _read_json(path: Path, label: str) -> tuple[Any, dict[str, Any]]:
    path = path.expanduser().absolute()
    if path.is_symlink() or not path.is_file():
        raise CatalogFailure(f"{label} is not a regular non-symlink file: {path}")
    before = _stat(path)
    if before["bytes"] > SMALL_CAP:
        raise CatalogFailure(f"{label} exceeds 10 MiB: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    if before != after or len(raw) != before["bytes"]:
        raise CatalogFailure(f"{label} changed during bounded read: {path}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CatalogFailure(f"{label} is not valid JSON: {path}") from exc
    return value, {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "stat": after}


def _safe_key(value: str) -> str:
    return value if re.fullmatch(r"[A-Za-z0-9_\-]+", value) else json.dumps(value, ensure_ascii=False)


def _walk_fields(value: Any, path: str = "$") -> list[tuple[str, str, str]]:
    """Return bounded field paths without copying list payloads into output."""
    result: list[tuple[str, str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{_safe_key(str(key))}"
            kind = "object" if isinstance(child, dict) else "array" if isinstance(child, list) else type(child).__name__
            result.append((child_path, str(key), kind))
            if isinstance(child, dict):
                result.extend(_walk_fields(child, child_path))
            elif isinstance(child, list):
                # A list's existence and length are useful metadata; inspect
                # only the first two object rows for field names.
                result.append((child_path + ".length", "length", "int"))
                for index, item in enumerate(child[:2]):
                    if isinstance(item, dict):
                        result.extend(_walk_fields(item, f"{child_path}[{index}]"))
    return result


def _matches(key: str, tokens: tuple[str, ...]) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", key.lower())
    return any(token.replace("_", "") in normalized for token in tokens)


def _unit_for_key(key: str) -> str | None:
    lower = key.lower()
    suffixes = (
        ("_m_per_s", "m/s"), ("_mps", "m/s"), ("_m_s", "m/s"),
        ("_m", "m"), ("_s", "s"), ("_kg", "kg"), ("_j", "J"),
        ("_bytes", "bytes"), ("_hz", "Hz"),
    )
    for suffix, unit in suffixes:
        if lower.endswith(suffix):
            return unit
    return None


def _numeric(value: Any) -> float | int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def _numeric_fields(value: Any, path: str = "$") -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{_safe_key(str(key))}"
            number = _numeric(child)
            unit = _unit_for_key(str(key))
            if number is not None and unit is not None:
                result.append({"path": child_path, "unit": unit, "value_kind": type(child).__name__})
            if isinstance(child, dict):
                result.extend(_numeric_fields(child, child_path))
            elif isinstance(child, list):
                for index, item in enumerate(child[:2]):
                    if isinstance(item, dict):
                        result.extend(_numeric_fields(item, f"{child_path}[{index}]"))
    return result


def _tolerance_record(gates: dict[str, Any], dimension: str, gate_source: dict[str, Any]) -> dict[str, Any]:
    names = TOLERANCE_DIMENSIONS[dimension]
    values: dict[str, Any] = {}
    for name in names:
        text = gates.get(name)
        item: dict[str, Any] = {"source_field": f"$.frozen_gates.{name}", "text": text}
        if isinstance(text, str):
            match = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
            if match:
                item["fraction_if_percent"] = float(match.group(1)) / 100.0
        values[name] = item
    return {"status": "SOURCE_REGISTERED_VALUES_ONLY" if values else "UNKNOWN_NO_DIMENSION_GATE",
            "source": gate_source, "gates": values,
            "must_not_be_used_as_truth_error_without_dimension_prerequisites": True}


def _record(v2: dict[str, Any], status: dict[str, Any], status_record: dict[str, Any],
            gates: dict[str, Any]) -> dict[str, Any]:
    path = Path(str(v2["path"]))
    evidence, evidence_record = _read_json(path, str(v2.get("evidence_id", "evidence")))
    if not isinstance(evidence, dict):
        raise CatalogFailure(f"{v2['evidence_id']} proof is not an object")
    dimension = str(v2["dimension"])
    fields = _walk_fields(evidence)
    matching = [{"path": field_path, "key": key, "value_kind": kind}
                for field_path, key, kind in fields if _matches(key, DIMENSION_TOKENS[dimension])]
    # Avoid making the index itself a large mirror of the proof JSON.
    matching = matching[:96]
    scales = _numeric_fields(evidence)[:96]
    if not bool(v2.get("actual")) or not bool(v2.get("observed")):
        observation = "NOT_EXECUTED_SOURCE_PLAN"
    elif not matching:
        observation = "UNKNOWN_NO_RECORDED_DIMENSION_FIELDS"
    else:
        observation = "UNKNOWN_IDENTIFICATION_GATE_NOT_CLOSED"
    return {
        "evidence_id": v2["evidence_id"],
        "sentinel_id": v2["sentinel_id"],
        "dimension": dimension,
        "source_index_flags": {"actual": bool(v2.get("actual")), "observed": bool(v2.get("observed"))},
        "dimension_observation": observation,
        "field_presence": {
            "status": "FIELDS_PRESENT" if matching else "NO_MATCHING_FIELDS_FOUND",
            "paths": matching,
            "matching_token_vocabulary": list(DIMENSION_TOKENS[dimension]),
        },
        "observed_scales": {
            "status": "EXPLICIT_UNIT_FIELDS_PRESENT" if scales else "UNKNOWN_NO_EXPLICIT_UNIT_FIELDS",
            "fields": scales,
            "unit_inference_from_filename_or_status": False,
        },
        "frozen_tolerance": _tolerance_record(gates, dimension, status_record),
        "recognition_prerequisites": [
            {"requirement": item, "status": UNKNOWN}
            for item in PREREQUISITES[dimension]
        ],
        "evidence": {
            "path": evidence_record["path"], "sha256": evidence_record["sha256"],
            "stat": evidence_record["stat"], "source_v2_sha256": v2.get("sha256"),
        },
        "note": v2.get("note"),
        "origin": v2.get("origin"),
        "scope": "bounded_proof_field_inventory_only",
        "scientific_qualification": {"QI": UNKNOWN, "QN": UNKNOWN, "QE": UNKNOWN, "scientific_credit": 0},
    }


def build(catalog_path: Path, status_path: Path, output_path: Path) -> dict[str, Any]:
    catalog, catalog_record = _read_json(catalog_path, "V2 evidence catalog")
    status, status_record = _read_json(status_path, "V3 frozen gate registry")
    if catalog.get("schema") != V2_SCHEMA or catalog.get("record_count") != 41:
        raise CatalogFailure("V2 catalog schema/count mismatch")
    if status.get("schema") != STATUS_SCHEMA:
        raise CatalogFailure("frozen gate registry schema mismatch")
    gates = status.get("frozen_gates")
    if not isinstance(gates, dict):
        raise CatalogFailure("frozen gate registry has no frozen_gates object")
    records = catalog.get("records")
    if not isinstance(records, list) or len(records) != 41:
        raise CatalogFailure("V2 catalog does not contain 41 records")
    output_records = [_record(item, status, status_record, gates) for item in records]
    pairs = [(str(item["sentinel_id"]), str(item["dimension"])) for item in output_records]
    if len(set(pairs)) != len(pairs):
        raise CatalogFailure("V3 catalog has duplicate sentinel/dimension pairs")
    result = {
        "schema": SCHEMA,
        "status": "CURRENT_EXPLICIT_41_RECORD_FIELD_GROUNDED_INDEX_NO_SCIENTIFIC_Q",
        "record_count": len(output_records),
        "dimension_vocabulary": list(DIMENSIONS),
        "records": output_records,
        "source_catalog_v2": catalog_record,
        "frozen_gate_registry": status_record,
        "read_scope": {
            "metadata_cap_bytes": SMALL_CAP,
            "proof_json_only": True,
            "production_native_vtk_bi4_h5_read": False,
            "solver_or_gencase_launch": False,
            "dimension_observation_requires_identification_prerequisites": True,
            "status_text_not_used_to_infer_dimension": True,
        },
        "scientific_qualification": {"QI": UNKNOWN, "QN": UNKNOWN, "QE": UNKNOWN, "scientific_credit": 0},
    }
    output_path = output_path.expanduser().absolute()
    if output_path.exists() or output_path.is_symlink():
        raise CatalogFailure(f"refusing overwrite: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


def _self_test() -> None:
    gates = {"position": "2% registered L", "time_output": "each <= one quarter", "velocity_ke": "5% scale"}
    source = {"path": "fixture", "sha256": "0" * 64, "stat": {}}
    evidence = {"report": {"maximum_centroid_difference_m": 0.1,
                            "maximum_mean_velocity_difference_m_per_s": 0.2,
                            "saved_time_s": 1.0}}
    fields = _walk_fields(evidence)
    assert any(path.endswith("maximum_centroid_difference_m") for path, _, _ in fields)
    result = _tolerance_record(gates, "spatial_three_grid", source)
    assert result["gates"]["position"]["fraction_if_percent"] == 0.02
    assert _matches("maximum_centroid_difference_m", DIMENSION_TOKENS["spatial_three_grid"])
    assert not _matches("unrelated_status", DIMENSION_TOKENS["spatial_three_grid"])
    print("PASS_FOURTEEN_EVIDENCE_DIMENSION_CATALOG_V3_SELFTEST")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build", action="store_true")
    parser.add_argument("--catalog", type=Path, default=CATALOG_V2)
    parser.add_argument("--status", type=Path, default=STATUS_V3)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.self_test:
        try:
            _self_test()
        except Exception as exc:
            print(f"FAILED_FOURTEEN_EVIDENCE_DIMENSION_CATALOG_V3_SELFTEST: {exc}", file=sys.stderr)
            return 2
        return 0
    if args.output is None:
        parser.error("--build requires --output")
    try:
        value = build(args.catalog, args.status, args.output)
    except (CatalogFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_FOURTEEN_EVIDENCE_DIMENSION_CATALOG_V3: {exc}", file=sys.stderr)
        return 2
    unknown = sum(item["dimension_observation"].startswith("UNKNOWN") for item in value["records"])
    print(json.dumps({"status": value["status"], "record_count": value["record_count"],
                      "unknown_dimension_observations": unknown,
                      "output": str(args.output.expanduser().absolute()), "scientific_credit": 0}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
