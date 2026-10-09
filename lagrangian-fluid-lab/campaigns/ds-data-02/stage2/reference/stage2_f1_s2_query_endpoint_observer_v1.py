#!/usr/bin/env python3
"""Guarded ROOT225 observer for the actual native frames around t=1 s.

Preparation records the six native Part files without opening them.  The
parent reservation is responsible for running this worker with the source
paths in ``deferred_native_records``.  The worker then performs a stable
pre-read hash/stat check, calls the already calibrated V1 observer on exactly
the two RunPARTs rows bracketing 1 s for each grid, and performs the same
stable post-read check.  It deliberately reports the sparse endpoint fields
only; it never interpolates and grants no numerical qualification.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any
import xml.etree.ElementTree as ET

import stage2_f1_native_selected_observer_v1 as calibrated


SCHEMA = "ds02.stage2.f1-s2.query-endpoint-observer.v1"
MANIFEST_SCHEMA = "ds02.stage2.f1-s2.query-endpoint-manifest.v1"
PASS_STATUS = "COMPLETE_QUERY_ENDPOINT_NATIVE_DIAGNOSTICS_NO_SCIENTIFIC_Q"
FAIL_STATUS = "FAILED_QUERY_ENDPOINT_GUARD"
UNKNOWN_STATUS = "UNKNOWN_QUERY_ENDPOINT_NATIVE_DIAGNOSTICS"
QUERY_TIME_S = 1.0
MAX_SMALL_BYTES = 16 * 1024 * 1024
MAX_NATIVE_BYTES = 512 * 1024 * 1024
ROOT207_SHA = "c2016d5a36922230eafc57c49baadaeff3a2bc920bb953b5fef215eb9fda30ab"
ROOT207_CHILD_SHA = "d588f17021c3b1418ac73e343d6c323f2d8850d2be1148d39bba7243ce101fb2"
ROOT217_SHA = "7df9b02c339e3b3eb8bae8f108c16d5db0fd2b6cb3f03d192c4edc827ae1bdf0"
ROOT223_SHA = "23f79366541c609e3cfb42c99ec0419ddf4fecca63aaf9d5c12c9ecbc22a9b84"


class GuardFailure(RuntimeError):
    """A source or endpoint condition that invalidates this bounded read."""


def _stat_tuple(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def _stat_dict(value: os.stat_result) -> dict[str, int]:
    return {
        "dev": int(value.st_dev),
        "ino": int(value.st_ino),
        "bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
    }


def _read_stable(path: Path, label: str, *, max_bytes: int | None = MAX_SMALL_BYTES) -> tuple[bytes, dict[str, Any]]:
    path = path.expanduser().absolute()
    if path.is_symlink() or not path.is_file():
        raise GuardFailure(f"{label} is not a regular file: {path}")
    before = path.stat()
    if max_bytes is not None and before.st_size > max_bytes:
        raise GuardFailure(f"{label} exceeds bounded read ({before.st_size} bytes): {path}")
    digest = hashlib.sha256()
    chunks: list[bytes] = []
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            chunks.append(chunk)
    after = path.stat()
    if _stat_tuple(before) != _stat_tuple(after):
        raise GuardFailure(f"{label} changed during read: {path}")
    return b"".join(chunks), {
        "path": str(path),
        "sha256": digest.hexdigest(),
        "stat": _stat_dict(after),
    }


def _read_json(path: Path, label: str, expected_sha: str | None = None, *, max_bytes: int | None = MAX_SMALL_BYTES) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, record = _read_stable(path, label, max_bytes=max_bytes)
    if expected_sha is not None and record["sha256"] != expected_sha:
        raise GuardFailure(f"{label} SHA mismatch: {record['sha256']} != {expected_sha}")
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GuardFailure(f"invalid {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise GuardFailure(f"{label} root is not an object")
    return value, record


def _record_matches(record: dict[str, Any], label: str, *, max_bytes: int | None = MAX_SMALL_BYTES) -> dict[str, Any]:
    path_value = record.get("path")
    if not isinstance(path_value, str):
        raise GuardFailure(f"{label} has no path")
    actual_payload, actual = _read_stable(Path(path_value), label, max_bytes=max_bytes)
    del actual_payload
    expected_sha = record.get("sha256")
    if isinstance(expected_sha, str) and actual["sha256"] != expected_sha:
        raise GuardFailure(f"{label} content changed: {actual['sha256']} != {expected_sha}")
    expected_bytes = record.get("bytes")
    if expected_bytes is not None and int(actual["stat"]["bytes"]) != int(expected_bytes):
        raise GuardFailure(f"{label} size changed")
    expected_stat = record.get("stat")
    if isinstance(expected_stat, dict):
        for key in ("dev", "ino", "mtime_ns", "ctime_ns"):
            if key in expected_stat and int(actual["stat"][key]) != int(expected_stat[key]):
                raise GuardFailure(f"{label} {key} changed")
    return actual


def _parse_runparts(payload: bytes, label: str) -> list[dict[str, Any]]:
    try:
        text = payload.decode("utf-8", errors="replace")
    except Exception as exc:  # pragma: no cover - bytes.decode is total
        raise GuardFailure(f"cannot decode {label}: {exc}") from exc
    lines = [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    if not lines:
        raise GuardFailure(f"{label} is empty")
    reader = csv.DictReader(lines, delimiter=";")
    rows: list[dict[str, Any]] = []
    for row in reader:
        clean = {(key or "").strip(): (value or "").strip() for key, value in row.items()}
        raw_part = clean.get("Part", "").split("#", 1)[0].strip()
        raw_time = clean.get("TimeStep [s]", "").split("#", 1)[0].strip()
        try:
            part = int(raw_part)
            time_s = float(raw_time)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(time_s):
            raise GuardFailure(f"{label} contains non-finite time")
        rows.append({"frame": part, "time_s": time_s})
    rows.sort(key=lambda row: row["frame"])
    if not rows or [row["frame"] for row in rows] != list(range(len(rows))):
        raise GuardFailure(f"{label} frame ids are not contiguous from zero")
    if any(right["time_s"] <= left["time_s"] for left, right in zip(rows, rows[1:])):
        raise GuardFailure(f"{label} times are not strictly increasing")
    return rows


def _nearest(rows: list[dict[str, Any]], query: float) -> tuple[dict[str, Any], dict[str, Any]]:
    lower = [row for row in rows if row["time_s"] <= query]
    upper = [row for row in rows if row["time_s"] >= query]
    if not lower or not upper:
        raise GuardFailure(f"query {query} is outside actual saved window")
    return max(lower, key=lambda row: row["time_s"]), min(upper, key=lambda row: row["time_s"])


def _command_tout(command: Any) -> str | None:
    if not isinstance(command, list):
        return None
    for item in command:
        if isinstance(item, str) and item.startswith("-tout:"):
            return item.split(":", 1)[1]
    return None


def _xml_timeout(payload: bytes, label: str) -> str | None:
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise GuardFailure(f"invalid {label}: {exc}") from exc
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1] == "parameter" and node.get("key") == "TimeOut":
            return node.get("value")
    return None


def _expected_record(manifest: dict[str, Any], path: str) -> dict[str, Any] | None:
    for record in manifest.get("static_source_records", []):
        if isinstance(record, dict) and record.get("path") == path:
            return record
    return None


def _verify_producer_joins(manifest: dict[str, Any]) -> dict[str, Any]:
    root223 = manifest.get("root223")
    if not isinstance(root223, dict):
        raise GuardFailure("manifest has no ROOT223 binding")
    proof, proof_record = _read_json(Path(root223["path"]), "ROOT223 proof", ROOT223_SHA)
    if proof.get("status") != "VERIFIED_ACTUAL_F1_S2_THREE_GRID_SELECTED_COMPONENT_DIAGNOSTICS_ONLY":
        raise GuardFailure("ROOT223 status is not the consumed diagnostics-only status")
    report_path = Path(proof.get("report", ""))
    report, report_record = _read_json(report_path, "ROOT223 report", proof.get("report_sha256"))
    if report.get("schema") != "ds02.stage2.f1-s2.component-space-compare.v1":
        raise GuardFailure("ROOT223 report schema mismatch")
    producer = proof.get("source_producer_proof", {})
    if producer.get("sha256") != ROOT207_SHA:
        raise GuardFailure("ROOT223 does not bind ROOT207 proof")
    child_binding = proof.get("actual_native_child_report", {})
    if child_binding.get("sha256") != ROOT207_CHILD_SHA:
        raise GuardFailure("ROOT223 does not bind ROOT207 child report")
    child, child_record = _read_json(Path(child_binding["path"]), "ROOT207 child report", ROOT207_CHILD_SHA)
    if child.get("schema") != "ds02.stage2.f1.native-selected-observer.v1":
        raise GuardFailure("ROOT207 child schema mismatch")
    root217_binding = manifest.get("root217")
    if not isinstance(root217_binding, dict):
        raise GuardFailure("manifest has no ROOT217 calibration binding")
    calibration, calibration_record = _read_json(Path(root217_binding["path"]), "ROOT217 proof", ROOT217_SHA)
    if calibration.get("status") != "VERIFIED_ACTUAL_OFFICIAL_WRITER_DECODER_OBSERVER_V4_MANUFACTURED_CALIBRATION_ONLY":
        raise GuardFailure("ROOT217 calibration status mismatch")
    calibration_report_path = Path(calibration.get("report", ""))
    calibration_report, calibration_report_record = _read_json(
        calibration_report_path, "ROOT217 calibration report", calibration.get("report_sha256")
    )
    if calibration_report.get("schema") != "ds02.stage2.f1.bi4-official-writer-calibration.v4":
        raise GuardFailure("ROOT217 calibration report schema mismatch")
    if calibration.get("scientific_qualification", {}).get("QI") not in ("UNKNOWN", None):
        raise GuardFailure("ROOT217 manufactured calibration was promoted to QI")
    return {
        "root223_proof": proof_record,
        "root223_report": report_record,
        "root207_child": child_record,
        "root217_proof": calibration_record,
        "root217_report": calibration_report_record,
        "child": child,
    }


def _verify_static_sources(manifest: dict[str, Any]) -> None:
    for record in manifest.get("static_source_records", []):
        if not isinstance(record, dict):
            raise GuardFailure("static source record is not an object")
        _record_matches(record, f"static source {record.get('label', record.get('path'))}")


def _build_v1_manifest(
    child: dict[str, Any],
    grid: dict[str, Any],
    attempt_root: Path,
) -> tuple[Path, Path]:
    lower = grid["lower"]
    upper = grid["upper"]
    if int(lower["frame"]) == int(upper["frame"]):
        selected = [int(lower["frame"])]
    else:
        selected = [int(lower["frame"]), int(upper["frame"])]
    case = {
        "label": grid["case_label"],
        "identity": grid["identity"],
        "raw_root": grid["raw_root"],
        "runparts": grid["runparts"]["path"],
        "generated_xml": grid["generated_xml"]["path"],
        "decoder": grid["decoder"]["path"],
        "decoder_source": grid["decoder_source"]["path"],
        "expected_frame_count": int(grid["expected_frame_count"]),
        "expected_final_time_s": float(grid["last_frame"]["time_s"]),
        "selected_frames": selected,
        "query_times": [QUERY_TIME_S],
        "scratch_root": str(attempt_root / "scratch" / grid["label"]),
    }
    path = attempt_root / "inputs" / f"{grid['label']}_calibrated_v1_manifest.json"
    output = attempt_root / "observer" / f"{grid['label']}_calibrated_v1.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise GuardFailure(f"refusing to overwrite temporary V1 manifest: {path}")
    path.write_text(json.dumps({
        "schema": "ds02.stage2.f1.native-selected-observer-manifest.v1",
        "axis_authority": child["axis_authority"],
        "cases": [case],
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path, output


def _native_records_for_grid(manifest: dict[str, Any], label: str) -> list[dict[str, Any]]:
    records = [item for item in manifest.get("deferred_native_records", []) if item.get("grid") == label]
    if len(records) not in (1, 2):
        raise GuardFailure(f"{label} deferred native endpoint count is {len(records)}")
    if any(item.get("sha256") != "PARENT_AFTER_RESERVATION" for item in records):
        raise GuardFailure(f"{label} deferred native SHA policy was replaced before reservation")
    return records


def _run_grid(child: dict[str, Any], manifest: dict[str, Any], grid: dict[str, Any], attempt_root: Path) -> dict[str, Any]:
    label = str(grid["label"])
    records = _native_records_for_grid(manifest, label)
    receipt_path = Path(grid["solver_receipt"]["path"])
    receipt, receipt_record = _read_json(receipt_path, f"{label} solver receipt", grid["solver_receipt"]["sha256"])
    if receipt.get("status") != "completed" or receipt.get("returncode") not in (0, "0"):
        raise GuardFailure(f"{label} solver receipt is not completed/0")
    request = receipt.get("request")
    if not isinstance(request, dict):
        raise GuardFailure(f"{label} solver receipt has no request object")
    identity = grid["identity"]
    if label in {"coarse", "fine"}:
        if request.get("sentinel_id") != "F1-S2" or request.get("physical_case_id") != identity.get("physical_case_id"):
            raise GuardFailure(f"{label} solver request physical identity mismatch")
        receipt_identity_status = "REQUEST_V1_F1_S2_PHYSICAL_IDENTITY"
    else:
        if (
            request.get("family_id") != "F1"
            or request.get("case_id") != "F1_STAGE1_DUAL_H340_DP020"
            or request.get("sentinel_id") is not None
            or request.get("physical_case_id") != identity.get("physical_case_id")
        ):
            raise GuardFailure(f"{label} historical runner-v2 solver request identity mismatch")
        receipt_identity_status = "HISTORICAL_RUNNER_V2_EXACT_F1_CASE_ID_PHYSICAL_IDENTITY_ABSENT"
    runparts_payload, runparts_record = _read_stable(Path(grid["runparts"]["path"]), f"{label} RunPARTs")
    if runparts_record["sha256"] != grid["runparts"]["sha256"]:
        raise GuardFailure(f"{label} RunPARTs SHA changed since preparation")
    rows = _parse_runparts(runparts_payload, f"{label} RunPARTs")
    if len(rows) != int(grid["expected_frame_count"]):
        raise GuardFailure(f"{label} RunPARTs row count changed")
    if rows[0] != grid["first_frame"] or rows[-1] != grid["last_frame"]:
        raise GuardFailure(f"{label} RunPARTs endpoint changed since preparation")
    lower, upper = _nearest(rows, QUERY_TIME_S)
    if lower != grid["lower"] or upper != grid["upper"]:
        raise GuardFailure(f"{label} nearest query endpoints changed")
    xml_payload, xml_record = _read_stable(Path(grid["generated_xml"]["path"]), f"{label} generated XML")
    if xml_record["sha256"] != grid["generated_xml"]["sha256"]:
        raise GuardFailure(f"{label} generated XML SHA changed")
    xml_tout = _xml_timeout(xml_payload, f"{label} generated XML")
    request_tout = _command_tout(request.get("command"))
    receipt_tout = _command_tout(receipt.get("command"))
    if xml_tout is None or request_tout is None or receipt_tout is None:
        raise GuardFailure(f"{label} lacks XML/request/receipt tout evidence")
    if request_tout != receipt_tout:
        raise GuardFailure(f"{label} request and executed receipt tout differ")
    if float(grid["actual_request_tout_s"]) != float(request_tout):
        raise GuardFailure(f"{label} prepared request tout differs from actual receipt request")
    output_root = Path(str(receipt.get("output_root", ""))).expanduser().absolute()
    raw_root = Path(grid["raw_root"]).expanduser().absolute()
    if raw_root.parent != output_root / "solver_output":
        raise GuardFailure(f"{label} raw_root is not the solver receipt output/data root")
    native_pre: list[dict[str, Any]] = []
    for item in records:
        part_path = Path(item["path"])
        if part_path != raw_root / f"Part_{int(item['frame']):04d}.bi4":
            raise GuardFailure(f"{label} deferred Part path does not match selected RunPARTs frame")
        _, pre = _read_stable(part_path, f"{label} native Part {item['frame']}", max_bytes=MAX_NATIVE_BYTES)
        native_pre.append(pre)
    v1_manifest, v1_output = _build_v1_manifest(child, grid, attempt_root)
    calibrated_result = calibrated.run(argparse.Namespace(manifest=v1_manifest, output=v1_output, attempt_root=attempt_root))
    if calibrated_result.get("status") != calibrated.PASS_STATUS:
        raise GuardFailure(f"{label} calibrated V1 observer did not complete")
    _, v1_record = _read_json(v1_output, f"{label} calibrated V1 output", max_bytes=MAX_SMALL_BYTES)
    native_post: list[dict[str, Any]] = []
    for item, before in zip(records, native_pre):
        _, after = _read_stable(Path(item["path"]), f"{label} native Part {item['frame']} post-read", max_bytes=MAX_NATIVE_BYTES)
        if after != before:
            raise GuardFailure(f"{label} native Part {item['frame']} changed during decode")
        native_post.append(after)
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
            "receipt_identity_status": receipt_identity_status,
        },
        "actual_saved_window": {
            "row_count": len(rows),
            "first": rows[0],
            "last": rows[-1],
            "query_time_s": QUERY_TIME_S,
            "lower": lower,
            "upper": upper,
            "selected_row_index_is_not_native_frame_id": True,
            "interpolation": "NOT_PERFORMED",
        },
        "solver_receipt": receipt_record,
        "runparts": runparts_record,
        "generated_xml": xml_record,
        "calibrated_v1_output": v1_record,
        "native_endpoint_source_integrity": [
            {"endpoint": item["endpoint"], "frame": int(item["frame"]), "pre": pre, "post": post, "stable": pre == post}
            for item, pre, post in zip(records, native_pre, native_post)
        ],
        "native_payload_read_count": len(records),
        "fields": "calibrated V1 native MassFluid/MassBound/Dp/Idp/role counts/weighted fluid COM/velocity/KE",
    }


def _failure_report(output: Path, reason: str) -> None:
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


def run(args: argparse.Namespace) -> dict[str, Any]:
    manifest_path = args.manifest.expanduser().absolute()
    manifest, manifest_record = _read_json(manifest_path, "ROOT225 manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise GuardFailure("ROOT225 manifest schema mismatch")
    if manifest.get("status") != "PREPARED_NOT_RUN_ROOT225_SOURCE_AND_ENDPOINT_AUDIT":
        raise GuardFailure("ROOT225 manifest is not the immutable prepared status")
    _verify_static_sources(manifest)
    joins = _verify_producer_joins(manifest)
    attempt_root = args.attempt_root.expanduser().absolute()
    grids = manifest.get("grids")
    if not isinstance(grids, list) or len(grids) != 3:
        raise GuardFailure("ROOT225 requires exactly three grids")
    outputs = [_run_grid(joins["child"], manifest, grid, attempt_root) for grid in grids]
    result = {
        "schema": SCHEMA,
        "status": PASS_STATUS,
        "manifest": manifest_record,
        "producer_join": {key: value for key, value in joins.items() if key != "child"},
        "query": {"query_time_s": QUERY_TIME_S, "interpolation": "FORBIDDEN", "extrapolation": "FORBIDDEN"},
        "grids": outputs,
        "read_scope": {
            "native_payload_read_count": sum(int(item["native_payload_read_count"]) for item in outputs),
            "native_payload_read": "six selected Part files only",
            "hdf5_read": False,
            "vtk_read": False,
            "full_native_tree_scan": False,
            "solver_launch": False,
        },
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0},
        "qualification_limits": [
            "lower/upper native endpoint fields only",
            "selected observation row indices are not native frame ids",
            "no interpolation or extrapolation",
            "one-second query gap is not an output interval or error bound",
            "runtime control equivalence is recorded from each receipt, not inferred from XML",
            "integration, spatial truth, event-time, and external-validation qualifications remain UNKNOWN",
        ],
    }
    calibrated.base.atomic_json(args.output.expanduser().absolute(), result)
    return result


def self_test() -> None:
    rows = [{"frame": 0, "time_s": 0.0}, {"frame": 199, "time_s": 0.9950233}, {"frame": 200, "time_s": 1.0001903}]
    lower, upper = _nearest(rows, QUERY_TIME_S)
    assert lower["frame"] == 199 and upper["frame"] == 200
    assert _command_tout(["solver", "-tout:0.005"]) == "0.005"
    assert _command_tout(["solver", "-gpu:0"]) is None
    with tempfile.TemporaryDirectory(prefix="root225-worker-") as temporary:
        path = Path(temporary) / "small.json"
        path.write_text('{"ok":true}\n', encoding="utf-8")
        payload, record = _read_stable(path, "manufactured metadata")
        assert json.loads(payload)["ok"] is True and record["stat"]["bytes"] > 0
    print("PASS_F1_S2_QUERY_ENDPOINT_OBSERVER_V1_SELFTEST")


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
        _failure_report(args.output.expanduser().absolute(), str(exc))
        print(f"FAIL_F1_S2_QUERY_ENDPOINT_OBSERVER: {exc}")
        return 2
    print(json.dumps({"status": result["status"], "output": str(args.output.expanduser().absolute())}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
