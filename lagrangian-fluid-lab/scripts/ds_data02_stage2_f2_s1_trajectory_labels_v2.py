#!/usr/bin/env python3
"""Recover a source-bound F2-S1 label sidecar from the completed v1 output.

The v1 attempt produced a complete 4 MB label H5 but failed while summarizing
it because an HDF5 boolean was compared by Python object identity.  This
forward-only worker preserves that receipt and H5, validates the original
source contract and the failed attempt's stable small-input hashes, then
reads the already-produced label H5 once to write a new immutable report.  It
does not reopen or hash the 1.19 GB source trajectory H5.  The ``run`` path
is retained for source-bound replay compatibility; the recovery request uses
``recover`` exclusively.

The labels are saved-frame observations.  A finite receiver/tray box is a
diagnostic region and a finite aperture crossing is a bracket [t_i,t_{i+1}]
with a linear-chord estimate.  Missing identities use the open-lifecycle
right-censoring label; they are never called legal spill or physical fate.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import tempfile
import xml.etree.ElementTree as ET
from typing import Any


SCRIPT = Path(__file__).resolve()
CURRENT_SHA256 = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
EXPECTED_H5_SHA256 = "f882a38dca872cbe81523b0691ea10ff6cc122037917b5d0a3004337eb6a8e9d"
EXPECTED_H5_BYTES = 1_191_110_523
EXPECTED_FRAMES = 401
EXPECTED_PARTICLES = 418_104
EXPECTED_END_TIME = 4.000007783879406
EXPECTED_TRAJECTORY_COORDINATE_FRAME = "DualSPHysics case Cartesian coordinates (x,y,z)"
SCHEMA = "ds02.stage2.f2-s1-trajectory-labels-recovery.v2"
LEGACY_LABEL_SCHEMA = "ds02.stage2.f2-s1-trajectory-labels.v1"
CONTRACT_SCHEMA = "ds02.stage2.f2-s1-trajectory-source-contract.v1"
RECOVERY_REQUEST_SCHEMA = "ds02.stage2.f2-s1-trajectory-labels-recovery-request.v2"


class TrajectoryLabelError(RuntimeError):
    """Raised when a source-bound trajectory-label contract is not exact."""


def sha256(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path | str, label: str) -> dict[str, Any]:
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise TrajectoryLabelError(f"{label} is missing: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TrajectoryLabelError(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise TrajectoryLabelError(f"{label} is not a JSON object: {path}")
    return value


def binding(path: Path | str, label: str, expected: str | None = None,
            *, allow_large: bool = False) -> dict[str, Any]:
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise TrajectoryLabelError(f"{label} is missing: {path}")
    if not allow_large and path.stat().st_size > 64 * 1024 * 1024:
        raise TrajectoryLabelError(f"{label} is unexpectedly large for metadata preparation: {path}")
    actual = sha256(path)
    if expected is not None and actual != expected:
        raise TrajectoryLabelError(f"{label} SHA256 differs: {path}")
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": actual}


def deferred_h5_binding(path: Path | str, expected: str, expected_bytes: int) -> dict[str, Any]:
    """Bind a trajectory by producer SHA and stat without reading its bytes."""
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise TrajectoryLabelError(f"trajectory H5 is missing: {path}")
    size = path.stat().st_size
    if size != expected_bytes:
        raise TrajectoryLabelError(f"trajectory H5 byte count differs: {path}")
    return {
        "path": str(path),
        "bytes": size,
        "sha256": expected,
        "digest_source": "completed conversion receipt; prepare did not open H5",
        "content_read_deferred_until_guarded_run": True,
    }


def _float(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise TrajectoryLabelError(f"{label} is not numeric") from exc
    if not math.isfinite(number):
        raise TrajectoryLabelError(f"{label} is not finite")
    return number


def _same_float(actual: Any, expected: float, label: str, tol: float = 1e-12) -> None:
    if abs(_float(actual, label) - expected) > tol:
        raise TrajectoryLabelError(f"{label} differs: {actual!r} != {expected!r}")


def _path_from(item: Any, label: str) -> Path:
    if not isinstance(item, dict) or not item.get("path"):
        raise TrajectoryLabelError(f"{label} lacks a path binding")
    return Path(item["path"]).expanduser().resolve()


def _declared_binding(item: Any, label: str) -> dict[str, Any]:
    """Hash a small declared input and require its contract metadata to agree."""
    path = _path_from(item, label)
    actual = binding(path, label)
    if item.get("bytes") is not None and int(item["bytes"]) != actual["bytes"]:
        raise TrajectoryLabelError(f"{label} byte count differs from contract")
    if item.get("sha256") and item["sha256"] != actual["sha256"]:
        raise TrajectoryLabelError(f"{label} SHA256 differs from contract")
    return actual


def _producer_receipt(path: Path, label: str) -> dict[str, Any]:
    receipt = read_json(path, label)
    if receipt.get("status") != "completed" or int(receipt.get("returncode", -1)) != 0:
        raise TrajectoryLabelError(f"{label} is not completed code 0")
    launch = receipt.get("input_hashes_at_launch")
    after = receipt.get("input_hashes_after_run")
    if not isinstance(launch, dict) or launch != after:
        raise TrajectoryLabelError(f"{label} input hashes are not stable")
    return receipt


def _read_text(path: Path, label: str) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="strict")
    except OSError as exc:
        raise TrajectoryLabelError(f"cannot read {label}: {path}") from exc


def _parse_xml_geometry(xml_path: Path) -> dict[str, Any]:
    try:
        root = ET.fromstring(_read_text(xml_path, "generated XML"))
    except ET.ParseError as exc:
        raise TrajectoryLabelError("generated XML is not parseable") from exc
    bounds: dict[str, list[list[float]]] = {}
    current_mk: str | None = None
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag == "setmkbound":
            current_mk = element.attrib.get("mk")
        elif tag == "drawbox" and current_mk in {"1", "2"}:
            fill = next((child.text or "" for child in element if child.tag.rsplit("}", 1)[-1] == "boxfill"), "")
            if "bottom" not in fill:
                # The XML reuses the last setmkbound while defining the
                # fluid boxes; only the bound drawbox is a region source.
                continue
            point = next((child for child in element if child.tag.rsplit("}", 1)[-1] == "point"), None)
            size = next((child for child in element if child.tag.rsplit("}", 1)[-1] == "size"), None)
            if point is not None and size is not None:
                p = [_float(point.attrib.get(axis), f"mk{current_mk} point {axis}") for axis in "xyz"]
                s = [_float(size.attrib.get(axis), f"mk{current_mk} size {axis}") for axis in "xyz"]
                bounds[current_mk] = [[p[i], p[i] + s[i]] for i in range(3)]
    if bounds.get("1") != [[0.56, 1.6600000000000001], [-0.16, 0.43999999999999995], [0.0, 0.45]]:
        # Compare numerically to avoid depending on XML decimal rendering.
        expected = [[0.56, 1.66], [-0.16, 0.44], [0.0, 0.45]]
        if bounds.get("1") is None or any(abs(bounds["1"][i][j] - expected[i][j]) > 1e-10 for i in range(3) for j in range(2)):
            raise TrajectoryLabelError("generated XML mkbound=1 geometry differs")
    expected_tray = [[-1.2, 2.8], [-1.0, 1.0], [-0.2, -0.05]]
    if bounds.get("2") is None or any(abs(bounds["2"][i][j] - expected_tray[i][j]) > 1e-10 for i in range(3) for j in range(2)):
        raise TrajectoryLabelError("generated XML mkbound=2 geometry differs")
    domain = root.find(".//simulationdomain")
    if domain is None:
        raise TrajectoryLabelError("generated XML simulationdomain is missing")
    posmin = domain.find("posmin")
    posmax = domain.find("posmax")
    if posmin is None or posmax is None:
        raise TrajectoryLabelError("generated XML simulationdomain bounds are missing")
    domain_bounds = [[_float(posmin.attrib.get(axis), f"domain min {axis}"),
                      _float(posmax.attrib.get(axis), f"domain max {axis}")] for axis in "xyz"]
    expected_domain = [[-1.4, 3.0], [-1.2, 1.2], [-0.5, 2.2]]
    if any(abs(domain_bounds[i][j] - expected_domain[i][j]) > 1e-10 for i in range(3) for j in range(2)):
        raise TrajectoryLabelError("generated XML simulationdomain differs")
    return {"receiver_mkbound_1": bounds["1"], "tray_mkbound_2": bounds["2"], "simulationdomain": domain_bounds}


def _runparts_last(runparts: Path) -> dict[str, Any]:
    lines = [line.strip() for line in _read_text(runparts, "RunPARTs.csv").splitlines() if line.strip() and not line.lstrip().startswith("#")]
    if not lines:
        raise TrajectoryLabelError("RunPARTs.csv has no rows")
    header = [part.strip() for part in lines[0].split(";")]
    rows = []
    for line in lines[1:]:
        values = [part.strip() for part in line.split(";")]
        if len(values) != len(header):
            continue
        rows.append(dict(zip(header, values)))
    if not rows:
        raise TrajectoryLabelError("RunPARTs.csv has no data row")
    row = rows[-1]
    time_key = next((key for key in row if key.lower().startswith("time")), None)
    out_key = next((key for key in row if key.lower().startswith("npout") and "pos" not in key.lower() and "rho" not in key.lower() and "mov" not in key.lower()), None)
    if time_key is None or out_key is None:
        raise TrajectoryLabelError("RunPARTs.csv lacks time/NpOut columns")
    return {"last_time_s": _float(row[time_key], "RunPARTs final time"), "last_npout": int(float(row[out_key])), "raw_header": header}


def _validate_runout(runout: Path, runparts: Path) -> dict[str, Any]:
    text = _read_text(runout, "Run.out")
    for required in ("MapRealPos(final)", "RhopOut=True", "TimeMax=4"):
        if required not in text:
            raise TrajectoryLabelError(f"Run.out lacks required native line: {required}")
    match = re.search(r"MapRealPos\(final\)=\(([^)]+)\)-\(([^)]+)\)", text)
    if not match:
        raise TrajectoryLabelError("Run.out final native domain line is missing")
    final_bounds = [[float(item.strip()) for item in side.split(",")] for side in match.groups()]
    if len(final_bounds) != 2 or any(len(side) != 3 for side in final_bounds):
        raise TrajectoryLabelError("Run.out final native domain line is malformed")
    part = _runparts_last(runparts)
    if abs(part["last_time_s"] - EXPECTED_END_TIME) > 1e-8:
        raise TrajectoryLabelError("RunPARTs final time differs from exact CURRENT window")
    return {"final_native_bounds": final_bounds, "runparts_last": part, "time_semantics": "saved RunPARTs row"}


def validate_contract(contract_path: Path | str, *, read_h5: bool = False) -> dict[str, Any]:
    """Validate metadata and optionally the deferred H5 binding.

    ``read_h5=False`` is used by request preparation.  It performs a stat
    only on the H5 and never calls :func:`sha256` for that path.
    """
    contract_path = Path(contract_path).expanduser().resolve()
    contract = read_json(contract_path, "trajectory source contract")
    if contract.get("schema") != CONTRACT_SCHEMA or contract.get("case_key") != "F2/scan-F2-S1-001":
        raise TrajectoryLabelError("trajectory source contract identity differs")
    current_item = contract.get("current")
    current = _path_from(current_item, "CURRENT336")
    current_binding = binding(current, "CURRENT336", CURRENT_SHA256)
    if current_binding != {k: current_item[k] for k in ("path", "bytes", "sha256") if k in current_item}:
        raise TrajectoryLabelError("CURRENT336 contract binding differs")
    h5_item = contract.get("trajectory_hdf5")
    h5 = _path_from(h5_item, "trajectory H5")
    if h5.stat().st_size != EXPECTED_H5_BYTES or h5_item.get("bytes") != EXPECTED_H5_BYTES or h5_item.get("sha256") != EXPECTED_H5_SHA256:
        raise TrajectoryLabelError("trajectory H5 deferred binding differs")
    if read_h5 and sha256(h5) != EXPECTED_H5_SHA256:
        raise TrajectoryLabelError("trajectory H5 SHA256 differs at guarded run")
    conversion = _path_from(contract.get("conversion_report"), "conversion report")
    conversion_binding = _declared_binding(contract.get("conversion_report"), "conversion report")
    conversion_payload = read_json(conversion, "conversion report")
    if conversion_payload.get("conversion_status") != "completed" or conversion_payload.get("output_hdf5") != str(h5):
        raise TrajectoryLabelError("conversion does not bind exact trajectory H5")
    if conversion_payload.get("output_sha256") != EXPECTED_H5_SHA256:
        raise TrajectoryLabelError("conversion output SHA differs")
    if conversion_payload.get("coordinate_frame") != EXPECTED_TRAJECTORY_COORDINATE_FRAME:
        raise TrajectoryLabelError("conversion coordinate frame differs")
    frames_value = conversion_payload.get("frames")
    if isinstance(frames_value, dict):
        frames_value = frames_value.get("count")
    if frames_value not in (EXPECTED_FRAMES, None):
        raise TrajectoryLabelError("conversion frame count differs")
    particles_value = conversion_payload.get("particles")
    if isinstance(particles_value, dict):
        particles_value = particles_value.get("count")
    if particles_value not in (EXPECTED_PARTICLES, None):
        raise TrajectoryLabelError("conversion particle count differs")
    closure_path = _path_from(contract.get("source_closure"), "F2-S1 source closure")
    closure = read_json(closure_path, "F2-S1 source closure")
    if closure.get("schema") != "ds02.stage2.f2-s1-native-source-closure.v1" or closure.get("current", {}).get("sha256") != CURRENT_SHA256:
        raise TrajectoryLabelError("source closure does not bind CURRENT336")
    if closure.get("native_result", {}).get("status") != "EXACT_SEMANTIC_MATCH":
        raise TrajectoryLabelError("source closure native result is not exact")
    xml = _path_from(contract.get("generated_xml"), "generated XML")
    xml_binding = _declared_binding(contract.get("generated_xml"), "generated XML")
    geometry = _parse_xml_geometry(xml)
    runout = _path_from(contract.get("runout"), "Run.out")
    runparts = _path_from(contract.get("runparts"), "RunPARTs.csv")
    runout_binding = _declared_binding(contract.get("runout"), "Run.out")
    runparts_binding = _declared_binding(contract.get("runparts"), "RunPARTs.csv")
    native_run = _validate_runout(runout, runparts)
    receipt = _path_from(contract.get("solver_receipt"), "solver receipt")
    _producer_receipt(receipt, "solver receipt")
    config_path = _path_from(contract.get("label_config"), "label config")
    config = read_json(config_path, "label config")
    if config.get("schema") != "ds02.stage2.f2-s1-trajectory-label-config.v1":
        raise TrajectoryLabelError("label config schema differs")
    if config.get("coordinate_frame") != EXPECTED_TRAJECTORY_COORDINATE_FRAME or config.get("frame_kind") != "fixed_solver_frame":
        raise TrajectoryLabelError("trajectory labels require fixed solver frame")
    if config.get("lifecycle_model") != "open":
        raise TrajectoryLabelError("F2-S1 trajectory labels require open lifecycle")
    if config.get("time_window_s") != [0.0, EXPECTED_END_TIME] or config.get("expected_frames") != EXPECTED_FRAMES:
        raise TrajectoryLabelError("label config time identity differs")
    if config.get("trajectory_hdf5_sha256") != EXPECTED_H5_SHA256:
        raise TrajectoryLabelError("label config H5 SHA differs")
    return {
        "contract": contract,
        "current": current_binding,
        "trajectory_hdf5": h5_item,
        "conversion_report": conversion_binding,
        "source_closure": _declared_binding(contract.get("source_closure"), "F2-S1 source closure"),
        "generated_xml": xml_binding,
        "geometry": geometry,
        "runout": runout_binding,
        "runparts": runparts_binding,
        "native_run": native_run,
        "solver_receipt": _declared_binding(contract.get("solver_receipt"), "solver receipt"),
        "label_config": _declared_binding(contract.get("label_config"), "label config"),
        "config": config,
        "h5_content_verified": read_h5,
    }


def _load_operator():
    path = SCRIPT.with_name("ds_data02_stage2_f2_s1_trajectory_labels_operator_v1.py")
    spec = importlib.util.spec_from_file_location("ds02_f2_s1_trajectory_operator_v1", path)
    if spec is None or spec.loader is None:
        raise TrajectoryLabelError("cannot load trajectory operator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sum_by_source(source: Any, masses: Any, values: Any, nsource: int) -> list[float]:
    return [float(values[(source == code)].sum()) for code in range(1, nsource + 1)]


def _strict_true(value: Any, np: Any) -> bool:
    """Accept Python/numpy booleans only; reject strings and integer flags."""
    return type(value) is bool or isinstance(value, np.bool_)


def _validate_existing_label_attrs(handle: Any, contract_info: dict[str, Any], np: Any) -> None:
    if handle.attrs.get("schema") != "ds-data-02.native-labels.v1":
        raise TrajectoryLabelError("operator output schema is not ds-data-02.native-labels.v1")
    if not _strict_true(handle.attrs.get("complete"), np) or not bool(handle.attrs.get("complete")):
        raise TrajectoryLabelError("operator output complete attribute is not a strict true boolean")
    if handle.attrs.get("source_hdf5_sha256") != EXPECTED_H5_SHA256:
        raise TrajectoryLabelError("operator output source trajectory digest differs")
    declared_source = str(handle.attrs.get("source_hdf5", ""))
    expected_source = str(contract_info["trajectory_hdf5"]["path"])
    if declared_source != expected_source:
        raise TrajectoryLabelError("operator output source trajectory path differs")


def summarize(output: Path, contract_info: dict[str, Any]) -> dict[str, Any]:
    import h5py
    import numpy as np

    with h5py.File(output, "r") as h:
        _validate_existing_label_attrs(h, contract_info, np)
        time = h["time"][:]
        source = h["source_label"][:]
        masses = h["initial_fluid_mass_kg"][:]
        if len(time) != EXPECTED_FRAMES or len(source) != EXPECTED_PARTICLES:
            raise TrajectoryLabelError("operator output frame or identity count differs")
        if abs(float(time[0])) > 1e-12 or abs(float(time[-1]) - EXPECTED_END_TIME) > 1e-8:
            raise TrajectoryLabelError("operator output saved time window differs")
        nsource = len(contract_info["config"]["source_regions"])
        total = float(h.attrs["initial_fluid_mass_kg"])
        final = h["final_category"][:]
        category_mass = {str(code): float(masses[final == code].sum()) for code in range(-2, len(contract_info["config"]["destination_regions"]) + 1)}
        source_mass = {str(code): float(masses[source == code].sum()) for code in range(1, nsource + 1)}
        missing_mass = float(masses[final == -1].sum())
        invalid_mass = float(masses[final == -2].sum())
        unknown_destination_mass = float(masses[final == 0].sum())
        residence = h["residence_time_s"][:]
        unresolved = h["unresolved_interval_time_s"][:]
        missing_gap = h["missing_identity_gap_bracket"][:]
        missing_censor = h["missing_identity_censor"][:].astype(bool)
        crossings = h["event_crossing_counts"][:]
        first = h["first_passage_interval"][:]
        censor = h["first_passage_censor"][:]
        flux = h["forward_backward_mass_kg"][-1]
        net = h["cumulative_net_flux_kg"][-1]
        events = []
        for index, event in enumerate(contract_info["config"].get("events", [])):
            entry_direction = event.get("forward_direction", "+axis")
            if entry_direction not in {"+x", "-x", "+y", "-y", "+z", "-z"}:
                raise TrajectoryLabelError(f"event direction is not explicit: {entry_direction!r}")
            entry_column = 0 if entry_direction[0] == "+" else 1
            exit_column = 1 - entry_column
            observed = censor[:, index] == 0
            events.append({
                "id": event["id"],
                "axis": "xyz"[event["axis"]],
                "entry_direction": entry_direction,
                "operator_column_semantics": "column0=negative-to-positive along selected axis; column1=positive-to-negative",
                "observed_first_passage_mass_kg": float(masses[observed].sum()),
                "censored_first_passage_mass_kg": float(masses[~observed].sum()),
                "first_passage_time_min_s": float(np.nanmin(first[observed, index, 0])) if np.any(observed) else None,
                "first_passage_time_max_s": float(np.nanmax(first[observed, index, 1])) if np.any(observed) else None,
                "positive_axis_mass_kg": float(flux[index, 0]),
                "negative_axis_mass_kg": float(flux[index, 1]),
                "positive_axis_net_flux_mass_kg": float(net[index]),
                "entry_direction_mass_kg": float(flux[index, entry_column]),
                "exit_direction_mass_kg": float(flux[index, exit_column]),
                "entry_direction_net_flux_mass_kg": float(flux[index, entry_column] - flux[index, exit_column]),
                "forward_crossing_count": int(crossings[:, index, 0].sum()),
                "backward_crossing_count": int(crossings[:, index, 1].sum()),
                "entry_direction_crossing_count": int(crossings[:, index, entry_column].sum()),
                "exit_direction_crossing_count": int(crossings[:, index, exit_column].sum()),
                "repeated_crossing_particles": int(np.count_nonzero(crossings[:, index].sum(axis=1) > 1)),
                "semantics": "saved-frame finite-aperture bracket; hidden crossings unresolved",
            })
        source_events = []
        for source_code in range(1, nsource + 1):
            mask = source == source_code
            source_events.append({
                "source_label": source_code,
                "initial_mass_kg": float(masses[mask].sum()),
                "residence_mass_weighted_s": [float((residence[mask, ri] * masses[mask]).sum() / masses[mask].sum()) if masses[mask].sum() else None for ri in range(residence.shape[1])],
                "unresolved_interval_mass_kg_s": float((unresolved[mask] * masses[mask]).sum()),
                "missing_identity_mass_kg": float(masses[mask & (final == -1)].sum()),
                "missing_identity_mass_fraction": float(masses[mask & (final == -1)].sum() / masses[mask].sum()) if masses[mask].sum() else None,
                "unknown_destination_mass_kg": float(masses[mask & (final == 0)].sum()),
                "unknown_destination_mass_fraction": float(masses[mask & (final == 0)].sum() / masses[mask].sum()) if masses[mask].sum() else None,
            })
        return {
            "schema": SCHEMA,
            "source_report_schema": LEGACY_LABEL_SCHEMA,
            "status": "TRAJECTORY_LABELS_RECOVERED_FROM_COMPLETED_H5",
            "case_key": "F2/scan-F2-S1-001",
            "physical_case_id": "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090",
            "source_contract": contract_info,
            "output_hdf5": {"path": str(output.resolve()), "bytes": output.stat().st_size, "sha256": sha256(output)},
            "trajectory": {"frames": len(time), "identities": len(source), "time_window_s": [float(time[0]), float(time[-1])], "initial_fluid_mass_kg": total},
            "missing_identity_observations": {
                "censored_particle_count": int(missing_censor.sum()),
                "first_gap_bracket_time_bounds_s": [float(np.nanmin(missing_gap[:, 0])), float(np.nanmax(missing_gap[:, 1]))] if np.any(missing_censor) else None,
                "semantics": "first saved-frame gap bracket only; physical event time, downstream region and fate UNKNOWN",
            },
            "source_cohorts": source_mass,
            "final_category_mass_kg": category_mass,
            "mass_screen": {
                "initial_fluid_mass_kg": total,
                "missing_identity_mass_kg": missing_mass,
                "missing_identity_mass_fraction": missing_mass / total if total else None,
                "invalid_state_mass_kg": invalid_mass,
                "unknown_final_destination_mass_kg": unknown_destination_mass,
                "task_mass_fraction_tolerance": contract_info["config"]["gates"]["task_mass_fraction_tolerance"],
                "unknown_width_gate_fraction": contract_info["config"]["gates"]["unknown_width_gate_fraction"],
                "decision": "screening_only; no physical-fate or dynamics credit",
            },
            "source_cohort_diagnostics": source_events,
            "events": events,
            "moving_source_frame": {"coordinate_frame": "fixed_solver_frame", "source_assignment": "native_initial_mk", "motion": "generated XML objreal ref=0, y-axis rotation; positions are not reclassified into a moving frame"},
            "unknown_scope": {"missing_identity": "open-lifecycle right censoring; physical fate and legal flux UNKNOWN", "unresolved_intervals": "saved-frame identity gaps; exact event time UNKNOWN inside bracket", "dynamics": "UNKNOWN; no momentum/force/QN/QE inference"},
            "gates": contract_info["config"]["gates"],
            "read_policy": {"h5_opened": True, "trajectory_content_opened": True, "solver_started": False, "cfd_or_model_run": False, "decoder_started": False},
        }


def run(contract_path: Path, output_h5: Path, report_path: Path, particle_chunk: int) -> dict[str, Any]:
    info = validate_contract(contract_path, read_h5=False)
    operator = _load_operator()
    operator.materialize(Path(info["trajectory_hdf5"]["path"]), output_h5, info["config"], particle_chunk=particle_chunk)
    # The operator performed source pre/post hashing.  Revalidate only the
    # metadata here; a third full H5 pass would add no evidence and would
    # inflate the declared guarded read cost.
    info = validate_contract(contract_path, read_h5=False)
    report = summarize(output_h5, info)
    report_path = Path(report_path).expanduser().resolve()
    if report_path.exists():
        raise TrajectoryLabelError(f"refusing to overwrite report: {report_path}")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    fd, temporary = tempfile.mkstemp(prefix=f".{report_path.name}.", dir=str(report_path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            fd = -1
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, report_path)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return report


def _stable_failed_receipt(failed_receipt_path: Path, contract_path: Path,
                           recovered_h5: Path, *, verify_small_inputs: bool) -> dict[str, Any]:
    """Validate the consumed failed attempt without treating it as science."""
    receipt = read_json(failed_receipt_path, "v1 failed execution receipt")
    if receipt.get("schema") != "ds02.execution-receipt.v1":
        raise TrajectoryLabelError("v1 failed receipt schema differs")
    if receipt.get("status") != "failed" or int(receipt.get("returncode", 0)) == 0:
        raise TrajectoryLabelError("recovery requires a recorded failed v1 receipt")
    request = receipt.get("request")
    if not isinstance(request, dict) or request.get("case_id") != "STAGE2_F2_S1_TRAJECTORY_LABELS_V1":
        raise TrajectoryLabelError("failed receipt is not the exact F2-S1 v1 attempt")
    launch = receipt.get("input_hashes_at_launch")
    after = receipt.get("input_hashes_after_run")
    if not isinstance(launch, dict) or launch != after:
        raise TrajectoryLabelError("v1 failed receipt input hashes are not stable")
    request_inputs = request.get("input_files")
    if not isinstance(request_inputs, list) or not request_inputs:
        raise TrajectoryLabelError("v1 failed receipt lacks input_files")
    request_declared = request.get("input_sha256") or request.get("input_hashes")
    if not isinstance(request_declared, dict):
        raise TrajectoryLabelError("v1 failed receipt lacks declared input hashes")
    contract_resolved = str(contract_path.expanduser().resolve())
    contract_seen = False
    trajectory_path = None
    stable_small_count = 0
    for raw_path in request_inputs:
        path = Path(str(raw_path)).expanduser().resolve()
        key = str(path)
        if key not in launch or key not in request_declared or launch[key] != request_declared[key]:
            raise TrajectoryLabelError(f"failed receipt request hash map differs: {path}")
        if path == contract_path.expanduser().resolve():
            contract_seen = True
        if path.suffix.lower() in {".h5", ".hdf5"}:
            trajectory_path = path
            if launch[key] != EXPECTED_H5_SHA256:
                raise TrajectoryLabelError("failed receipt source H5 digest differs")
            if path.stat().st_size != EXPECTED_H5_BYTES:
                raise TrajectoryLabelError("failed receipt source H5 byte count differs")
            # The original 1.19 GB H5 is intentionally never content-read or
            # rehashed by recovery.  Its producer digest and stat are bound.
            continue
        if not path.is_file():
            raise TrajectoryLabelError(f"failed receipt small input is missing: {path}")
        if verify_small_inputs and sha256(path) != launch[key]:
            raise TrajectoryLabelError(f"failed receipt small input changed: {path}")
        stable_small_count += 1
    if not contract_seen:
        raise TrajectoryLabelError("failed receipt does not bind the recovery contract")
    expected_trajectory = str(read_json(contract_path, "F2-S1 source contract").get("trajectory_hdf5", {}).get("path", ""))
    if trajectory_path is None or str(trajectory_path) != str(Path(expected_trajectory).expanduser().resolve()):
        raise TrajectoryLabelError("failed receipt source H5 differs from source contract")
    if not recovered_h5.is_file() or recovered_h5.stat().st_size <= 0:
        raise TrajectoryLabelError("recovered label H5 is missing or empty")
    stdout_path = failed_receipt_path.parent / "stdout.log"
    stdout_sha = receipt.get("stdout_sha256")
    if not stdout_path.is_file() or not isinstance(stdout_sha, str) or sha256(stdout_path) != stdout_sha:
        raise TrajectoryLabelError("v1 failed stdout is missing or differs from receipt")
    command = request.get("command")
    if not isinstance(command, list) or not any(str(item).endswith("ds_data02_stage2_f2_s1_trajectory_labels_v1.py") for item in command):
        raise TrajectoryLabelError("failed receipt command is not the consumed v1 worker")
    return {
        "path": str(failed_receipt_path.resolve()),
        "sha256": sha256(failed_receipt_path),
        "status": receipt.get("status"),
        "returncode": int(receipt.get("returncode")),
        "termination_reason": receipt.get("termination_reason"),
        "stable_input_count": stable_small_count,
        "source_trajectory_path": str(trajectory_path),
        "source_trajectory_sha256": EXPECTED_H5_SHA256,
        "source_trajectory_bytes": EXPECTED_H5_BYTES,
        "stdout_path": str(stdout_path.resolve()),
        "stdout_sha256": stdout_sha,
        "failure_credit": "none; v1 worker summary schema failure only",
        "old_attempt_preserved": True,
    }


def recover(contract_path: Path, failed_receipt_path: Path, recovered_h5: Path,
            report_path: Path) -> dict[str, Any]:
    """Read the completed v1 label H5 and write a separate v2 report."""
    info = validate_contract(contract_path, read_h5=False)
    failure = _stable_failed_receipt(failed_receipt_path, contract_path, recovered_h5,
                                     verify_small_inputs=True)
    report = summarize(recovered_h5, info)
    report["schema"] = SCHEMA
    report["source_report_schema"] = LEGACY_LABEL_SCHEMA
    report["recovery"] = {
        "kind": "forward_only_failed_summary_recovery",
        "failed_attempt": failure,
        "input_h5_sha256": sha256(recovered_h5),
        "input_h5_bytes": recovered_h5.stat().st_size,
        "source_trajectory_h5_opened": False,
        "source_trajectory_h5_rehashed": False,
        "old_h5_or_report_mutated": False,
        "complete_boolean_policy": "Python bool or numpy.bool_ True only; strings/integers rejected",
    }
    report_path = Path(report_path).expanduser().resolve()
    if report_path.exists():
        raise TrajectoryLabelError(f"refusing to overwrite report: {report_path}")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    fd, temporary = tempfile.mkstemp(prefix=f".{report_path.name}.", dir=str(report_path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            fd = -1
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, report_path)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return report


def make_recovery_request(contract_path: Path, failed_receipt_path: Path,
                          recovered_h5: Path, output: Path,
                          worktree_root: Path,
                          runtime_paths: list[Path] | None = None) -> dict[str, Any]:
    """Prepare a guard request that reads only the completed 4 MB label H5."""
    contract_path = Path(contract_path).expanduser().resolve()
    failed_receipt_path = Path(failed_receipt_path).expanduser().resolve()
    recovered_h5 = Path(recovered_h5).expanduser().resolve()
    info = validate_contract(contract_path, read_h5=False)
    failure = _stable_failed_receipt(failed_receipt_path, contract_path, recovered_h5,
                                     verify_small_inputs=True)
    root = Path(worktree_root).expanduser().resolve()
    worker = root / "lagrangian-fluid-lab/scripts/ds_data02_stage2_f2_s1_trajectory_labels_v2.py"
    operator = root / "lagrangian-fluid-lab/scripts/ds_data02_stage2_f2_s1_trajectory_labels_operator_v1.py"
    if runtime_paths is None:
        runtime_paths = [
            root / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py",
            root / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py",
            root / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py",
        ]
    runtime_paths = [Path(path).expanduser().resolve() for path in runtime_paths]
    source_paths: list[Path] = [worker, operator, contract_path, failed_receipt_path, recovered_h5,
                                Path(failure["stdout_path"]), *runtime_paths]
    old_receipt = read_json(failed_receipt_path, "v1 failed execution receipt")
    old_request = old_receipt.get("request", {})
    for raw_path in old_request.get("input_files", []):
        path = Path(str(raw_path)).expanduser().resolve()
        if path.suffix.lower() in {".h5", ".hdf5"}:
            continue
        source_paths.append(path)
    unique: list[Path] = []
    seen: set[str] = set()
    for path in source_paths:
        if str(path) in seen:
            continue
        if not path.is_file():
            continue
        unique.append(path)
        seen.add(str(path))
    missing = [str(path) for path in [worker, operator, contract_path, failed_receipt_path, recovered_h5, *runtime_paths] if not path.is_file()]
    input_sha256 = {str(path): sha256(path) for path in unique}
    deferred_source = {
        failure["source_trajectory_path"]: {
            "sha256": EXPECTED_H5_SHA256,
            "bytes": EXPECTED_H5_BYTES,
            "digest_source": "consumed v1 producer/guard receipt",
            "content_hash_deferred": True,
            "content_read_by_recovery_worker": False,
        }
    }
    request = {
        "schema": "ds02.runner-request.v1",
        "request_schema": RECOVERY_REQUEST_SCHEMA,
        "attempt_id": "f2-s1-trajectory-labels-recovery-v2",
        "case_id": "STAGE2_F2_S1_TRAJECTORY_LABELS_RECOVERY_V2",
        "family_id": "F2",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 1,
        "max_wall_seconds": 900,
        "estimated_storage_bytes": 32 * 1024 * 1024,
        "cwd": str(root / "lagrangian-fluid-lab/scripts"),
        "worktree_root": str(root),
        "command": [
            "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python",
            str(worker), "recover", "--contract", str(contract_path),
            "--failed-receipt", str(failed_receipt_path), "--input-h5", str(recovered_h5),
            "--output", "{attempt_root}/f2-s1-trajectory-labels-recovery-v2.json",
        ],
        "input_files": [str(path) for path in unique],
        "input_sha256": input_sha256,
        "deferred_source_bindings": deferred_source,
        "launch_allowed": not missing,
        "primary_launch_owner": "root",
        "status": "prepared_guard_pending_actual_CPU" if not missing else "prepared_missing_guard_sources",
        "source_cost": {
            "recovered_label_h5_bytes_read": recovered_h5.stat().st_size if recovered_h5.is_file() else 0,
            "original_source_trajectory_h5_bytes_read": 0,
            "original_source_trajectory_h5_rehashed": False,
            "small_input_bytes_read": sum(path.stat().st_size for path in unique),
            "solver_started": False,
            "cfd_or_model_run": False,
        },
        "failed_attempt_binding": failure,
        "qualification": {"physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN", "QN": "NOT_ASSESSED", "QE": "NOT_ASSESSED"},
        "claim_boundary": {
            "missing_identity": "saved-frame open-lifecycle censoring only",
            "physical_fate": "UNKNOWN",
            "dynamics": "UNKNOWN",
            "failure_interpretation": "v1 summary schema failure; not a physical or source failure",
        },
        "request_note": "Forward-only summary of the completed v1 label H5. The original 1.19 GB trajectory is stat/declaration-bound and never opened or rehashed; old failed receipt and H5 bytes are immutable.",
    }
    output = Path(output).expanduser().resolve()
    if output.exists():
        raise TrajectoryLabelError(f"refusing to overwrite recovery request: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return request


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare", help="validate metadata without opening H5")
    prep.add_argument("--contract", type=Path, required=True)
    prep.add_argument("--output", type=Path, required=True)
    run_parser = sub.add_parser("run", help="run after shared guard binds the H5")
    run_parser.add_argument("--contract", type=Path, required=True)
    run_parser.add_argument("--output-h5", type=Path, required=True)
    run_parser.add_argument("--output", type=Path, required=True)
    run_parser.add_argument("--particle-chunk", type=int, default=16384)
    recover_parser = sub.add_parser("recover", help="summarize a completed v1 label H5 without reopening source H5")
    recover_parser.add_argument("--contract", type=Path, required=True)
    recover_parser.add_argument("--failed-receipt", type=Path, required=True)
    recover_parser.add_argument("--input-h5", type=Path, required=True)
    recover_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        info = validate_contract(args.contract, read_h5=False)
        result = {"schema": SCHEMA, "status": "PREPARED_H5_READ_DEFERRED", "contract": info,
                  "source_read_cost": info["contract"].get("source_read_cost"),
                  "read_policy": {"h5_opened": False, "trajectory_content_opened": False, "solver_started": False}}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        if args.output.exists():
            raise TrajectoryLabelError(f"refusing to overwrite output: {args.output}")
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(result, indent=2, sort_keys=True))
    elif args.command == "recover":
        print(json.dumps(recover(args.contract, args.failed_receipt, args.input_h5, args.output), indent=2, sort_keys=True))
    else:
        print(json.dumps(run(args.contract, args.output_h5, args.output, args.particle_chunk), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
