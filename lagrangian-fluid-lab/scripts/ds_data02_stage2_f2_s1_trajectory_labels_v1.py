#!/usr/bin/env python3
"""Guarded trajectory labels for the exact F2-S1 CURRENT case.

The preparation path consumes only the completed source-closure metadata and
small XML/Run.out/RunPARTs files.  It deliberately does not hash or open the
trajectory H5.  The ``run`` path is the only path allowed to open that H5 and
is intended to be launched by the shared Stage2 guard after the request has
bound the H5 path, byte count and producer SHA.

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
SCHEMA = "ds02.stage2.f2-s1-trajectory-labels.v1"
CONTRACT_SCHEMA = "ds02.stage2.f2-s1-trajectory-source-contract.v1"


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
    conversion_binding = binding(conversion, "conversion report")
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
    xml_binding = binding(xml, "generated XML")
    geometry = _parse_xml_geometry(xml)
    runout = _path_from(contract.get("runout"), "Run.out")
    runparts = _path_from(contract.get("runparts"), "RunPARTs.csv")
    runout_binding = binding(runout, "Run.out")
    runparts_binding = binding(runparts, "RunPARTs.csv")
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
    if read_h5:
        # The operator performs its own source pre/post digest check.  This
        # second digest closes the wrapper contract after materialization.
        if sha256(h5) != EXPECTED_H5_SHA256:
            raise TrajectoryLabelError("trajectory H5 changed after labeling")
    return {
        "contract": contract,
        "current": current_binding,
        "trajectory_hdf5": h5_item,
        "conversion_report": conversion_binding,
        "source_closure": binding(closure_path, "F2-S1 source closure"),
        "generated_xml": xml_binding,
        "geometry": geometry,
        "runout": runout_binding,
        "runparts": runparts_binding,
        "native_run": native_run,
        "solver_receipt": binding(receipt, "solver receipt"),
        "label_config": binding(config_path, "label config"),
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


def summarize(output: Path, contract_info: dict[str, Any]) -> dict[str, Any]:
    import h5py
    import numpy as np

    with h5py.File(output, "r") as h:
        if h.attrs.get("source_hdf5_sha256") != EXPECTED_H5_SHA256 or h.attrs.get("complete") is not True:
            raise TrajectoryLabelError("operator output is not complete and source-bound")
        time = h["time"][:]
        source = h["source_label"][:]
        masses = h["initial_fluid_mass_kg"][:]
        nsource = len(contract_info["config"]["source_regions"])
        total = float(h.attrs["initial_fluid_mass_kg"])
        final = h["final_category"][:]
        category_mass = {str(code): float(masses[final == code].sum()) for code in range(-2, len(contract_info["config"]["destination_regions"]) + 1)}
        source_mass = {str(code): float(masses[source == code].sum()) for code in range(1, nsource + 1)}
        residence = h["residence_time_s"][:]
        unresolved = h["unresolved_interval_time_s"][:]
        crossings = h["event_crossing_counts"][:]
        first = h["first_passage_interval"][:]
        censor = h["first_passage_censor"][:]
        flux = h["forward_backward_mass_kg"][-1]
        net = h["cumulative_net_flux_kg"][-1]
        events = []
        for index, event in enumerate(contract_info["config"].get("events", [])):
            observed = censor[:, index] == 0
            events.append({
                "id": event["id"],
                "observed_first_passage_mass_kg": float(masses[observed].sum()),
                "censored_first_passage_mass_kg": float(masses[~observed].sum()),
                "first_passage_time_min_s": float(np.nanmin(first[observed, index, 0])) if np.any(observed) else None,
                "first_passage_time_max_s": float(np.nanmax(first[observed, index, 1])) if np.any(observed) else None,
                "forward_mass_kg": float(flux[index, 0]),
                "backward_mass_kg": float(flux[index, 1]),
                "net_flux_mass_kg": float(net[index]),
                "forward_crossing_count": int(crossings[:, index, 0].sum()),
                "backward_crossing_count": int(crossings[:, index, 1].sum()),
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
                "unknown_destination_mass_kg": float(masses[mask & (final == 0)].sum()),
            })
        return {
            "schema": SCHEMA,
            "status": "TRAJECTORY_LABELS_OBSERVED_OPEN_LIFECYCLE",
            "case_key": "F2/scan-F2-S1-001",
            "physical_case_id": "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090",
            "source_contract": contract_info,
            "output_hdf5": {"path": str(output.resolve()), "bytes": output.stat().st_size, "sha256": sha256(output)},
            "trajectory": {"frames": len(time), "identities": len(source), "time_window_s": [float(time[0]), float(time[-1])], "initial_fluid_mass_kg": total},
            "source_cohorts": source_mass,
            "final_category_mass_kg": category_mass,
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
    # Validate the H5 source after the operator's own before/after check and
    # only then emit the report.  A partial/changed source cannot receive a
    # successful label report.
    info = validate_contract(contract_path, read_h5=True)
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
    else:
        print(json.dumps(run(args.contract, args.output_h5, args.output, args.particle_chunk), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
