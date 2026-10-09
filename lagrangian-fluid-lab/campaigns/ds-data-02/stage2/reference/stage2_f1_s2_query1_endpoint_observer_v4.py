#!/usr/bin/env python3
"""ROOT234 query-1 component-space native endpoint reader.

ROOT225 stopped at the world-axis metadata gate.  ROOT234 is a separate
query-1 namespace: it calls the already tested axis-independent ROOT231
component reader, but first checks the complete one-second manifest entry.
The check binds the lower/upper native frame records to each grid and rejects
the common builder/reader mismatch before any native file is opened.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import stage2_f1_native_selected_observer_v1 as calibrated
import stage2_f1_s2_query_endpoint_observer_v2 as _reader


SCHEMA = "ds02.stage2.f1-s2.query1-endpoint-observer.v4"
MANIFEST_SCHEMA = "ds02.stage2.f1-s2.query1-endpoint-manifest.v3"
PASS_STATUS = "COMPLETE_QUERY1_NATIVE_COMPONENT_DIAGNOSTICS_NO_SCIENTIFIC_Q"
FAIL_STATUS = "FAILED_QUERY1_NATIVE_ENDPOINT_GUARD_V4"
QUERY_TIMES_S = (1.0,)


def _failure(output: Path, reason: str) -> None:
    output = output.expanduser().absolute()
    if output.exists():
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    _reader._failure_report_v2(output, reason)
    # The inherited helper is configured below only during a normal run.  A
    # failure before configuration must still carry the ROOT234 namespace.
    try:
        value = json.loads(output.read_text(encoding="utf-8"))
        value["schema"] = SCHEMA
        value["status"] = FAIL_STATUS
        output.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except (OSError, UnicodeError, json.JSONDecodeError):
        pass


def validate_manifest_entry(manifest: dict[str, Any]) -> None:
    """Validate the builder-shaped query-1 manifest before native access."""
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("status") != "PREPARED_NOT_RUN_ROOT234_QUERY1_AXIS_INDEPENDENT_ENDPOINT_AUDIT":
        raise ValueError("ROOT234 manifest schema/status mismatch")
    grids = manifest.get("grids")
    if not isinstance(grids, list) or len(grids) != 3 or {item.get("label") for item in grids if isinstance(item, dict)} != {"coarse", "medium", "fine"}:
        raise ValueError("ROOT234 requires exactly coarse/medium/fine grid records")
    deferred = manifest.get("deferred_native_records")
    if not isinstance(deferred, list):
        raise ValueError("ROOT234 deferred native records are missing")
    for grid in grids:
        label = grid["label"]
        queries = grid.get("queries")
        if not isinstance(queries, list) or len(queries) != 1:
            raise ValueError(f"{label} must have exactly one query record")
        query = queries[0]
        if float(query.get("query_time_s")) != 1.0:
            raise ValueError(f"{label} query is not the frozen 1 second endpoint")
        if query.get("interpolation") != "NOT_PERFORMED" or query.get("extrapolation") != "FORBIDDEN":
            raise ValueError(f"{label} query permits interpolation/extrapolation")
        lower = query.get("lower")
        upper = query.get("upper")
        if not isinstance(lower, dict) or not isinstance(upper, dict):
            raise ValueError(f"{label} lacks lower/upper RunPARTs rows")
        selected = {int(lower["frame"]), int(upper["frame"])}
        records = [item for item in deferred if isinstance(item, dict) and item.get("grid") == label]
        if len(records) != len(selected):
            raise ValueError(f"{label} deferred record count does not match query endpoints")
        seen: set[int] = set()
        for record in records:
            if record.get("grid_label") != label:
                raise ValueError(f"{label} deferred record is missing matching grid_label")
            frame = record.get("frame")
            if not isinstance(frame, int) or frame in seen or frame not in selected:
                raise ValueError(f"{label} deferred frame does not match the one-second bracket")
            path = Path(str(record.get("path", "")))
            if path.name != f"Part_{frame:04d}.bi4":
                raise ValueError(f"{label} deferred path/frame mismatch")
            seen.add(frame)
        if seen != selected:
            raise ValueError(f"{label} deferred records do not cover both query endpoints")
    if len(deferred) != 6:
        raise ValueError("ROOT234 requires exactly six deferred endpoint Part records")


def _configure() -> None:
    _reader.SCHEMA = SCHEMA
    _reader.MANIFEST_SCHEMA = MANIFEST_SCHEMA
    _reader.PASS_STATUS = PASS_STATUS
    _reader.FAIL_STATUS = FAIL_STATUS
    _reader.QUERY_TIMES_S = QUERY_TIMES_S


def run(args: argparse.Namespace) -> dict[str, Any]:
    manifest_path = args.manifest.expanduser().absolute()
    # This is a bounded metadata read; the inherited reader performs its own
    # stable read and all deferred Part files remain parent-owned.
    manifest, _ = _reader._read_json(manifest_path, "ROOT234 query-1 manifest")
    validate_manifest_entry(manifest)
    _configure()
    # Do not call _reader.run(): its consumed ROOT231 implementation has a
    # hard-coded ROOT231 status string.  Reusing its verified grid decoder
    # helpers while owning this small entry/result envelope keeps ROOT234's
    # status separate and prevents ROOT225/ROOT231 namespace confusion.
    manifest, manifest_record = _reader._read_json(manifest_path, "ROOT234 query-1 manifest")
    _reader._verify_static_sources(manifest)
    joins = _reader._verify_producer_joins(manifest)
    grids = manifest.get("grids")
    if not isinstance(grids, list) or len(grids) != 3:
        raise ValueError("ROOT234 requires exactly three grids")
    attempt_root = args.attempt_root.expanduser().absolute()
    outputs = [_reader._run_grid(joins["child"], manifest, grid, attempt_root) for grid in grids]
    result = {
        "schema": SCHEMA,
        "status": PASS_STATUS,
        "manifest": manifest_record,
        "producer_join": {key: value for key, value in joins.items() if key != "child"},
        "query": {"query_times_s": [1.0], "interpolation": "FORBIDDEN", "extrapolation": "FORBIDDEN"},
        "grids": outputs,
        "read_scope": {
            "native_payload_read_count": sum(int(item["native_payload_read_count"]) for item in outputs),
            "native_payload_read": "nearest lower/upper Part files for query 1 second only",
            "hdf5_read": False,
            "vtk_read": False,
            "full_native_tree_scan": False,
            "solver_launch": False,
        },
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0},
        "qualification_limits": [
            "component-space native endpoint fields only; producer world-axis remains UNKNOWN",
            "query frame IDs are native frame IDs; selected row indices are not substituted",
            "no interpolation or extrapolation",
            "one-second brackets are not output intervals or error bounds",
            "integration, spatial truth, event-time, and external-validation qualifications remain UNKNOWN",
        ],
    }
    calibrated.base.atomic_json(args.output.expanduser().absolute(), result)
    return result


def self_test() -> None:
    # Builder-shaped manifest: validate the exact entry contract, not merely a
    # decoder fixture.  The request builder has the same six records.
    grids = []
    deferred = []
    for label, lower, upper in (("coarse", 199, 200), ("medium", 99, 100), ("fine", 199, 200)):
        grids.append({"label": label, "queries": [{"query_time_s": 1.0, "lower": {"frame": lower, "time_s": 0.99}, "upper": {"frame": upper, "time_s": 1.01}, "interpolation": "NOT_PERFORMED", "extrapolation": "FORBIDDEN"}]})
        for frame in (lower, upper):
            deferred.append({"grid": label, "grid_label": label, "frame": frame, "path": f"/deferred/{label}/Part_{frame:04d}.bi4", "sha256": "PARENT_AFTER_RESERVATION"})
    manifest = {"schema": MANIFEST_SCHEMA, "status": "PREPARED_NOT_RUN_ROOT234_QUERY1_AXIS_INDEPENDENT_ENDPOINT_AUDIT", "grids": grids, "deferred_native_records": deferred}
    validate_manifest_entry(manifest)
    bad = json.loads(json.dumps(manifest))
    bad["deferred_native_records"][0]["grid_label"] = "fine"
    try:
        validate_manifest_entry(bad)
    except ValueError:
        pass
    else:
        raise AssertionError("ROOT234 accepted a mismatched builder/reader grid label")
    bad = json.loads(json.dumps(manifest))
    bad["grids"][0]["queries"][0]["query_time_s"] = 2.0
    try:
        validate_manifest_entry(bad)
    except ValueError:
        pass
    else:
        raise AssertionError("ROOT234 accepted a non-query-1 manifest")
    print("PASS_F1_S2_QUERY1_ENDPOINT_OBSERVER_V4_MANIFEST_ENTRY_SELFTEST")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--attempt-root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.manifest is None or args.attempt_root is None or args.output is None:
        parser.error("--manifest, --attempt-root, and --output are required unless --self-test is used")
    try:
        result = run(args)
    except Exception as exc:
        _failure(args.output, str(exc))
        print(f"FAIL_F1_S2_QUERY1_ENDPOINT_OBSERVER_V4: {exc}")
        return 2
    print(json.dumps({"status": result["status"], "output": str(args.output.expanduser().absolute())}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
