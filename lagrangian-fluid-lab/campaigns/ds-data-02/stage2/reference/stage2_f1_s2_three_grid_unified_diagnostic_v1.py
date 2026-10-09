#!/usr/bin/env python3
"""ROOT246 compact F1-S2 three-grid diagnostic consumer.

This worker joins the four completed, small JSON studies for F1-S2:
ROOT227's continuous-owner audit, ROOT233's frame-zero support audit,
ROOT234's one-second endpoint audit, and ROOT231's two/three/four-second
endpoint audit.  It reads only those proofs, their JSON reports, requests,
and execution receipts.  It never opens a BI4, H5, VTK, RunPARTs, or solver
output payload.

The result is deliberately a control and evidence diagnostic.  Native
component fields are retained at their actual saved times.  No interpolation,
neighbour-grid truth, integration-error claim, or scientific Q credit is
created from asynchronous brackets.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import tempfile
from typing import Any, Iterable


HERE = Path(__file__).resolve().parent
CONTRACT = HERE / "stage2_f1_s2_three_grid_unified_diagnostic_contract_v1.json"
SCHEMA = "ds02.stage2.f1-s2.three-grid-unified-diagnostic.v1"
MANIFEST_SCHEMA = "ds02.stage2.f1-s2.three-grid-unified-diagnostic-manifest.v1"
PASS_STATUS = "COMPLETE_F1_S2_THREE_GRID_UNIFIED_DIAGNOSTICS_NO_SCIENTIFIC_Q"
FAIL_STATUS = "FAILED_F1_S2_THREE_GRID_UNIFIED_DIAGNOSTIC_GUARD"
MAX_JSON_BYTES = 4 * 1024 * 1024
TIME_EPS = 1.0e-12
GRID_LABELS = ("coarse", "medium", "fine")
EXPECTED_DP = {"coarse": 0.0225, "medium": 0.02, "fine": 0.017}
EXPECTED_QUERIES = {"query1": (1.0,), "query234": (2.0, 3.0, 4.0)}
PHYSICAL_CASE = "F1_DUAL_HEAD_340_UNCHANGED_MOTHER_GEOMETRY_V1"
QUALIFICATION = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0}


class GuardFailure(RuntimeError):
    """Raised when a producer or diagnostic contract is not closed."""


def _abs(path: str | Path) -> Path:
    return Path(path).expanduser().absolute()


def _stat_tuple(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def _stable_bytes(path: str | Path, label: str, expected_sha: str | None = None) -> tuple[bytes, dict[str, Any]]:
    """Read one bounded JSON/source file with a complete pre/post stat join."""
    target = _abs(path)
    if target.is_symlink() or not target.is_file():
        raise GuardFailure(f"{label} must be a regular non-symlink file: {target}")
    before = target.stat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_JSON_BYTES:
        raise GuardFailure(f"{label} is missing, non-regular, or over {MAX_JSON_BYTES} bytes: {target}")
    data = target.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    after = target.stat()
    if _stat_tuple(before) != _stat_tuple(after):
        raise GuardFailure(f"{label} changed during bounded read: {target}")
    if expected_sha and expected_sha not in {"PARENT_AFTER_RESERVATION", "UNKNOWN"} and digest != expected_sha.lower():
        raise GuardFailure(f"{label} SHA mismatch: {digest} != {expected_sha}")
    return data, {
        "path": str(target),
        "bytes": int(after.st_size),
        "sha256": digest,
        "device": int(after.st_dev),
        "inode": int(after.st_ino),
        "mtime_ns": int(after.st_mtime_ns),
        "ctime_ns": int(after.st_ctime_ns),
        "link_count": int(after.st_nlink),
    }


def _json(path: str | Path, label: str, expected_sha: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    raw, record = _stable_bytes(path, label, expected_sha)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GuardFailure(f"{label} is not bounded UTF-8 JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise GuardFailure(f"{label} must contain a JSON object")
    return value, record


def _finite(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise GuardFailure(f"{label} is not numeric") from exc
    if not math.isfinite(result):
        raise GuardFailure(f"{label} is non-finite")
    return result


def _int(value: Any, label: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise GuardFailure(f"{label} is not an integer") from exc
    return result


def _same_float(left: Any, right: Any, label: str, tolerance: float = 1.0e-12) -> None:
    if abs(_finite(left, label) - _finite(right, label)) > tolerance:
        raise GuardFailure(f"{label} differs: {left!r} != {right!r}")


def _sha_record(path: str | Path, label: str, expected_sha: str | None) -> dict[str, Any]:
    _raw, record = _stable_bytes(path, label, expected_sha)
    return record


def _proof_link(manifest_item: dict[str, Any]) -> dict[str, Any]:
    label = manifest_item.get("label")
    if label not in {"owner", "support", "query1", "query234"}:
        raise GuardFailure(f"invalid ROOT246 evidence label: {label!r}")
    proof, proof_record = _json(manifest_item.get("proof_path", ""), f"{label} actual proof", manifest_item.get("proof_sha256"))
    if proof.get("schema") != "ds02.stage2.root-actual-verification.v1":
        raise GuardFailure(f"{label} proof is not an actual-verification proof")
    if not str(proof.get("status", "")).startswith("VERIFIED_ACTUAL"):
        raise GuardFailure(f"{label} proof status is not verified actual: {proof.get('status')!r}")
    if proof.get("report") != manifest_item.get("report_path") or proof.get("request") != manifest_item.get("request_path") or proof.get("receipt") != manifest_item.get("receipt_path"):
        raise GuardFailure(f"{label} manifest paths do not exactly match the producer proof")
    for proof_key, item_key in (("report_sha256", "report_sha256"), ("request_sha256", "request_sha256"), ("receipt_sha256", "receipt_sha256")):
        if proof.get(proof_key) != manifest_item.get(item_key):
            raise GuardFailure(f"{label} {proof_key} differs from the manifest binding")
    report, report_record = _json(proof["report"], f"{label} compact report", proof["report_sha256"])
    request, request_record = _json(proof["request"], f"{label} producer request", proof["request_sha256"])
    receipt, receipt_record = _json(proof["receipt"], f"{label} execution receipt", proof["receipt_sha256"])
    if receipt.get("schema") != "ds02.execution-receipt.v1" or receipt.get("status") != "completed" or _int(receipt.get("returncode"), f"{label} receipt returncode") != 0:
        raise GuardFailure(f"{label} execution receipt is not completed with returncode 0")
    if receipt.get("request_sha256") and receipt.get("request_sha256") != proof.get("request_sha256"):
        raise GuardFailure(f"{label} receipt request SHA does not match proof")
    if request.get("family_id") not in {None, "F1"} or request.get("sentinel_id") not in {None, "F1-S2"}:
        raise GuardFailure(f"{label} request is not an F1-S2 request")
    if "F1" not in str(proof.get("status")) and "F1" not in str(report.get("status")):
        raise GuardFailure(f"{label} actual proof/report has no F1 identity")
    return {
        "label": label,
        "proof": proof,
        "proof_record": proof_record,
        "report": report,
        "report_record": report_record,
        "request": request,
        "request_record": request_record,
        "receipt": receipt,
        "receipt_record": receipt_record,
    }


def _require_identity(identity: Any, label: str, grid: str | None = None) -> dict[str, Any]:
    if not isinstance(identity, dict):
        raise GuardFailure(f"{label} identity is missing")
    if identity.get("family_id") != "F1" or identity.get("sentinel_id") != "F1-S2" or identity.get("physical_case_id") != PHYSICAL_CASE:
        raise GuardFailure(f"{label} physical identity is not F1-S2: {identity!r}")
    if grid is not None:
        if grid not in GRID_LABELS or not isinstance(identity.get("grid"), dict):
            raise GuardFailure(f"{label} grid identity is malformed")
        _same_float(identity["grid"].get("dp_m"), EXPECTED_DP[grid], f"{label} dp_m")
        _same_float(identity["grid"].get("owner_mass_kg"), 340.0, f"{label} owner mass")
    return identity


def _grid_map(report: dict[str, Any], label: str) -> dict[str, dict[str, Any]]:
    grids = report.get("grids")
    if not isinstance(grids, list) or len(grids) != 3:
        raise GuardFailure(f"{label} must contain exactly three grid records")
    mapped: dict[str, dict[str, Any]] = {}
    for item in grids:
        if not isinstance(item, dict) or item.get("label") not in GRID_LABELS:
            raise GuardFailure(f"{label} contains an invalid grid record")
        grid = str(item["label"])
        if grid in mapped:
            raise GuardFailure(f"{label} contains duplicate {grid} grid")
        mapped[grid] = item
    if set(mapped) != set(GRID_LABELS):
        raise GuardFailure(f"{label} does not contain coarse/medium/fine")
    return mapped


def _float_value(value: Any, label: str) -> float:
    if isinstance(value, dict):
        if "value" in value:
            return _finite(value["value"], label)
        if "v" in value:
            return _finite(value["v"], label)
    return _finite(value, label)


def _vector(value: Any, label: str) -> list[float]:
    if not isinstance(value, list) or len(value) != 3:
        raise GuardFailure(f"{label} must be a three-component vector")
    return [_finite(item, f"{label}[{index}]") for index, item in enumerate(value)]


def _compact_observation(row: dict[str, Any], label: str) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise GuardFailure(f"{label} is not an observation object")
    obs = row.get("observables")
    if not isinstance(obs, dict):
        raise GuardFailure(f"{label} has no observables")
    header = row.get("native_header")
    if not isinstance(header, dict):
        raise GuardFailure(f"{label} has no native header")
    roles = obs.get("role_counts")
    fluid = obs.get("fluid_observable_using_native_MassFluid")
    if not isinstance(roles, dict) or not isinstance(fluid, dict):
        raise GuardFailure(f"{label} lacks typed role counts or fluid native-weighted fields")
    if obs.get("fixed_moving_excluded_from_fluid_observables") is not True:
        raise GuardFailure(f"{label} does not prove fixed/moving exclusion")
    return {
        "frame": _int(row.get("frame"), f"{label} native frame"),
        "time_s": _finite(row.get("time_s"), f"{label} saved time"),
        "runparts_time_s": _finite(row.get("runparts_time_s", row.get("time_s")), f"{label} RunPARTs time"),
        "native_header": {
            "MassFluid_kg": _float_value(header.get("MassFluid"), f"{label} MassFluid"),
            "MassBound_kg": _float_value(header.get("MassBound"), f"{label} MassBound"),
            "Dp_m": _float_value(header.get("Dp"), f"{label} Dp"),
        },
        "role_counts": {
            key: _int(roles.get(key, 0), f"{label} role {key}")
            for key in ("fluid", "fixed", "moving", "floating", "unknown", "total")
        },
        "fluid": {
            "sample_mass_kg": _finite(fluid.get("sample_mass_kg"), f"{label} fluid sample mass"),
            "weighted_centroid_m": _vector(fluid.get("weighted_centroid_m"), f"{label} centroid"),
            "weighted_velocity_m_per_s": _vector(fluid.get("weighted_velocity_m_per_s"), f"{label} velocity"),
            "kinetic_energy_j": _finite(fluid.get("kinetic_energy_j"), f"{label} kinetic energy"),
            "mass_semantics": fluid.get("mass_semantics", "UNKNOWN"),
        },
        "native_field_digest_sha256": row.get("native_field_digest_sha256"),
    }


def _command_flag(command: Any, prefix: str, label: str) -> float:
    if not isinstance(command, list):
        raise GuardFailure(f"{label} command is missing")
    matches = [str(item)[len(prefix):] for item in command if str(item).startswith(prefix)]
    if len(matches) != 1:
        raise GuardFailure(f"{label} requires exactly one {prefix} flag")
    return _finite(matches[0], f"{label} {prefix}")


def _control(grid: dict[str, Any], label: str) -> dict[str, Any]:
    control = grid.get("actual_control")
    window = grid.get("actual_saved_window")
    if not isinstance(control, dict) or not isinstance(window, dict):
        raise GuardFailure(f"{label} lacks actual control or saved window")
    xml_tout = _finite(control.get("generated_xml_TimeOut_s"), f"{label} generated XML TimeOut")
    request_tout = _finite(control.get("request_tout_s"), f"{label} request tout")
    receipt_tout = _command_flag(control.get("receipt_command"), "-tout:", f"{label} receipt")
    command_tmax = _command_flag(control.get("receipt_command"), "-tmax:", f"{label} receipt")
    _same_float(request_tout, receipt_tout, f"{label} request/receipt tout")
    if control.get("override_status") not in {"RUNTIME_RECEIPT_MATCHES_XML", "RUNTIME_RECEIPT_OVERRIDE_CONFIRMED"}:
        raise GuardFailure(f"{label} has unrecognized runtime control status")
    if not isinstance(window.get("queries"), list):
        raise GuardFailure(f"{label} saved window has no query records")
    first = window.get("first")
    last = window.get("last")
    if not isinstance(first, dict) or not isinstance(last, dict):
        raise GuardFailure(f"{label} saved window lacks first/last times")
    first_time = _finite(first.get("time_s"), f"{label} first time")
    last_time = _finite(last.get("time_s"), f"{label} last time")
    if last_time < first_time:
        raise GuardFailure(f"{label} saved time window is reversed")
    return {
        "generated_xml_tout_s": xml_tout,
        "request_tout_s": request_tout,
        "receipt_tout_s": receipt_tout,
        "receipt_tmax_s": command_tmax,
        "override_status": control.get("override_status"),
        "receipt_identity_status": control.get("receipt_identity_status"),
        "row_count": _int(window.get("row_count"), f"{label} saved row count"),
        "first": {"frame": _int(first.get("frame"), f"{label} first frame"), "time_s": first_time},
        "last": {"frame": _int(last.get("frame"), f"{label} last frame"), "time_s": last_time},
    }


def _query_records(grid: dict[str, Any], grid_label: str, expected_queries: tuple[float, ...]) -> dict[str, Any]:
    window = grid.get("actual_saved_window")
    cal = grid.get("calibrated_v1_case_result")
    if not isinstance(window, dict) or not isinstance(cal, dict) or not isinstance(cal.get("selected_observations"), list):
        raise GuardFailure(f"{grid_label} lacks calibrated selected observations")
    by_frame: dict[int, dict[str, Any]] = {}
    for index, row in enumerate(cal["selected_observations"]):
        compact = _compact_observation(row, f"{grid_label} selected row {index}")
        if compact["frame"] in by_frame:
            raise GuardFailure(f"{grid_label} has duplicate selected native frame {compact['frame']}")
        by_frame[compact["frame"]] = compact
    records = window.get("queries")
    if not isinstance(records, list) or len(records) != len(expected_queries):
        raise GuardFailure(f"{grid_label} query record count does not match the registered query set")
    output: list[dict[str, Any]] = []
    for expected in expected_queries:
        matches = [item for item in records if isinstance(item, dict) and abs(_finite(item.get("query_time_s"), f"{grid_label} query") - expected) <= TIME_EPS]
        if len(matches) != 1:
            raise GuardFailure(f"{grid_label} does not contain exactly one query record for {expected}")
        item = matches[0]
        if item.get("interpolation") != "NOT_PERFORMED" or item.get("extrapolation") != "FORBIDDEN" or item.get("selected_row_index_is_not_native_frame_id") is not True:
            raise GuardFailure(f"{grid_label} query {expected} changes interpolation/frame-id semantics")
        lower = item.get("lower")
        upper = item.get("upper")
        if not isinstance(lower, dict) or not isinstance(upper, dict):
            raise GuardFailure(f"{grid_label} query {expected} lacks lower/upper native frames")
        lower_frame = _int(lower.get("frame"), f"{grid_label} lower frame")
        upper_frame = _int(upper.get("frame"), f"{grid_label} upper frame")
        if lower_frame > upper_frame or lower_frame not in by_frame or upper_frame not in by_frame:
            raise GuardFailure(f"{grid_label} query {expected} lower/upper frame is not in selected observations")
        lower_time = _finite(lower.get("time_s"), f"{grid_label} lower time")
        upper_time = _finite(upper.get("time_s"), f"{grid_label} upper time")
        if lower_time > expected + TIME_EPS or upper_time < expected - TIME_EPS:
            raise GuardFailure(f"{grid_label} query {expected} is not bracketed by actual saved times")
        status = "EXACT_NATIVE_FRAME" if lower_frame == upper_frame else "OBSERVED_ENDPOINT_BRACKET_ONLY"
        output.append({
            "query_time_s": expected,
            "status": status,
            "lower": {"frame": lower_frame, "time_s": lower_time, "fields": by_frame[lower_frame]},
            "upper": {"frame": upper_frame, "time_s": upper_time, "fields": by_frame[upper_frame]},
            "bracket_width_s": upper_time - lower_time,
            "interpolation": "NOT_PERFORMED",
            "extrapolation": "FORBIDDEN",
            "selected_row_index_is_not_native_frame_id": True,
        })
    return {"queries": output, "selected_native_frame_count": len(by_frame)}


def _validate_manifest(manifest: dict[str, Any]) -> None:
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("status") != "READY_FOR_PARENT_V8_F1_S2_THREE_GRID_UNIFIED_DIAGNOSTIC_ROOT246":
        raise GuardFailure("ROOT246 manifest schema/status mismatch")
    if manifest.get("family_id") != "F1" or manifest.get("sentinel_id") != "F1-S2" or manifest.get("physical_case_id") != PHYSICAL_CASE:
        raise GuardFailure("ROOT246 manifest physical identity mismatch")
    evidence = manifest.get("evidence")
    if not isinstance(evidence, list) or len(evidence) != 4:
        raise GuardFailure("ROOT246 requires exactly four producer evidence bindings")
    labels = [item.get("label") for item in evidence if isinstance(item, dict)]
    if set(labels) != {"owner", "support", "query1", "query234"}:
        raise GuardFailure("ROOT246 evidence labels are incomplete or duplicated")


def _owner_summary(bundle: dict[str, Any]) -> dict[str, Any]:
    report = bundle["report"]
    if report.get("schema") != "ds02.stage2.f1-s2.continuous-owner-audit.v2" or report.get("status") != "PASS_SOURCE_OWNER_CONTROL_CLOSURE_NATIVE_SUPPORT_PENDING":
        raise GuardFailure("ROOT227 report schema/status mismatch")
    owner = report.get("owner_continuum")
    if not isinstance(owner, dict):
        raise GuardFailure("ROOT227 owner continuum is missing")
    _same_float(owner.get("mass_kg"), 340.0, "ROOT227 owner mass")
    rows = _grid_map({"grids": report.get("three_grid_source_control_closure")}, "ROOT227 source closure")
    output: dict[str, Any] = {"owner_continuum": {key: owner.get(key) for key in ("physical_case_id", "mass_kg", "volume_m3", "density_kg_m3", "fluid_low_m", "fluid_high_m", "gravity_m_s2", "initial_velocity_m_s", "divider_disjoint", "tank_containment")}, "grids": {}}
    for grid in GRID_LABELS:
        row = rows[grid]
        _same_float(row.get("definition_dp_m"), EXPECTED_DP[grid], f"ROOT227 {grid} dp")
        if row.get("discrete_mass_is_not_continuum_truth") is not True:
            raise GuardFailure(f"ROOT227 {grid} discrete mass was not separated from owner mass")
        output["grids"][grid] = {
            "dp_m": _finite(row.get("definition_dp_m"), f"ROOT227 {grid} dp"),
            "fluid_count": _int(row.get("fluid_count"), f"ROOT227 {grid} fluid count"),
            "native_sample_mass_kg": _finite(row.get("native_selected_sample_mass_kg"), f"ROOT227 {grid} native mass"),
            "native_minus_owner_mass_kg": _finite(row.get("native_minus_owner_mass_kg"), f"ROOT227 {grid} mass delta"),
            "generated_xml": row.get("generated_xml"),
        }
    return output


def _support_summary(bundle: dict[str, Any]) -> dict[str, Any]:
    report = bundle["report"]
    if report.get("schema") != "ds02.stage2.f1-s2.initial-support-observer.v2" or report.get("status") != "COMPLETE_F1_S2_INITIAL_NATIVE_SUPPORT_DIAGNOSTICS_NO_SCIENTIFIC_Q":
        raise GuardFailure("ROOT233 report schema/status mismatch")
    owner = report.get("owner_continuum")
    if not isinstance(owner, dict):
        raise GuardFailure("ROOT233 owner continuum is missing")
    _same_float(owner.get("mass_kg"), 340.0, "ROOT233 owner mass")
    grids = _grid_map(report, "ROOT233 support report")
    output: dict[str, Any] = {"grids": {}}
    for label in GRID_LABELS:
        item = grids[label]
        _require_identity(item.get("identity"), f"ROOT233 {label}", label)
        support = item.get("support")
        roles = item.get("typed_role_counts")
        header = item.get("native_header")
        mass = item.get("mass_separation")
        if not isinstance(support, dict):
            raise GuardFailure(f"ROOT233 {label} support record is missing")
        owner_box = support.get("owner_box")
        if not isinstance(owner_box, dict) or owner_box.get("within_registered_support") is not True or _int(owner_box.get("outside_count"), f"ROOT233 {label} outside count") != 0:
            raise GuardFailure(f"ROOT233 {label} is outside the owner support")
        divider = support.get("divider_disjoint")
        if not isinstance(divider, dict) or divider.get("no_fluid_overlap") is not True or _int(divider.get("overlap_count"), f"ROOT233 {label} divider overlap") != 0:
            raise GuardFailure(f"ROOT233 {label} divider support is not disjoint")
        if item.get("native_observables", {}).get("fixed_moving_excluded_from_fluid_observables") is not True:
            raise GuardFailure(f"ROOT233 {label} does not exclude fixed/moving from fluid aggregates")
        if not isinstance(roles, dict) or not isinstance(header, dict) or not isinstance(mass, dict):
            raise GuardFailure(f"ROOT233 {label} lacks native support fields")
        _same_float(header.get("Dp", {}).get("value"), EXPECTED_DP[label], f"ROOT233 {label} Dp")
        output["grids"][label] = {
            "dp_m": _finite(header["Dp"]["value"], f"ROOT233 {label} Dp"),
            "mass_fluid_kg": _finite(header["MassFluid"]["value"], f"ROOT233 {label} MassFluid"),
            "fluid_count": _int(roles.get("fluid"), f"ROOT233 {label} fluid count"),
            "fixed_count": _int(roles.get("fixed"), f"ROOT233 {label} fixed count"),
            "total_count": _int(roles.get("total"), f"ROOT233 {label} total count"),
            "outside_count": _int(owner_box.get("outside_count"), f"ROOT233 {label} outside count"),
            "divider_overlap_count": _int(divider.get("overlap_count"), f"ROOT233 {label} overlap count"),
            "finite": support.get("fluid_position_finite") is True,
            "within_registered_support": True,
            "native_sample_mass_kg": _finite(mass.get("native_sample_mass_kg"), f"ROOT233 {label} sample mass"),
            "position_tolerance_is_not_task_error": True,
        }
    return output


def _query_summary(bundle: dict[str, Any], expected_schema: str, expected_status: str, expected_queries: tuple[float, ...], name: str) -> dict[str, Any]:
    report = bundle["report"]
    if report.get("schema") != expected_schema or report.get("status") != expected_status:
        raise GuardFailure(f"{name} report schema/status mismatch")
    query = report.get("query")
    if not isinstance(query, dict) or query.get("interpolation") != "FORBIDDEN" or query.get("extrapolation") != "FORBIDDEN":
        raise GuardFailure(f"{name} query policy is not interpolation/extrapolation forbidden")
    actual_queries = tuple(_finite(item, f"{name} query") for item in query.get("query_times_s", []))
    if actual_queries != expected_queries:
        raise GuardFailure(f"{name} query times differ from frozen set: {actual_queries!r}")
    grids = _grid_map(report, name)
    output: dict[str, Any] = {"query_times_s": list(expected_queries), "grids": {}}
    for label in GRID_LABELS:
        item = grids[label]
        _require_identity(item.get("identity"), f"{name} {label}", label)
        control = _control(item, f"{name} {label}")
        actual = _query_records(item, label, expected_queries)
        output["grids"][label] = {
            "identity": item["identity"],
            "control": control,
            "actual_saved_window": {"row_count": control["row_count"], "first": control["first"], "last": control["last"]},
            "queries": actual["queries"],
            "selected_native_frame_count": actual["selected_native_frame_count"],
            "native_payload_read_count": _int(item.get("native_payload_read_count"), f"{name} {label} payload count"),
            "axis_authority": item.get("axis_authority"),
        }
    return output


def _compare_controls(q1: dict[str, Any], q234: dict[str, Any]) -> dict[str, Any]:
    by_grid: dict[str, Any] = {}
    for label in GRID_LABELS:
        left = q1["grids"][label]["control"]
        right = q234["grids"][label]["control"]
        for key in ("generated_xml_tout_s", "request_tout_s", "receipt_tout_s", "receipt_tmax_s", "override_status", "row_count"):
            if left[key] != right[key]:
                raise GuardFailure(f"query1/query234 control mismatch for {label}: {key}")
        by_grid[label] = left
    xml_tout = {label: by_grid[label]["generated_xml_tout_s"] for label in GRID_LABELS}
    receipt_tout = {label: by_grid[label]["receipt_tout_s"] for label in GRID_LABELS}
    request_tout = {label: by_grid[label]["request_tout_s"] for label in GRID_LABELS}
    xml_uniform = len(set(xml_tout.values())) == 1
    receipt_uniform = len(set(receipt_tout.values())) == 1
    return {
        "by_grid": by_grid,
        "generated_xml_tout_s": xml_tout,
        "request_tout_s": request_tout,
        "receipt_tout_s": receipt_tout,
        "generated_xml_tout_uniform": xml_uniform,
        "actual_request_tout_uniform": len(set(request_tout.values())) == 1,
        "actual_receipt_tout_uniform": receipt_uniform,
        "diagnostic_status": "CONTROL_VARIATION_OBSERVED" if not receipt_uniform else "CONTROL_RECEIPT_UNIFORM",
        "scientific_interpretation": "XML TimeOut is provenance only; receipt command is authoritative",
    }


def _common_queries(q1: dict[str, Any], q234: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for label in GRID_LABELS:
        entries = q1["grids"][label]["queries"] + q234["grids"][label]["queries"]
        result[label] = {str(item["query_time_s"]): item for item in entries}
    all_common = True
    for query in (1.0, 2.0, 3.0, 4.0):
        statuses = [result[label][str(query)]["status"] for label in GRID_LABELS]
        # Even if all are brackets, their actual endpoints/times need to be
        # equal for a field difference to have an exact common-time meaning.
        pairs = [(result[label][str(query)]["lower"]["time_s"], result[label][str(query)]["upper"]["time_s"]) for label in GRID_LABELS]
        if len(set(pairs)) != 1:
            all_common = False
        for status in statuses:
            if status != "EXACT_NATIVE_FRAME":
                all_common = False
    return {
        "requested_times_s": [1.0, 2.0, 3.0, 4.0],
        "by_grid": result,
        "common_exact_native_time_status": "NO_COMMON_EXACT_NATIVE_TIMES" if not all_common else "COMMON_EXACT_NATIVE_TIMES",
        "field_comparison_status": "UNKNOWN_ASYNCHRONOUS_SAVED_TIME_ALIGNMENT",
        "interpolation": "NOT_PERFORMED",
        "spatial_difference_is_truth": False,
    }


def _write_once(path: str | Path, value: dict[str, Any]) -> None:
    target = _abs(path)
    if target.exists() or target.is_symlink():
        raise GuardFailure(f"refusing to overwrite output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def run(args: argparse.Namespace) -> dict[str, Any]:
    manifest, manifest_record = _json(args.manifest, "ROOT246 manifest")
    _validate_manifest(manifest)
    bundles = {item["label"]: _proof_link(item) for item in manifest["evidence"]}
    owner = _owner_summary(bundles["owner"])
    support = _support_summary(bundles["support"])
    q1 = _query_summary(bundles["query1"], "ds02.stage2.f1-s2.query1-endpoint-observer.v4", "COMPLETE_QUERY1_NATIVE_COMPONENT_DIAGNOSTICS_NO_SCIENTIFIC_Q", EXPECTED_QUERIES["query1"], "ROOT234")
    q234 = _query_summary(bundles["query234"], "ds02.stage2.f1-s2.query-endpoint-observer.v2", "COMPLETE_QUERY234_NATIVE_COMPONENT_DIAGNOSTICS_NO_SCIENTIFIC_Q", EXPECTED_QUERIES["query234"], "ROOT231")
    for label in GRID_LABELS:
        _same_float(owner["grids"][label]["dp_m"], support["grids"][label]["dp_m"], f"{label} owner/support dp")
        if owner["grids"][label]["fluid_count"] != support["grids"][label]["fluid_count"]:
            raise GuardFailure(f"{label} owner/support fluid count mismatch")
        _require_identity(q1["grids"][label]["identity"], f"ROOT234 {label}", label)
        _require_identity(q234["grids"][label]["identity"], f"ROOT231 {label}", label)
    controls = _compare_controls(q1, q234)
    result = {
        "schema": SCHEMA,
        "status": PASS_STATUS,
        "manifest": manifest_record,
        "producer_evidence": {
            label: {
                "proof": bundle["proof_record"],
                "report": bundle["report_record"],
                "request": bundle["request_record"],
                "receipt": bundle["receipt_record"],
                "actual_status": bundle["proof"].get("status"),
                "report_schema": bundle["report"].get("schema"),
            }
            for label, bundle in bundles.items()
        },
        "owner_continuum": owner,
        "initial_support": support,
        "query1": q1,
        "query234": q234,
        "controls": controls,
        "common_observation": _common_queries(q1, q234),
        "step_cfl_status": {
            "status": "UNKNOWN_CFL_NOT_EXPLICIT_IN_BOUND_SMALL_REPORTS",
            "same_cfl_label_is_not_receipt_evidence": True,
            "dt_or_coefdtmin_parameter": "UNKNOWN_UNBOUND",
            "no_step_error_claim": True,
        },
        "recipe_control_status": {
            "source_identity": "BOUND_PER_GRID_REPORT_IDENTITY_AND_RECEIPT",
            "all_grid_recipe_byte_identity": "UNKNOWN",
            "reason": "The compact reports bind each actual XML/receipt identity, but do not prove a byte-identical three-grid recipe or an explicit CFL/dt key.",
        },
        "next_source_ready_tasks": {
            "output_cadence_isolation": {
                "task_id": "F1-S2-OUTPUT-CADENCE-ISOLATION-V1",
                "status": "READY_FOR_SEPARATE_PARENT_REQUEST",
                "only_change": "receipt-proven -tout value",
                "fixed": ["per-grid owner/source/BI4", "CFL/dt parameter", "tmax", "forcing", "query times 1,2,3,4 s"],
                "common_tout_s": 0.005,
                "required_checks": ["actual receipt command", "RunPARTs saved times", "native lower/upper frames", "pre/post source hash/stat"],
                "interpolation": "FORBIDDEN",
                "qualification": "UNKNOWN until actual guarded pair/run evidence",
            },
            "time_step_isolation": {
                "task_id": "F1-S2-TIME-STEP-ISOLATION-V1",
                "status": "BLOCKED_ON_EXPLICIT_SOURCE_CFL_DT_BINDING",
                "only_change": "one source-registered CFL/dt/CoefDtMin setting",
                "fixed": ["one selected grid/source/BI4", "common actual -tout:0.005", "tmax", "forcing", "query times 1,2,3,4 s"],
                "required_before_launch": ["source XML/overlay parameter key", "actual receipt command proving the key", "same physical producer identity", "parent resource reservation"],
                "qualification": "UNKNOWN until actual guarded pair/run evidence",
            },
            "neighbor_grid_truth": False,
            "tolerance_widening": False,
        },
        "read_scope": {
            "small_json_only": True,
            "production_native_payload_read": False,
            "production_h5_read": False,
            "production_vtk_read": False,
            "solver_launch": False,
            "interpolation": False,
            "qualification_credit": 0,
        },
        "scientific_qualification": QUALIFICATION,
        "qualification_limits": [
            "native sample mass is a discrete diagnostic and is not the 340 kg owner truth",
            "position support containment and native field finiteness are diagnostic checks, not QN task tolerances",
            "actual receipt tout is nonuniform (.005 coarse/fine, .01 medium), so output cadence is not a common control",
            "CFL/dt is not explicitly bound by these four small reports; same_cfl labels are not used as proof",
            "requested 1/2/3/4 second brackets have asynchronous native saved times; no field difference is promoted to an error bound",
            "producer-to-world orientation, integration, event-time, spatial truth, and external validation remain UNKNOWN",
        ],
    }
    _write_once(args.output, result)
    return result


def self_test() -> None:
    """Exercise strict local contracts without touching production paths."""
    with tempfile.TemporaryDirectory(prefix="f1-s2-root246-") as name:
        tmp = Path(name)
        commands = [
            ["solver", "-tmax:4", "-tout:0.005"],
            ["solver", "-tmax:4", "-tout:0.01"],
        ]
        assert _command_flag(commands[0], "-tout:", "fixture") == 0.005
        try:
            _command_flag(["solver", "-tmax:4"], "-tout:", "negative")
        except GuardFailure:
            pass
        else:
            raise AssertionError("missing tout was accepted")
        row = {
            "frame": 0,
            "time_s": 0.0,
            "native_header": {"MassFluid": {"value": 1.0}, "MassBound": {"value": 1.0}, "Dp": {"value": 0.1}},
            "observables": {
                "role_counts": {"fluid": 1, "fixed": 1, "moving": 0, "floating": 0, "unknown": 0, "total": 2},
                "fixed_moving_excluded_from_fluid_observables": True,
                "fluid_observable_using_native_MassFluid": {"sample_mass_kg": 1.0, "weighted_centroid_m": [1.0, 2.0, 3.0], "weighted_velocity_m_per_s": [0.1, 0.2, 0.3], "kinetic_energy_j": 0.5},
            },
        }
        compact = _compact_observation(row, "fixture row")
        assert compact["native_header"]["Dp_m"] == 0.1
        bad = json.loads(json.dumps(row))
        bad["observables"]["fixed_moving_excluded_from_fluid_observables"] = False
        try:
            _compact_observation(bad, "negative row")
        except GuardFailure:
            pass
        else:
            raise AssertionError("fixed/moving contamination was accepted")
        manifest = {"schema": MANIFEST_SCHEMA, "status": "READY_FOR_PARENT_V8_F1_S2_THREE_GRID_UNIFIED_DIAGNOSTIC_ROOT246", "family_id": "F1", "sentinel_id": "F1-S2", "physical_case_id": PHYSICAL_CASE, "evidence": [{"label": label} for label in ("owner", "support", "query1", "query234")]}
        _validate_manifest(manifest)
        bad_manifest = json.loads(json.dumps(manifest)); bad_manifest["evidence"][-1]["label"] = "query1"
        try:
            _validate_manifest(bad_manifest)
        except GuardFailure:
            pass
        else:
            raise AssertionError("duplicate evidence label was accepted")
    print("PASS_F1_S2_ROOT246_UNIFIED_DIAGNOSTIC_SELFTEST")


def _failure(output: Path, reason: str) -> None:
    if output.exists() or output.is_symlink():
        return
    try:
        _write_once(output, {"schema": SCHEMA, "status": FAIL_STATUS, "reason": reason, "scientific_qualification": QUALIFICATION, "read_scope": {"small_json_only": "UNKNOWN_OR_PARTIAL", "solver_launch": False}})
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--run", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.self_test:
        self_test()
        return 0
    if args.manifest is None or args.output is None:
        parser.error("--manifest and --output are required with --run")
    try:
        result = run(args)
    except Exception as exc:
        _failure(args.output, str(exc))
        print(f"FAIL_ROOT246_F1_S2_UNIFIED_DIAGNOSTIC: {exc}")
        return 2
    print(json.dumps({"schema": SCHEMA, "status": result["status"], "output": str(_abs(args.output))}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
