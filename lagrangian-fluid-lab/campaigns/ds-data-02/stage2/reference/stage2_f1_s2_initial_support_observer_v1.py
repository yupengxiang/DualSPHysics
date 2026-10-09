#!/usr/bin/env python3
"""Guarded ROOT229 one-frame F1-S2 initial-support observer.

The parent reservation supplies exactly three deferred ``Part_0000.bi4``
files.  This worker hashes each selected file before and after invoking the
already calibrated official decoder, validates finite fields/typed ranges,
and records support against the independently closed 340 kg owner box.  The
native particle sample mass is retained as a discrete diagnostic and is never
rescaled to the continuous owner mass.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys
from typing import Any
import xml.etree.ElementTree as ET

import numpy as np

import stage2_f1_native_selected_observer_v1 as calibrated
import stage2_native_physical_observer_v2 as base


SCHEMA = "ds02.stage2.f1-s2.initial-support-observer.v1"
MANIFEST_SCHEMA = "ds02.stage2.f1-s2.initial-support-manifest.v1"
PASS_STATUS = "COMPLETE_F1_S2_INITIAL_NATIVE_SUPPORT_DIAGNOSTICS_NO_SCIENTIFIC_Q"
UNKNOWN_STATUS = "UNKNOWN_F1_S2_INITIAL_NATIVE_SUPPORT"
FAIL_STATUS = "FAILED_F1_S2_INITIAL_SUPPORT_GUARD"
QUALIFICATION = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0}
MAX_SMALL_BYTES = 16 * 1024 * 1024
MAX_NATIVE_BYTES = 512 * 1024 * 1024


class GuardFailure(RuntimeError):
    pass


def _stat_tuple(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def _stat_dict(value: os.stat_result) -> dict[str, int]:
    return {"dev": int(value.st_dev), "ino": int(value.st_ino), "bytes": int(value.st_size), "mtime_ns": int(value.st_mtime_ns), "ctime_ns": int(value.st_ctime_ns)}


def _read_stable(path: Path, label: str, *, max_bytes: int) -> tuple[bytes, dict[str, Any]]:
    path = path.expanduser().absolute()
    if path.is_symlink() or not path.is_file():
        raise GuardFailure(f"{label} is not a regular non-symlink file: {path}")
    before = path.stat()
    if before.st_size > max_bytes:
        raise GuardFailure(f"{label} exceeds bounded read: {path}")
    digest = hashlib.sha256()
    chunks: list[bytes] = []
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            chunks.append(chunk)
    after = path.stat()
    if _stat_tuple(before) != _stat_tuple(after):
        raise GuardFailure(f"{label} changed while being read: {path}")
    return b"".join(chunks), {"path": str(path), "sha256": digest.hexdigest(), "stat": _stat_dict(after)}


def _read_json(path: Path, label: str, expected_sha: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, record = _read_stable(path, label, max_bytes=MAX_SMALL_BYTES)
    if expected_sha is not None and record["sha256"] != expected_sha:
        raise GuardFailure(f"{label} SHA mismatch: {record['sha256']} != {expected_sha}")
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GuardFailure(f"invalid {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise GuardFailure(f"{label} root is not an object")
    return value, record


def _record_matches(record: dict[str, Any], label: str, *, max_bytes: int = MAX_SMALL_BYTES) -> dict[str, Any]:
    path_value = record.get("path")
    if not isinstance(path_value, str):
        raise GuardFailure(f"{label} has no path")
    _, actual = _read_stable(Path(path_value), label, max_bytes=max_bytes)
    if isinstance(record.get("sha256"), str) and actual["sha256"] != record["sha256"]:
        raise GuardFailure(f"{label} content SHA changed")
    expected_stat = record.get("stat")
    if isinstance(expected_stat, dict):
        for key in ("dev", "ino", "bytes", "mtime_ns", "ctime_ns"):
            if key in expected_stat and int(actual["stat"][key]) != int(expected_stat[key]):
                raise GuardFailure(f"{label} {key} changed")
    return actual


def _write_once(path: Path, value: Any) -> None:
    path = path.expanduser().absolute()
    if path.exists() or path.is_symlink():
        raise GuardFailure(f"refusing to overwrite output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _read_divider(xml_path: Path) -> dict[str, Any]:
    root = ET.fromstring(xml_path.read_bytes())
    matches: list[dict[str, Any]] = []
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1] != "drawbox" or node.get("cmt") != "asymmetric channel divider physical solid":
            continue
        point = next((child for child in node if child.tag.rsplit("}", 1)[-1] == "point"), None)
        size = next((child for child in node if child.tag.rsplit("}", 1)[-1] == "size"), None)
        if point is None or size is None:
            raise GuardFailure(f"divider drawbox missing point/size: {xml_path}")
        try:
            low = [float(point.get(axis)) for axis in ("x", "y", "z")]
            extent = [float(size.get(axis)) for axis in ("x", "y", "z")]
        except (TypeError, ValueError) as exc:
            raise GuardFailure(f"divider drawbox has nonnumeric geometry: {xml_path}") from exc
        if not all(math.isfinite(v) for v in low + extent) or any(v < 0 for v in extent):
            raise GuardFailure(f"divider drawbox has invalid geometry: {xml_path}")
        matches.append({"low_m": low, "high_m": [low[i] + extent[i] for i in range(3)], "source_cmt": node.get("cmt")})
    if len(matches) != 1:
        raise GuardFailure(f"expected one source divider drawbox, found {len(matches)}: {xml_path}")
    return matches[0]


def _support_summary(
    positions: np.ndarray,
    kind: np.ndarray,
    owner_low: np.ndarray,
    owner_high: np.ndarray,
    divider_low: np.ndarray,
    divider_high: np.ndarray,
    tolerance: float,
) -> dict[str, Any]:
    if positions.ndim != 2 or positions.shape[1] != 3:
        raise GuardFailure("decoded position field is not an N x 3 array")
    if not np.isfinite(positions).all():
        raise GuardFailure("decoded positions contain NaN or Inf")
    fluid = positions[kind == "fluid"]
    if fluid.size == 0:
        raise GuardFailure("decoded frame has no typed fluid particles")
    outside_mask = np.any((fluid < owner_low - tolerance) | (fluid > owner_high + tolerance), axis=1)
    excess = np.maximum(np.maximum(owner_low - fluid, fluid - owner_high), 0.0)
    max_excess = float(np.max(excess)) if excess.size else 0.0
    divider_mask = np.all((fluid >= divider_low - tolerance) & (fluid <= divider_high + tolerance), axis=1)
    return {
        "fluid_count": int(fluid.shape[0]),
        "fluid_position_finite": True,
        "owner_box": {
            "low_m": owner_low.tolist(),
            "high_m": owner_high.tolist(),
            "tolerance_m": tolerance,
            "outside_count": int(np.sum(outside_mask)),
            "max_outside_excess_m": max_excess,
            "within_registered_support": bool(not np.any(outside_mask)),
        },
        "divider_disjoint": {
            "low_m": divider_low.tolist(),
            "high_m": divider_high.tolist(),
            "tolerance_m": tolerance,
            "overlap_count": int(np.sum(divider_mask)),
            "no_fluid_overlap": bool(not np.any(divider_mask)),
        },
    }


def _verify_provenance(manifest: dict[str, Any]) -> dict[str, Any]:
    owner = manifest.get("owner_continuum")
    if not isinstance(owner, dict) or owner.get("mass_kg") != 340.0 or owner.get("volume_m3") != 0.34 or owner.get("density_kg_m3") != 1000.0:
        raise GuardFailure("manifest owner continuum is not the frozen 340 kg box")
    if owner.get("low_m") != [2.2, 0.0, 0.0] or owner.get("high_m") != [3.2, 1.0, 0.34]:
        raise GuardFailure("manifest owner bounds changed")
    tolerance = manifest.get("position_support_tolerance", {})
    if tolerance.get("value_m") != 1.0e-6 or tolerance.get("task_error_tolerance") is not False or tolerance.get("QN_credit") is not False:
        raise GuardFailure("position support tolerance was widened or relabeled as a task tolerance")
    provenance = manifest.get("provenance")
    if not isinstance(provenance, dict):
        raise GuardFailure("manifest provenance missing")
    root227 = provenance.get("root227", {})
    owner_proof, owner_proof_record = _read_json(Path(root227["path"]), "ROOT227 proof", root227["sha256"])
    if "CONTINUOUS_OWNER_340KG" not in str(owner_proof.get("status")):
        raise GuardFailure("ROOT227 proof status does not bind the 340 kg owner")
    owner_report, owner_report_record = _read_json(Path(owner_proof["report"]), "ROOT227 owner report", owner_proof.get("report_sha256"))
    if owner_report.get("qualification", {}).get("QN") != "UNKNOWN":
        raise GuardFailure("ROOT227 owner report promoted QN")
    root207 = provenance.get("root207", {})
    native_proof, native_proof_record = _read_json(Path(root207["path"]), "ROOT207 proof", root207["sha256"])
    child_record = root207.get("child_report", {})
    child, child_report_record = _read_json(Path(child_record["path"]), "ROOT207 child report", child_record["sha256"])
    if child.get("schema") != "ds02.stage2.f1.native-selected-observer.v1" or child.get("status") != "PASS_F1_NATIVE_HEADER_SELECTED_OBSERVABLES":
        raise GuardFailure("ROOT207 child report status/schema mismatch")
    wrapper_record = root207.get("wrapper_report", {})
    wrapper_actual = _record_matches(wrapper_record, "ROOT207 wrapper report")
    root217 = provenance.get("root217", {})
    calibration_proof, calibration_proof_record = _read_json(Path(root217["path"]), "ROOT217 proof", root217["sha256"])
    calibration_report_record = root217.get("report", {})
    calibration_report, calibration_report_actual = _read_json(Path(calibration_report_record["path"]), "ROOT217 report", calibration_report_record["sha256"])
    if calibration_report.get("scientific_qualification", {}).get("QI") not in (None, "UNKNOWN"):
        raise GuardFailure("ROOT217 manufactured calibration promoted QI")
    return {
        "root227_proof": owner_proof_record,
        "root227_report": owner_report_record,
        "root207_proof": native_proof_record,
        "root207_child": child_report_record,
        "root207_wrapper": wrapper_actual,
        "root217_proof": calibration_proof_record,
        "root217_report": calibration_report_actual,
        "child": child,
        "calibration": calibration_proof,
    }


def _verify_static_sources(manifest: dict[str, Any]) -> None:
    records = manifest.get("static_source_records")
    if not isinstance(records, list) or not records:
        raise GuardFailure("manifest static source records missing")
    for record in records:
        if not isinstance(record, dict):
            raise GuardFailure("static source record is not an object")
        _record_matches(record, f"static source {record.get('label', record.get('path'))}")


def _verify_case_identity(label: str, receipt: dict[str, Any], identity: dict[str, Any]) -> str:
    request = receipt.get("request")
    if not isinstance(request, dict):
        raise GuardFailure(f"{label} receipt has no request")
    if label in {"coarse", "fine"}:
        if request.get("family_id") != "F1" or request.get("sentinel_id") != "F1-S2" or request.get("physical_case_id") != "F1_DUAL_HEAD_340_UNCHANGED_MOTHER_GEOMETRY_V1":
            raise GuardFailure(f"{label} request physical identity mismatch")
        return "REQUEST_V1_F1_S2_PHYSICAL_IDENTITY"
    if request.get("family_id") != "F1" or request.get("case_id") != "F1_STAGE1_DUAL_H340_DP020" or request.get("sentinel_id") is not None or request.get("physical_case_id") != "F1_DUAL_HEAD_340_UNCHANGED_MOTHER_GEOMETRY_V1":
        raise GuardFailure(f"{label} historical request identity mismatch")
    return "HISTORICAL_RUNNER_V2_EXACT_F1_CASE_ID_SENTINEL_ABSENT"


def _run_case(
    case: dict[str, Any],
    manifest: dict[str, Any],
    attempt_root: Path,
    joins: dict[str, Any],
) -> dict[str, Any]:
    label = str(case["label"])
    records = [item for item in manifest["deferred_native_records"] if item.get("grid") == label or (label == item.get("grid"))]
    # The builder emits one record per grid.  The explicit condition above
    # leaves the check readable in reports and rejects accidental batching.
    if len(records) != 1:
        raise GuardFailure(f"{label} must have exactly one deferred frame-0 Part record")
    record = records[0]
    source_xml = Path(case["generated_xml"]["path"])
    runparts = Path(case["runparts"]["path"])
    raw_root = Path(case["raw_root"])
    decoder = Path(case["decoder"]["path"])
    receipt_path = Path(case["solver_receipt"]["path"])
    _, runparts_actual = _read_stable(runparts, f"{label} RunPARTs", max_bytes=MAX_SMALL_BYTES)
    if runparts_actual["sha256"] != case["runparts"]["sha256"]:
        raise GuardFailure(f"{label} RunPARTs changed after preparation")
    rows = base.read_runparts(runparts)
    if not rows or rows[0]["part"] != 0 or rows[0]["time_s"] != 0.0:
        raise GuardFailure(f"{label} does not have exact frame-0 t=0 source row")
    xml_payload, xml_actual = _read_stable(source_xml, f"{label} generated XML", max_bytes=MAX_SMALL_BYTES)
    if xml_actual["sha256"] != case["generated_xml"]["sha256"]:
        raise GuardFailure(f"{label} generated XML changed after preparation")
    receipt, receipt_actual = _read_json(receipt_path, f"{label} solver receipt", case["solver_receipt"]["sha256"])
    if receipt.get("status") != "completed" or receipt.get("returncode") not in (0, "0"):
        raise GuardFailure(f"{label} solver receipt is not completed/0")
    identity_status = _verify_case_identity(label, receipt, case["identity"])
    output_root = Path(str(receipt.get("output_root", ""))).expanduser().absolute()
    if raw_root.expanduser().absolute() != output_root / "solver_output" / "data":
        raise GuardFailure(f"{label} raw_root does not match receipt output_root")
    part_path = raw_root / "Part_0000.bi4"
    if Path(record["path"]).expanduser().absolute() != part_path.absolute() or int(record["frame"]) != 0:
        raise GuardFailure(f"{label} deferred Part path does not match frame 0")
    if record.get("sha256") != "PARENT_AFTER_RESERVATION":
        raise GuardFailure(f"{label} deferred SHA was filled before parent reservation")
    divider = _read_divider(source_xml)
    expected_divider = case.get("divider")
    if expected_divider != divider:
        raise GuardFailure(f"{label} source divider changed after preparation")
    scratch = attempt_root / "scratch" / label
    pre_payload, pre = _read_stable(part_path, f"{label} native Part_0000 pre-read", max_bytes=MAX_NATIVE_BYTES)
    del pre_payload
    try:
        decoded = base.decode_frame(part_path, decoder, scratch, 0)
        header = {
            "MassFluid": calibrated._native_scalar("MassFluid", decoded["metadata"], decoded["info"], required=True),
            "MassBound": calibrated._native_scalar("MassBound", decoded["metadata"], decoded["info"], required=False),
            "Dp": calibrated._native_scalar("Dp", decoded["metadata"], decoded["info"], required=True),
        }
        identity = calibrated._idp_summary(decoded["ids"])
        source = base.parse_source_xml(source_xml)
        counts, kind, mkfluid, mk_absolute = calibrated._role_counts(decoded["ids"], source)
        observables = calibrated._weighted_observables(decoded, source, header)
        positions = decoded["position"]
        owner_low = np.asarray(manifest["owner_continuum"]["low_m"], dtype=np.float64)
        owner_high = np.asarray(manifest["owner_continuum"]["high_m"], dtype=np.float64)
        divider_low = np.asarray(divider["low_m"], dtype=np.float64)
        divider_high = np.asarray(divider["high_m"], dtype=np.float64)
        support = _support_summary(positions, kind, owner_low, owner_high, divider_low, divider_high, 1.0e-6)
        fluid_mask = kind == "fluid"
        fluid_mk_relative = sorted(set(int(value) for value in mkfluid[fluid_mask].tolist()))
        fluid_mk_absolute = sorted(set(int(value) for value in mk_absolute[fluid_mask].tolist()))
        expected_fluid = sum(int(block["count"]) for block in source["blocks"] if block["kind"] == "fluid")
        if counts["fluid"] != expected_fluid or fluid_mk_relative != [0] or fluid_mk_absolute != [1]:
            raise GuardFailure(f"{label} typed fluid/MK mapping differs from source XML")
        if not all(observables["role_counts"].get(key) == counts.get(key) for key in ("fluid", "fixed", "moving", "floating", "unknown", "total")):
            raise GuardFailure(f"{label} role count arithmetic mismatch")
    except (base.UnsupportedSemantics, ValueError, KeyError) as exc:
        raise GuardFailure(f"{label} calibrated decoder/support failure: {exc}") from exc
    _, post = _read_stable(part_path, f"{label} native Part_0000 post-read", max_bytes=MAX_NATIVE_BYTES)
    if pre != post:
        raise GuardFailure(f"{label} native Part_0000 changed during decode")
    residual = [str(path) for path in scratch.rglob("*") if path.is_file()] if scratch.exists() else []
    if residual:
        raise GuardFailure(f"{label} decoder scratch was not cleaned: {residual[:3]}")
    sample_mass = float(observables["fluid_observable_using_native_MassFluid"]["sample_mass_kg"])
    return {
        "label": label,
        "identity": case["identity"],
        "solver_receipt": receipt_actual,
        "time": {"runparts_s": rows[0]["time_s"], "decoded_s": decoded["decoded_time_s"], "interpolation": "NOT_PERFORMED"},
        "native_source_integrity": {"frame": 0, "pre": pre, "post": post, "stable": pre == post},
        "native_header": header,
        "native_Idp": identity,
        "typed_role_counts": counts,
        "fluid_mk_mapping": {"mkfluid_relative": fluid_mk_relative, "mk_absolute": fluid_mk_absolute, "status": "PASS_SOURCE_XML_TYPED_RANGE"},
        "support": support,
        "native_observables": observables,
        "mass_separation": {"continuous_owner_mass_kg": 340.0, "native_sample_mass_kg": sample_mass, "native_minus_owner_kg": sample_mass - 340.0, "native_sample_is_not_continuum_truth": True, "rescale": "FORBIDDEN"},
        "world_axis_calibration": "UNKNOWN_PRODUCER_ORIENTATION_METADATA_NOT_INFERRED",
        "receipt_identity_status": identity_status,
        "scratch_files_after_decode": residual,
    }


def _unknown(output: Path, reason: str) -> dict[str, Any]:
    result = {"schema": SCHEMA, "status": UNKNOWN_STATUS, "reason": reason, "scientific_qualification": QUALIFICATION, "read_scope": {"native_payload_read": "UNKNOWN_OR_PARTIAL", "solver_launch": False}}
    _write_once(output, result)
    return result


def run(args: argparse.Namespace) -> dict[str, Any]:
    manifest_path = args.manifest.expanduser().absolute()
    manifest, manifest_record = _read_json(manifest_path, "ROOT229 manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("status") != "PREPARED_NOT_RUN_ROOT229_INITIAL_SUPPORT_SOURCE_AUDIT":
        raise GuardFailure("ROOT229 manifest schema/status mismatch")
    _verify_static_sources(manifest)
    joins = _verify_provenance(manifest)
    grids = manifest.get("grids")
    if not isinstance(grids, list) or len(grids) != 3 or {item.get("label") for item in grids} != {"coarse", "medium", "fine"}:
        raise GuardFailure("ROOT229 requires coarse/medium/fine grid records")
    attempt_root = args.attempt_root.expanduser().absolute()
    outputs = [_run_case(case, manifest, attempt_root, joins) for case in grids]
    result = {
        "schema": SCHEMA,
        "status": PASS_STATUS,
        "manifest": manifest_record,
        "producer_join": {key: value for key, value in joins.items() if key not in {"child", "calibration"}},
        "owner_continuum": {"mass_kg": 340.0, "volume_m3": 0.34, "density_kg_m3": 1000.0, "mass_source": "ROOT227 owner closure"},
        "grids": outputs,
        "read_scope": {"native_payload_read_count": 3, "native_payload_read": "three selected Part_0000.bi4 files only", "hdf5_read": False, "vtk_read": False, "full_native_tree_scan": False, "solver_launch": False},
        "scientific_qualification": QUALIFICATION,
        "qualification_limits": ["position tolerance is binary support containment only, not a QN task tolerance", "native sample mass remains separate from 340 kg continuous owner mass", "producer world-axis calibration remains UNKNOWN", "no interpolation, integration, spatial-truth, or external-validation credit"],
    }
    _write_once(args.output.expanduser().absolute(), result)
    return result


def self_test() -> None:
    positions = np.asarray([[2.2, 0.0, 0.0], [3.2, 1.0, 0.34]], dtype=np.float64)
    kinds = np.asarray(["fluid", "fluid"], dtype=object)
    result = _support_summary(positions, kinds, np.asarray([2.2, 0.0, 0.0]), np.asarray([3.2, 1.0, 0.34]), np.asarray([1.2, 0.34, 0.0]), np.asarray([2.0, 0.4, 0.7]), 1.0e-6)
    assert result["owner_box"]["within_registered_support"] is True
    assert result["divider_disjoint"]["no_fluid_overlap"] is True
    outside = _support_summary(np.asarray([[3.200002, 0.5, 0.1]], dtype=np.float64), kinds[:1], np.asarray([2.2, 0.0, 0.0]), np.asarray([3.2, 1.0, 0.34]), np.asarray([1.2, 0.34, 0.0]), np.asarray([2.0, 0.4, 0.7]), 1.0e-6)
    assert outside["owner_box"]["within_registered_support"] is False
    overlap = _support_summary(np.asarray([[1.5, 0.35, 0.1]], dtype=np.float64), kinds[:1], np.asarray([0.0, 0.0, 0.0]), np.asarray([3.2, 1.0, 0.34]), np.asarray([1.2, 0.34, 0.0]), np.asarray([2.0, 0.4, 0.7]), 1.0e-6)
    assert overlap["divider_disjoint"]["no_fluid_overlap"] is False
    print("PASS_F1_S2_INITIAL_SUPPORT_OBSERVER_V1_SELFTEST")


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
    except base.UnsupportedSemantics as exc:
        result = _unknown(args.output.expanduser().absolute(), str(exc))
    except Exception as exc:
        print(f"FAIL_F1_S2_INITIAL_SUPPORT_OBSERVER: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": result["status"], "output": str(args.output.expanduser().absolute())}, sort_keys=True))
    return 0 if result["status"] == PASS_STATUS else 2


if __name__ == "__main__":
    raise SystemExit(main())
