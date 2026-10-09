#!/usr/bin/env python3
"""Guarded ROOT231 endpoint observer without an unauthorized axis gate.

ROOT225 proved that the old endpoint wrapper stopped before the calibrated
decoder because it passed the ROOT207 report through the V1 ``axis_authority``
validator.  The producer orientation is intentionally UNKNOWN for this
study, so it is not a prerequisite for component-space native fields.  This
forward worker keeps the ROOT225 source and receipt joins, but calls the
calibrated V1 case reader directly after the parent-reserved pre-read.  It
therefore reuses the official decoder, Idp/range checks, native header
scalars, and fluid-only observables without turning the unknown world-axis
record into a failure.

The worker is for query times 2, 3, and 4 seconds.  It reads only the
nearest saved lower/upper Part files for those queries, never interpolates,
and grants no scientific qualification.  All deferred Part SHA/stat values
remain parent-owned until reservation.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile
from typing import Any

import stage2_f1_native_selected_observer_v1 as calibrated

from stage2_f1_s2_query_endpoint_observer_v1 import (
    GuardFailure,
    MAX_NATIVE_BYTES,
    MAX_SMALL_BYTES,
    _build_v1_manifest,
    _command_tout,
    _nearest,
    _parse_runparts,
    _read_json,
    _read_stable,
    _record_matches,
    _verify_producer_joins,
    _verify_static_sources,
    _xml_timeout,
)


SCHEMA = "ds02.stage2.f1-s2.query-endpoint-observer.v2"
MANIFEST_SCHEMA = "ds02.stage2.f1-s2.query-endpoint-manifest.v2"
PASS_STATUS = "COMPLETE_QUERY234_NATIVE_COMPONENT_DIAGNOSTICS_NO_SCIENTIFIC_Q"
FAIL_STATUS = "FAILED_QUERY234_NATIVE_ENDPOINT_GUARD"
QUERY_TIMES_S = (2.0, 3.0, 4.0)


def _failure_report_v2(output: Path, reason: str) -> None:
    """Write a correctly versioned bounded failure artifact.

    The consumed V1 helper writes a V1 schema even when called by a forward
    worker.  Keeping that helper untouched is required for provenance, but a
    ROOT231 failure must identify itself as V2 so the parent cannot mistake an
    axis-independent attempt for the old ROOT225 product.
    """
    output = output.expanduser().absolute()
    if output.exists():
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    value = {
        "schema": SCHEMA,
        "status": FAIL_STATUS,
        "reason": reason,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0},
        "scope": {"native_payload_read": "UNKNOWN_OR_PARTIAL", "interpolation": "NOT_PERFORMED", "solver_launch": False},
    }
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(output)


def _records_for_grid(manifest: dict[str, Any], label: str) -> list[dict[str, Any]]:
    records = [item for item in manifest.get("deferred_native_records", []) if item.get("grid") == label]
    if not records or len(records) > 6:
        raise GuardFailure(f"{label} deferred record count is outside the query234 bound: {len(records)}")
    if any(item.get("sha256") != "PARENT_AFTER_RESERVATION" for item in records):
        raise GuardFailure(f"{label} deferred Part SHA was filled before reservation")
    return records


def _query_rows(grid: dict[str, Any], rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[int]]:
    expected = grid.get("queries")
    if not isinstance(expected, list) or [float(item.get("query_time_s")) for item in expected] != list(QUERY_TIMES_S):
        raise GuardFailure("manifest query times are not the frozen 2/3/4 second set")
    required: list[dict[str, Any]] = []
    selected: set[int] = set()
    for item in expected:
        lower, upper = _nearest(rows, float(item["query_time_s"]))
        if lower != item.get("lower") or upper != item.get("upper"):
            raise GuardFailure(f"{grid['label']} nearest endpoint changed for query {item['query_time_s']}")
        selected.add(int(lower["frame"]))
        selected.add(int(upper["frame"]))
        required.append({
            "query_time_s": float(item["query_time_s"]),
            "lower": lower,
            "upper": upper,
            "interpolation": "NOT_PERFORMED",
            "extrapolation": "FORBIDDEN",
            "selected_row_index_is_not_native_frame_id": True,
        })
    return required, sorted(selected)


def _run_grid(child: dict[str, Any], manifest: dict[str, Any], grid: dict[str, Any], attempt_root: Path) -> dict[str, Any]:
    label = str(grid["label"])
    records = _records_for_grid(manifest, label)
    receipt_path = Path(grid["solver_receipt"]["path"])
    receipt, receipt_record = _read_json(receipt_path, f"{label} solver receipt", grid["solver_receipt"]["sha256"])
    if receipt.get("status") != "completed" or receipt.get("returncode") not in (0, "0"):
        raise GuardFailure(f"{label} solver receipt is not completed/0")
    request = receipt.get("request")
    if not isinstance(request, dict):
        raise GuardFailure(f"{label} solver receipt has no request")
    identity = grid["identity"]
    if label in {"coarse", "fine"}:
        if request.get("sentinel_id") != "F1-S2" or request.get("physical_case_id") != identity.get("physical_case_id"):
            raise GuardFailure(f"{label} solver request physical identity mismatch")
        identity_status = "REQUEST_V1_F1_S2_PHYSICAL_IDENTITY"
    else:
        if (
            request.get("family_id") != "F1"
            or request.get("case_id") != "F1_STAGE1_DUAL_H340_DP020"
            or request.get("sentinel_id") is not None
            or request.get("physical_case_id") != identity.get("physical_case_id")
        ):
            raise GuardFailure(f"{label} historical runner-v2 solver request identity mismatch")
        identity_status = "HISTORICAL_RUNNER_V2_EXACT_F1_CASE_ID_PHYSICAL_IDENTITY_ABSENT"

    runparts_payload, runparts_record = _read_stable(Path(grid["runparts"]["path"]), f"{label} RunPARTs")
    if runparts_record["sha256"] != grid["runparts"]["sha256"]:
        raise GuardFailure(f"{label} RunPARTs SHA changed since preparation")
    rows = _parse_runparts(runparts_payload, f"{label} RunPARTs")
    if len(rows) != int(grid["expected_frame_count"]):
        raise GuardFailure(f"{label} RunPARTs row count changed")
    if rows[0] != grid["first_frame"] or rows[-1] != grid["last_frame"]:
        raise GuardFailure(f"{label} RunPARTs endpoints changed since preparation")
    queries, selected = _query_rows(grid, rows)
    xml_payload, xml_record = _read_stable(Path(grid["generated_xml"]["path"]), f"{label} generated XML")
    if xml_record["sha256"] != grid["generated_xml"]["sha256"]:
        raise GuardFailure(f"{label} generated XML SHA changed")
    xml_tout = _xml_timeout(xml_payload, f"{label} generated XML")
    request_tout = _command_tout(request.get("command"))
    receipt_tout = _command_tout(receipt.get("command"))
    if xml_tout is None or request_tout is None or receipt_tout is None or request_tout != receipt_tout:
        raise GuardFailure(f"{label} XML/request/receipt tout evidence is incomplete")
    if float(grid["actual_request_tout_s"]) != float(request_tout):
        raise GuardFailure(f"{label} prepared request tout differs from executed receipt")
    output_root = Path(str(receipt.get("output_root", ""))).expanduser().absolute()
    raw_root = Path(grid["raw_root"]).expanduser().absolute()
    if raw_root.parent != output_root / "solver_output":
        raise GuardFailure(f"{label} raw_root does not join receipt output_root")

    by_frame = {int(item["frame"]): item for item in records}
    for frame in selected:
        item = by_frame.get(frame)
        if item is None or Path(item["path"]).expanduser().absolute() != raw_root / f"Part_{frame:04d}.bi4":
            raise GuardFailure(f"{label} deferred records do not exactly cover selected query frames")
    if set(by_frame) != set(selected):
        raise GuardFailure(f"{label} deferred records contain an unrequested frame")
    native_pre: dict[int, dict[str, Any]] = {}
    for frame in selected:
        _, native_pre[frame] = _read_stable(raw_root / f"Part_{frame:04d}.bi4", f"{label} native Part {frame}", max_bytes=MAX_NATIVE_BYTES)

    # The calibrated V1 case reader does not use its axis argument.  Calling
    # it directly preserves the official decoder and component-space checks,
    # while deliberately avoiding V1.run's world-axis metadata gate.
    v1_manifest, _ = _build_v1_manifest(child, {**grid, "lower": queries[0]["lower"], "upper": queries[0]["upper"]}, attempt_root)
    case = json.loads(v1_manifest.read_text(encoding="utf-8"))["cases"][0]
    case["selected_frames"] = selected
    case["query_times"] = list(QUERY_TIMES_S)
    component_axis = {
        "status": "BOUND_COMPONENT_SPACE_SOURCE_CONVENTION_AXIS_CALIBRATION_UNKNOWN",
        "producer_axis_orientation_metadata": "UNKNOWN",
        "reason": "ROOT207/ROOT217 source and decoder contracts bind SI/component fields; no world-axis claim is made",
    }
    calibrated_case = calibrated._case_result(case, component_axis, attempt_root)

    native_post: dict[int, dict[str, Any]] = {}
    for frame in selected:
        _, after = _read_stable(raw_root / f"Part_{frame:04d}.bi4", f"{label} native Part {frame} post-read", max_bytes=MAX_NATIVE_BYTES)
        if after != native_pre[frame]:
            raise GuardFailure(f"{label} native Part {frame} changed during decode")
        native_post[frame] = after
    return {
        "label": label,
        "identity": identity,
        "actual_control": {
            "generated_xml_TimeOut_s": float(xml_tout),
            "request_tout_s": float(request_tout),
            "receipt_command_tout_s": float(receipt_tout),
            "override_status": "RUNTIME_RECEIPT_OVERRIDE_CONFIRMED" if float(xml_tout) != float(receipt_tout) else "RUNTIME_RECEIPT_MATCHES_XML",
            "request_command": request.get("command"),
            "receipt_command": receipt.get("command"),
            "run_txt_present": (output_root / "Run.txt").is_file(),
            "run_out_present": (output_root / "Run.out").is_file(),
            "receipt_identity_status": identity_status,
        },
        "actual_saved_window": {
            "row_count": len(rows),
            "first": rows[0],
            "last": rows[-1],
            "queries": queries,
            "interpolation": "NOT_PERFORMED",
            "extrapolation": "FORBIDDEN",
        },
        "solver_receipt": receipt_record,
        "runparts": runparts_record,
        "generated_xml": xml_record,
        "calibrated_v1_case_result": calibrated_case,
        "axis_authority": component_axis,
        "native_endpoint_source_integrity": [
            {"frame": frame, "pre": native_pre[frame], "post": native_post[frame], "stable": native_pre[frame] == native_post[frame]}
            for frame in selected
        ],
        "native_payload_read_count": len(selected),
        "fields": "calibrated V1 native MassFluid/MassBound/Dp/Idp/role counts/weighted fluid COM/velocity/KE; component axis only",
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    manifest_path = args.manifest.expanduser().absolute()
    manifest, manifest_record = _read_json(manifest_path, "ROOT231 manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("status") != "PREPARED_NOT_RUN_ROOT231_QUERY234_SOURCE_ENDPOINT_AUDIT":
        raise GuardFailure("ROOT231 manifest schema/status mismatch")
    _verify_static_sources(manifest)
    joins = _verify_producer_joins(manifest)
    grids = manifest.get("grids")
    if not isinstance(grids, list) or len(grids) != 3:
        raise GuardFailure("ROOT231 requires exactly three grids")
    attempt_root = args.attempt_root.expanduser().absolute()
    outputs = [_run_grid(joins["child"], manifest, grid, attempt_root) for grid in grids]
    result = {
        "schema": SCHEMA,
        "status": PASS_STATUS,
        "manifest": manifest_record,
        "producer_join": {key: value for key, value in joins.items() if key != "child"},
        "query": {"query_times_s": list(QUERY_TIMES_S), "interpolation": "FORBIDDEN", "extrapolation": "FORBIDDEN"},
        "grids": outputs,
        "read_scope": {
            "native_payload_read_count": sum(int(item["native_payload_read_count"]) for item in outputs),
            "native_payload_read": "nearest lower/upper Part files for queries 2, 3, and 4 seconds only",
            "hdf5_read": False,
            "vtk_read": False,
            "full_native_tree_scan": False,
            "solver_launch": False,
        },
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0},
        "qualification_limits": [
            "component-space native endpoint fields only; producer world-axis remains UNKNOWN",
            "selected row indices are not native frame ids",
            "no interpolation or extrapolation",
            "query brackets are not output intervals or error bounds",
            "integration, spatial truth, event-time, and external-validation qualifications remain UNKNOWN",
        ],
    }
    calibrated.base.atomic_json(args.output.expanduser().absolute(), result)
    return result


def self_test() -> None:
    rows = [{"frame": 0, "time_s": 0.0}, {"frame": 199, "time_s": 1.995}, {"frame": 200, "time_s": 2.0001}]
    lower, upper = _nearest(rows, 2.0)
    assert lower["frame"] == 199 and upper["frame"] == 200
    assert _command_tout(["solver", "-tout:0.005"]) == "0.005"
    # Real CLI fixture: exercise the calibrated decoder case reader without
    # supplying axis_authority, proving component-space use does not inherit
    # ROOT225's unauthorized world-axis gate.
    with tempfile.TemporaryDirectory(prefix="root231-worker-") as temporary:
        root = Path(temporary)
        manifest_path = calibrated._fixture_manifest(root / "fixture")
        case = json.loads(manifest_path.read_text(encoding="utf-8"))["cases"][0]
        case["query_times"] = [0.0, 0.5]
        case_result = calibrated._case_result(case, {"status": "AXIS_UNKNOWN"}, root / "attempt")
        assert case_result["native_summary"]["MassFluid_kg"] == 2.0
        assert case_result["selected_observations"][0]["native_header"]["Dp"]["value"] == 0.01
    print("PASS_F1_S2_QUERY_ENDPOINT_OBSERVER_V2_SELFTEST")


def main() -> int:
    parser = argparse.ArgumentParser()
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
        _failure_report_v2(args.output.expanduser().absolute(), str(exc))
        print(f"FAIL_F1_S2_QUERY234_ENDPOINT_OBSERVER: {exc}")
        return 2
    print(json.dumps({"status": result["status"], "output": str(args.output.expanduser().absolute())}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
