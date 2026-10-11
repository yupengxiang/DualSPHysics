#!/usr/bin/env python3
"""Validate direct-converter metadata and emit M4 portability evidence.

This is a bounded post-conversion audit.  It reads the JSON conversion report,
the small owner metadata file, generated XML, and an optional producer-native
lifecycle JSON sidecar.  It intentionally does not open trajectory HDF5, BI4,
PartOut, or RunPARTs payloads and it never infers a particle's physical fate.

The native lifecycle sidecar is an exchange point for an existing official
PartOut/RunPARTs extraction.  This module validates its identity/reason fields;
it is not a second BI4/PartOut decoder.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Mapping


CONVERSION_SCHEMA = "ds-data-02.bi4-direct-conversion.v1"
OUTPUT_SCHEMA = "ds-data-02.m4.upstream-conversion-compatibility.v1"
NATIVE_SCHEMA = "ds-data-02.native-lifecycle-records.v1"
PHYSICAL_BINDING_SCHEMA = "ds-data-02.physical-binding.v1"
TOLERANCE_S = 1.0e-3


class CompatibilityError(ValueError):
    """Raised when the report cannot support the declared route contract."""


def _regular(path: Path, label: str) -> Path:
    if not path.is_file() or path.is_symlink():
        raise CompatibilityError(f"{label} is not a regular file: {path}")
    return path


def _json(path: Path, label: str) -> dict[str, Any]:
    _regular(path, label)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CompatibilityError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise CompatibilityError(f"{label} must be a JSON object: {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _expected_hash(path: Path, expected: Any, label: str) -> str:
    actual = _sha256(_regular(path, label))
    if isinstance(expected, str) and expected and actual != expected:
        raise CompatibilityError(f"{label} SHA-256 disagrees with the conversion report")
    return actual


def _scalar_float(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise CompatibilityError(f"{label} is not numeric: {value!r}") from exc
    if not math.isfinite(result):
        raise CompatibilityError(f"{label} is not finite: {value!r}")
    return result


def _xml_evidence(path: Path) -> dict[str, Any]:
    _regular(path, "generated XML")
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise CompatibilityError(f"generated XML is not parseable: {path}") from exc
    geometry = root.find(".//geometry")
    execution = root.find(".//execution")
    if geometry is None:
        raise CompatibilityError("generated XML lacks .//geometry")
    if execution is None:
        raise CompatibilityError("generated XML lacks .//execution")
    parameters = {
        item.get("key"): item.get("value")
        for item in execution.findall(".//parameter")
        if item.get("key")
    }
    if parameters.get("Boundary") not in {"2", "2.0"}:
        raise CompatibilityError("generated XML is not the official mDBC Boundary=2 route")
    data2d = root.find(".//data2d")
    return {
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
        "geometry_present": True,
        "execution_present": True,
        "boundary": parameters.get("Boundary"),
        "time_max_s": parameters.get("TimeMax"),
        "time_out_s": parameters.get("TimeOut"),
        "data2d_value": None if data2d is None else data2d.get("value"),
    }


def _event_window(owner: Mapping[str, Any]) -> tuple[float, float, dict[str, Any]]:
    binding = owner.get("physical_binding")
    if not isinstance(binding, Mapping) or binding.get("schema") != PHYSICAL_BINDING_SCHEMA:
        raise CompatibilityError(
            "owner metadata needs an explicit ds-data-02.physical-binding.v1 object"
        )
    event = binding.get("event_window")
    if not isinstance(event, Mapping):
        raise CompatibilityError("physical_binding.event_window is missing")
    start = _scalar_float(event.get("time_start_s", 0.0), "event_window.time_start_s")
    end = _scalar_float(event.get("time_end_s"), "event_window.time_end_s")
    if end <= start:
        raise CompatibilityError("event window end must be greater than start")
    return start, end, dict(event)


def _validate_native_records(path: Path) -> dict[str, Any]:
    payload = _json(path, "native lifecycle sidecar")
    if payload.get("schema") != NATIVE_SCHEMA:
        raise CompatibilityError(
            f"native lifecycle sidecar schema must be {NATIVE_SCHEMA!r}"
        )
    records = payload.get("records")
    if not isinstance(records, list):
        raise CompatibilityError("native lifecycle sidecar records must be a list")
    checked = []
    for index, row in enumerate(records):
        if not isinstance(row, Mapping):
            raise CompatibilityError(f"native lifecycle record {index} is not an object")
        if not ("particle_id" in row or "idp" in row):
            raise CompatibilityError(f"native lifecycle record {index} lacks Idp")
        if not ("particle_zone" in row or "zone" in row or "piece" in row):
            raise CompatibilityError(f"native lifecycle record {index} lacks Zone/Piece")
        if "time_s" not in row:
            raise CompatibilityError(f"native lifecycle record {index} lacks time_s")
        _scalar_float(row["time_s"], f"native lifecycle record {index}.time_s")
        reason = row.get("reason", row.get("motive"))
        if not isinstance(reason, str) or not reason.strip():
            raise CompatibilityError(f"native lifecycle record {index} lacks native reason/motive")
        checked.append(
            {
                "index": index,
                "particle_id_field": "particle_id" if "particle_id" in row else "idp",
                "zone_field": "particle_zone" if "particle_zone" in row else ("zone" if "zone" in row else "piece"),
                "reason": reason,
            }
        )
    return {
        "available": True,
        "schema": NATIVE_SCHEMA,
        "path_sha256": _sha256(path),
        "bytes": path.stat().st_size,
        "record_count": len(records),
        "records_checked": checked,
        "fate_inference": "forbidden; native reason/motive is retained as a numerical-node censoring record",
    }


def validate(
    report_path: Path,
    *,
    owner_metadata: Path,
    generated_xml: Path,
    definition_xml: Path | None = None,
    native_lifecycle: Path | None = None,
    expected_case_id: str | None = None,
    event_start_s: float | None = None,
    event_end_s: float | None = None,
) -> dict[str, Any]:
    report = _json(report_path, "conversion report")
    owner = _json(owner_metadata, "owner metadata")
    if report.get("schema") != CONVERSION_SCHEMA:
        raise CompatibilityError(f"unsupported conversion report schema: {report.get('schema')!r}")
    if report.get("conversion_status") != "completed":
        raise CompatibilityError("conversion report is not completed")
    if expected_case_id is not None and report.get("case_id") not in {None, expected_case_id}:
        raise CompatibilityError("conversion report case identity disagrees with the route")

    provenance = report.get("source_provenance")
    if not isinstance(provenance, Mapping):
        raise CompatibilityError("conversion report lacks source_provenance")
    owner_info = provenance.get("owner_metadata")
    xml_info = provenance.get("generated_xml")
    if not isinstance(owner_info, Mapping) or not isinstance(xml_info, Mapping):
        raise CompatibilityError("conversion report lacks owner/XML source hashes")
    owner_hash = _expected_hash(owner_metadata, owner_info.get("sha256"), "owner metadata")
    xml_evidence = _xml_evidence(generated_xml)
    if isinstance(xml_info.get("sha256"), str) and xml_info["sha256"] != xml_evidence["sha256"]:
        raise CompatibilityError("generated XML SHA-256 disagrees with the conversion report")

    definition_evidence = None
    if definition_xml is not None:
        definition_evidence = {
            "path_sha256": _sha256(_regular(definition_xml, "source definition XML")),
            "bytes": definition_xml.stat().st_size,
        }
        declared = owner.get("source_mother", {}).get("source_definition_sha256")
        if isinstance(declared, str) and declared and declared != definition_evidence["path_sha256"]:
            raise CompatibilityError("source definition hash disagrees with owner metadata")

    binding = owner.get("physical_binding")
    if not isinstance(binding, Mapping) or binding.get("schema") != PHYSICAL_BINDING_SCHEMA:
        raise CompatibilityError("explicit physical binding is required for M4 route")
    physical_start, physical_end, event = _event_window(owner)
    start = physical_start if event_start_s is None else _scalar_float(event_start_s, "selected event start")
    end = physical_end if event_end_s is None else _scalar_float(event_end_s, "selected event end")
    if start < physical_start - TOLERANCE_S or end > physical_end + TOLERANCE_S or end <= start:
        raise CompatibilityError(
            f"selected event window [{start}, {end}] is outside physical source window "
            f"[{physical_start}, {physical_end}]"
        )

    frames = report.get("frames")
    particles = report.get("particles")
    if not isinstance(frames, int) or frames < 2:
        raise CompatibilityError("conversion report must contain at least two frames")
    if not isinstance(particles, int) or particles <= 0:
        raise CompatibilityError("conversion report must contain a full positive identity axis")
    dimension = report.get("solver_dimension", {}).get("solver_dimension")
    if dimension != 3:
        raise CompatibilityError(f"M4 route requires 3-D report, got {dimension!r}")
    typed = report.get("typed_identity")
    lifecycle = report.get("lifecycle")
    time_evidence = report.get("time_evidence")
    if not isinstance(typed, Mapping) or typed.get("key") != "(Zone,Idp)":
        raise CompatibilityError("native typed identity key (Zone,Idp) is missing")
    if not isinstance(lifecycle, Mapping):
        raise CompatibilityError("conversion report lacks lifecycle validity evidence")
    required_lifecycle = {
        "contract",
        "introduced_ids",
        "open_birth_adaptive_multi_piece",
        "transient_missing_frame_count",
        "transient_missing_by_type_frame_events",
        "transient_missing_by_mk_frame_events",
        "missing_semantics",
    }
    missing_lifecycle = sorted(required_lifecycle.difference(lifecycle))
    if missing_lifecycle:
        raise CompatibilityError(f"lifecycle evidence is incomplete: {missing_lifecycle}")
    if lifecycle.get("contract") != "closed fixed identity axis":
        raise CompatibilityError("M4 route requires the closed fixed identity axis contract")
    if lifecycle.get("introduced_ids") != "rejected":
        raise CompatibilityError("introduced IDs are not rejected by the direct converter")
    if lifecycle.get("open_birth_adaptive_multi_piece") != "rejected":
        raise CompatibilityError("open/birth/adaptive/multi-piece contracts are not rejected")
    ledger = typed.get("initial_exclusion_ledger")
    if not isinstance(ledger, Mapping):
        raise CompatibilityError("initial exclusion ledger is missing")
    for key in ("count", "ids_sha256", "type_counts", "mk_counts", "semantics"):
        if key not in ledger:
            raise CompatibilityError(f"initial exclusion ledger lacks {key}")
    if not isinstance(time_evidence, Mapping):
        raise CompatibilityError("conversion report lacks time evidence")
    first_s = _scalar_float(time_evidence.get("first_s"), "time_evidence.first_s")
    last_s = _scalar_float(time_evidence.get("last_s"), "time_evidence.last_s")
    if first_s > start + TOLERANCE_S or last_s < end - TOLERANCE_S:
        raise CompatibilityError(
            f"converted native window [{first_s}, {last_s}] does not cover [{start}, {end}]"
        )
    if time_evidence.get("strictly_increasing") is not True:
        raise CompatibilityError("native time evidence is not strictly increasing")

    native_evidence = (
        _validate_native_records(native_lifecycle)
        if native_lifecycle is not None
        else {
            "available": False,
            "status": "pending_native_partout_binding",
            "fate_inference": "forbidden; no native reason has been supplied",
        }
    )
    native_status = "ready" if native_evidence.get("available") else "blocked_missing_native_partout_binding"
    return {
        "schema": OUTPUT_SCHEMA,
        "status": "ready" if native_status == "ready" else native_status,
        "case_id": expected_case_id or owner.get("case_id") or report.get("case_id"),
        "route": {
            "converter": "lagrangian-fluid-lab/scripts/ds_data02_direct_convert.py",
            "contract": "full spatial native BI4 event window; one decoded frame at a time",
            "spatial_subsampling": "forbidden",
            "event_window_s": [start, end],
            "physical_source_event_window_s": [physical_start, physical_end],
            "time_evidence_s": [first_s, last_s],
            "frames": frames,
            "particles": particles,
            "identity_key": "(Zone,Idp)",
            "transport_semantics": "numerical solver-node identity; no material relabeling or fate inference",
        },
        "source_hashes": {
            "conversion_report_sha256": _sha256(report_path),
            "owner_metadata_sha256": owner_hash,
            "generated_xml_sha256": xml_evidence["sha256"],
            "source_definition": definition_evidence,
            "report_declared_geometry_sha256": provenance.get("geometry_sha256"),
            "report_declared_control_sha256": provenance.get("control_sha256"),
        },
        "geometry_control": {
            "geometry_from_generated_xml": True,
            "control_from_generated_xml": True,
            "physical_binding_schema": binding.get("schema"),
            "event_window": event,
            "xml": xml_evidence,
        },
        "validity": {
            "valid_dataset": "valid[t, (Zone,Idp)]",
            "initial_exclusion_ledger": dict(ledger),
            "transient_missing_frame_count": lifecycle.get("transient_missing_frame_count"),
            "transient_missing_by_type_frame_events": lifecycle.get("transient_missing_by_type_frame_events"),
            "transient_missing_by_mk_frame_events": lifecycle.get("transient_missing_by_mk_frame_events"),
            "missing_semantics": lifecycle.get("missing_semantics"),
            "native_partout": native_evidence,
            "physical_fate": "UNKNOWN",
        },
        "portable_compatibility": {
            "trajectory_fields": [
                "time", "particle_id", "particle_zone", "valid", "position", "velocity",
                "density", "mass", "pressure", "type", "mk", "initial_type", "initial_mk", "initial_mass",
            ],
            "label_key": ["particle_zone", "particle_id"],
            "endpoint_policy": "emit source/destination values only with endpoint-valid masks; preserve unknown/censored rows",
            "observed_all_frames": "valid.all(axis=0)",
            "destination_region": "unknown when destination validity is false; never infer physical fate from a region",
            "evaluator_policy": "mask invalid endpoint pairs; identity/per-field negatives remain no-model integrity checks",
            "builder_gap": "existing M2 portable_bundle.validate_bundle currently requires complete validity; M4 must use a validity-aware adapter before publication",
        },
        "claim_boundary": {
            "conversion": "evidence only",
            "scientific_transport_truth": "not established",
            "physical_fate": "UNKNOWN",
            "native_reason": "preserved only when the producer-native sidecar is bound",
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--owner-metadata", required=True, type=Path)
    parser.add_argument("--generated-xml", required=True, type=Path)
    parser.add_argument("--definition-xml", type=Path)
    parser.add_argument("--native-lifecycle", type=Path)
    parser.add_argument("--case-id")
    parser.add_argument("--event-start-s", type=float)
    parser.add_argument("--event-end-s", type=float)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = validate(
            args.report,
            owner_metadata=args.owner_metadata,
            generated_xml=args.generated_xml,
            definition_xml=args.definition_xml,
            native_lifecycle=args.native_lifecycle,
            expected_case_id=args.case_id,
            event_start_s=args.event_start_s,
            event_end_s=args.event_end_s,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        if args.output.exists() or args.output.is_symlink():
            raise CompatibilityError(f"refusing to overwrite {args.output}")
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["status"] == "ready" else 2
    except (OSError, CompatibilityError, json.JSONDecodeError) as exc:
        print(f"upstream-conversion-compatibility: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
