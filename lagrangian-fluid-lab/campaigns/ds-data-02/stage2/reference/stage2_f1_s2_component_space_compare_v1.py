#!/usr/bin/env python3
"""Compare compact F1-S2 native observer records without opening payloads.

The worker consumes only three small JSON observer reports, their producer
proof reference, and the three generated XML files.  It never opens a BI4,
H5, VTK, or solver output tree.  All comparisons are in the solver's ordered
component basis; missing producer-to-world orientation keeps world-frame
claims UNKNOWN.  Actual saved times are retained and no field interpolation
is performed.
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
import xml.etree.ElementTree as ET
from typing import Any, Iterable


HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[4]
CONTRACT = HERE / "stage2_f1_s2_component_space_compare_contract_v1.json"
WORKER = HERE / "stage2_f1_s2_component_space_compare_v1.py"
SCHEMA = "ds02.stage2.f1-s2.component-space-compare.v1"
MANIFEST_SCHEMA = "ds02.stage2.f1-s2.component-space-compare-manifest.v1"
MAX_FILE_BYTES = 16 * 1024 * 1024
TIME_TOLERANCE_S = 1.0e-12
QUALIFICATION = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}


class CompareFailure(RuntimeError):
    pass


def _abs(path: str | Path) -> Path:
    return Path(path).expanduser().absolute()


def _stat_tuple(st: os.stat_result) -> tuple[int, int, int, int, int]:
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)


def _stable_bytes(path: Path, label: str, expected_sha: str | None = None, *, max_bytes: int = MAX_FILE_BYTES) -> tuple[bytes, dict[str, Any]]:
    path = _abs(path)
    literal_venv_python = path.is_symlink() and str(path).endswith("/.venv/bin/python")
    if (path.is_symlink() and not literal_venv_python) or not path.is_file():
        raise CompareFailure(f"{label} is not a regular non-symlink file: {path}")
    before = path.stat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > max_bytes:
        raise CompareFailure(f"{label} is missing, non-regular, or exceeds the bounded read size: {path}")
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    after = path.stat()
    if _stat_tuple(before) != _stat_tuple(after):
        raise CompareFailure(f"{label} changed while being read: {path}")
    if expected_sha and expected_sha not in {"PARENT_AFTER_RESERVATION", "UNKNOWN"} and digest != expected_sha:
        raise CompareFailure(f"{label} SHA differs from the producer binding: {digest} != {expected_sha}")
    record = {
        "path": str(path),
        "bytes": int(after.st_size),
        "sha256": digest,
        "device": int(after.st_dev),
        "inode": int(after.st_ino),
        "mtime_ns": int(after.st_mtime_ns),
        "ctime_ns": int(after.st_ctime_ns),
        "link_count": int(after.st_nlink),
    }
    if literal_venv_python:
        record["literal_argv0"] = True
        record["symlink_target"] = str(path.resolve(strict=True))
    return data, record


def _json_file(path: Path, label: str, expected_sha: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    raw, record = _stable_bytes(path, label, expected_sha)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CompareFailure(f"{label} is not bounded UTF-8 JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise CompareFailure(f"{label} must contain a JSON object")
    return value, record


def _finite(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise CompareFailure(f"{label} is not numeric") from exc
    if not math.isfinite(number):
        raise CompareFailure(f"{label} is non-finite")
    return number


def _vector(value: Any, label: str) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise CompareFailure(f"{label} is not a 3-component vector")
    return [_finite(item, f"{label}[{index}]") for index, item in enumerate(value)]


def _value(value: Any, label: str) -> float:
    if isinstance(value, dict):
        if "value" in value:
            return _finite(value["value"], label)
        if "v" in value:
            return _finite(value["v"], label)
    return _finite(value, label)


def _walk(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _case_label(case: dict[str, Any]) -> str:
    pieces: list[str] = []
    for key in ("label", "case_id", "identity"):
        value = case.get(key)
        if isinstance(value, str):
            pieces.append(value)
        elif isinstance(value, dict):
            pieces.extend(str(item) for item in value.values() if isinstance(item, (str, int, float)))
    return " ".join(pieces).lower()


def _select_case(report: dict[str, Any], grid: dict[str, Any]) -> dict[str, Any]:
    aliases = [str(alias).lower() for alias in grid.get("aliases", [])]
    candidates = [item for item in _walk(report) if isinstance(item.get("selected_observations"), list)]
    matched = [item for item in candidates if any(alias in _case_label(item) for alias in aliases)]
    if len(matched) != 1:
        if len(candidates) == 1 and grid.get("allow_single_case", False):
            return candidates[0]
        raise CompareFailure(f"expected one {grid.get('label')} compact observer case, found {len(matched)}")
    return matched[0]


def _fluid_observable(row: dict[str, Any]) -> dict[str, Any]:
    observables = row.get("observables")
    if not isinstance(observables, dict):
        observables = {}
    candidates = [
        observables.get("fluid_observable_using_native_MassFluid"),
        observables.get("fluid"),
        row.get("groups", {}).get("fluid") if isinstance(row.get("groups"), dict) else None,
    ]
    fluid = next((item for item in candidates if isinstance(item, dict)), None)
    if fluid is None:
        raise CompareFailure("observer row has no fluid weighted observable group")
    com = fluid.get("weighted_centroid_m", fluid.get("weighted_com_m", fluid.get("centroid_m")))
    velocity = fluid.get("weighted_velocity_m_per_s", fluid.get("velocity_m_per_s"))
    ke = fluid.get("kinetic_energy_j", fluid.get("kinetic_energy"))
    mass = fluid.get("sample_mass_kg", fluid.get("mass_kg", fluid.get("mass")))
    return {
        "mass_kg": _value(mass, "fluid sample mass"),
        "weighted_centroid_m": _vector(com, "fluid weighted centroid"),
        "weighted_velocity_m_per_s": _vector(velocity, "fluid weighted velocity"),
        "kinetic_energy_j": _finite(ke, "fluid kinetic energy"),
    }


def _row_time(row: dict[str, Any]) -> float:
    for key in ("time_s", "runparts_time_s"):
        if key in row:
            return _finite(row[key], key)
    time = row.get("time")
    if isinstance(time, dict):
        for key in ("time_s", "saved_time_s", "actual_time_s"):
            if key in time:
                return _finite(time[key], f"time.{key}")
    raise CompareFailure("observer row has no actual saved time")


def _row(row: Any, label: str) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise CompareFailure(f"{label} is not an observer row")
    time_s = _row_time(row)
    header = row.get("native_header")
    if not isinstance(header, dict):
        raise CompareFailure(f"{label} has no native header")
    mass_fluid = header.get("MassFluid")
    dp = header.get("Dp")
    if mass_fluid is None or dp is None:
        raise CompareFailure(f"{label} lacks native MassFluid/Dp")
    obs = row.get("observables") if isinstance(row.get("observables"), dict) else {}
    roles = obs.get("role_counts", row.get("role_counts"))
    if not isinstance(roles, dict):
        raise CompareFailure(f"{label} lacks typed role counts")
    if int(roles.get("fluid", -1)) <= 0 or int(roles.get("total", -1)) <= 0:
        raise CompareFailure(f"{label} has invalid typed role counts")
    if int(roles.get("fixed", -1)) < 0 or int(roles.get("moving", -1)) < 0 or int(roles.get("floating", -1)) < 0:
        raise CompareFailure(f"{label} has invalid fixed/moving/floating counts")
    excluded = obs.get("fixed_moving_excluded_from_fluid_observables", row.get("fixed_moving_excluded_from_fluid_observables"))
    if excluded is not True:
        raise CompareFailure(f"{label} does not prove fixed/moving exclusion from fluid aggregates")
    return {
        "time_s": time_s,
        "native_mass_fluid_kg": _value(mass_fluid, f"{label} MassFluid"),
        "native_dp_m": _value(dp, f"{label} Dp"),
        "role_counts": {key: int(roles.get(key, 0)) for key in ("fluid", "fixed", "moving", "floating", "total")},
        "fluid": _fluid_observable(row),
        "native_field_digest_sha256": row.get("native_field_digest_sha256"),
    }


def _parse_xml(data: bytes, label: str) -> dict[str, Any]:
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise CompareFailure(f"{label} XML is invalid: {exc}") from exc
    params = {node.get("key"): node.get("value") for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "parameter" and node.get("key")}
    gravity_nodes = [node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "gravity" and node.get("units_comment") == "m/s^2"]
    if len(gravity_nodes) != 1:
        raise CompareFailure(f"{label} has no unique unit-bound gravity node")
    gravity = [_finite(gravity_nodes[0].get(axis), f"{label} gravity {axis}") for axis in ("x", "y", "z")]
    definition = next((node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "definition"), None)
    if definition is None:
        raise CompareFailure(f"{label} has no geometry definition")
    dp = _finite(definition.get("dp"), f"{label} dp")
    # GenCase emits an empty ``<motion/>`` container even when no moving or
    # floating body is configured.  Only a populated container is an active
    # motion control record; treating the empty structural node as motion
    # would falsely fail the same-control join.
    motion = [
        node.tag.rsplit("}", 1)[-1]
        for node in root.iter()
        if node.tag.rsplit("}", 1)[-1].lower() in {"motion", "moving", "floating"}
        and (bool(node.attrib) or len(list(node)) > 0 or bool((node.text or "").strip()))
    ]
    return {"parameters": params, "gravity": gravity, "dp_m": dp, "motion_tags": motion}


def _xml_control(cases: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    keys = ["Boundary", "SavePosDouble", "StepAlgorithm", "VerletSteps", "Kernel", "ViscoTreatment", "Shifting", "RigidAlgorithm", "CoefDtMin", "TimeOut", "RhopOutMin", "RhopOutMax", "TimeMax"]
    base = cases[0][1]
    equal = all(all(item["parameters"].get(key) == base["parameters"].get(key) for key in keys) for _, item in cases[1:])
    gravity_equal = all(item["gravity"] == base["gravity"] for _, item in cases[1:])
    no_motion = all(not item["motion_tags"] for _, item in cases)
    return {"equal_parameters": equal, "equal_gravity": gravity_equal, "no_motion_tags": no_motion, "checked_keys": keys, "values": {label: {key: item["parameters"].get(key) for key in keys} for label, item in cases}, "gravity": {label: item["gravity"] for label, item in cases}, "diagnostic_status": "PASS_SOURCE_CONTROL_JOIN" if equal and gravity_equal and no_motion else "FAIL_SOURCE_CONTROL_JOIN"}


def _bracket(rows: list[dict[str, Any]], query: float) -> dict[str, Any]:
    if not rows:
        raise CompareFailure("observer case has no selected observations")
    for index, row in enumerate(rows):
        if abs(row["time_s"] - query) <= TIME_TOLERANCE_S:
            return {"status": "EXACT", "query_time_s": query, "lower_index": index, "upper_index": index, "lower_time_s": row["time_s"], "upper_time_s": row["time_s"], "bracket_width_s": 0.0}
        if row["time_s"] > query:
            lower = index - 1
            if lower < 0:
                return {"status": "OUTSIDE_SAVED_WINDOW", "query_time_s": query}
            return {"status": "BRACKETED", "query_time_s": query, "lower_index": lower, "upper_index": index, "lower_time_s": rows[lower]["time_s"], "upper_time_s": row["time_s"], "bracket_width_s": row["time_s"] - rows[lower]["time_s"]}
    return {"status": "OUTSIDE_SAVED_WINDOW", "query_time_s": query}


def _delta(a: list[float], b: list[float]) -> float:
    return max(abs(x - y) for x, y in zip(a, b))


def _case_metrics(case: dict[str, Any], grid: dict[str, Any]) -> dict[str, Any]:
    raw_rows = case.get("selected_observations")
    if not isinstance(raw_rows, list) or not raw_rows:
        raise CompareFailure(f"{grid['label']} case has no selected observations")
    rows = [_row(value, f"{grid['label']} row {index}") for index, value in enumerate(raw_rows)]
    if any(right["time_s"] <= left["time_s"] for left, right in zip(rows, rows[1:])):
        raise CompareFailure(f"{grid['label']} saved times are not strictly increasing")
    masses = {row["native_mass_fluid_kg"] for row in rows}
    dps = {row["native_dp_m"] for row in rows}
    if len(masses) != 1 or len(dps) != 1:
        raise CompareFailure(f"{grid['label']} native MassFluid/Dp is not stable across selected rows")
    return {"label": grid["label"], "case_label": _case_label(case), "rows": rows, "native_summary": {"MassFluid_kg": next(iter(masses)), "Dp_m": next(iter(dps)), "sample_mass_is_not_continuum_owner": True}, "brackets": {str(query): _bracket(rows, query) for query in (0.0, 1.0, 2.0, 3.0, 4.0)}}


def _pairwise(metrics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for left_index, left in enumerate(metrics):
        for right in metrics[left_index + 1:]:
            right_by_time = {row["time_s"]: row for row in right["rows"]}
            exact: list[dict[str, Any]] = []
            for row in left["rows"]:
                match = next((item for item in right["rows"] if abs(item["time_s"] - row["time_s"]) <= TIME_TOLERANCE_S), None)
                if match is None:
                    continue
                exact.append({
                    "time_s": row["time_s"],
                    "mass_delta_kg": abs(row["fluid"]["mass_kg"] - match["fluid"]["mass_kg"]),
                    "centroid_max_abs_delta_m": _delta(row["fluid"]["weighted_centroid_m"], match["fluid"]["weighted_centroid_m"]),
                    "velocity_max_abs_delta_m_per_s": _delta(row["fluid"]["weighted_velocity_m_per_s"], match["fluid"]["weighted_velocity_m_per_s"]),
                    "kinetic_energy_abs_delta_j": abs(row["fluid"]["kinetic_energy_j"] - match["fluid"]["kinetic_energy_j"]),
                })
            results.append({
                "left": left["label"],
                "right": right["label"],
                "exact_saved_time_count": len(exact),
                "exact_component_diagnostics": exact,
                "asynchronous_saved_time_status": "UNKNOWN_WHEN_NO_EXACT_ROWS" if not exact else "RETAINED_SEPARATELY",
                "interpolation": "NOT_PERFORMED",
                "spatial_difference_is_truth": False,
                "pairwise_reference": "diagnostic only",
            })
    return results


def _load_manifest(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest, record = _json_file(path, "comparison manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise CompareFailure("unexpected comparison manifest schema")
    return manifest, record


def run(args: argparse.Namespace) -> dict[str, Any]:
    manifest, manifest_record = _load_manifest(args.manifest)
    contract, contract_record = _json_file(_abs(manifest["contract_path"]), "comparison contract", manifest.get("contract_sha256"))
    if contract.get("schema") != "ds02.stage2.f1-s2.component-space-compare-contract.v1":
        raise CompareFailure("unexpected F1-S2 component comparison contract")
    source_records: list[dict[str, Any]] = []
    for record in manifest.get("source_files", []):
        if not isinstance(record, dict):
            raise CompareFailure("malformed static source record")
        _data, current = _stable_bytes(Path(record["path"]), "static source", record.get("sha256"))
        source_records.append(current)
    proof = manifest.get("producer_proof")
    if not isinstance(proof, dict):
        raise CompareFailure("producer proof binding is missing")
    _proof_data, proof_record = _stable_bytes(Path(proof["path"]), "ROOT207 producer proof", proof.get("sha256"))
    xml_meta: list[tuple[str, dict[str, Any]]] = []
    reports: list[dict[str, Any]] = []
    metrics: list[dict[str, Any]] = []
    for grid in manifest.get("grids", []):
        if not isinstance(grid, dict) or not isinstance(grid.get("label"), str):
            raise CompareFailure("malformed grid binding")
        xml_data, xml_record = _stable_bytes(Path(grid["xml_path"]), f"{grid['label']} XML", grid.get("xml_sha256"))
        xml_meta.append((grid["label"], _parse_xml(xml_data, f"{grid['label']} XML")))
        report, report_record = _json_file(Path(grid["report_path"]), f"{grid['label']} compact observer report", grid.get("report_sha256"))
        case = _select_case(report, grid)
        metrics.append(_case_metrics(case, grid))
        reports.append({"label": grid["label"], "record": report_record, "case_label": _case_label(case)})
    if [item[0] for item in xml_meta] != [item["label"] for item in metrics]:
        raise CompareFailure("grid ordering differs between XML and observer bindings")
    control = _xml_control(xml_meta)
    result = {
        "schema": SCHEMA,
        "status": "COMPLETE_COMPONENT_SPACE_DIAGNOSTICS_NO_SCIENTIFIC_Q",
        "scope": {"compact_json_only": True, "production_native_payload_read": False, "solver_started": False, "interpolation": False, "qualification": QUALIFICATION},
        "manifest": manifest_record,
        "contract": contract_record,
        "producer_proof": proof_record,
        "source_records": source_records,
        "reports": reports,
        "xml_control": control,
        "grid_metrics": metrics,
        "pairwise_component_diagnostics": _pairwise(metrics),
        "mass_scope": {"native_sample_mass": "reported per grid", "continuum_owner_mass": "UNKNOWN", "neighbor_grid_truth": False},
        "time_scope": {"query_times_s": [0.0, 1.0, 2.0, 3.0, 4.0], "actual_saved_time_brackets": {item["label"]: item["brackets"] for item in metrics}, "field_interpolation": "FORBIDDEN", "event_characteristic_time": "UNKNOWN"},
        "world_orientation": {"status": "UNKNOWN", "component_space_only": True},
        "reader_calibration_prerequisite": contract.get("reader_calibration_prerequisite", {"status": "UNDECLARED"}),
        "scientific_qualification": QUALIFICATION,
    }
    output = _abs(args.output)
    if output.exists() or output.is_symlink():
        raise CompareFailure(f"refusing to overwrite output: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def _self_test() -> dict[str, Any]:
    # The fixture exercises the actual --run manifest path with three compact
    # reports.  It never opens a repository or production payload.
    with tempfile.TemporaryDirectory(prefix="f1-s2-component-compare-") as tmp_name:
        tmp = Path(tmp_name)
        xml_paths: dict[str, Path] = {}
        report_paths: dict[str, Path] = {}
        grid_specs = {"coarse": ("0.0225", 0.4), "medium": ("0.020", 0.5), "fine": ("0.017", 0.6)}
        for label, (dp, offset) in grid_specs.items():
            xml = tmp / f"{label}.xml"
            xml.write_text(
                "<case><gravity units_comment='m/s^2' x='0' y='0' z='-9.81'/>"
                f"<definition dp='{dp}'/><parameter key='Boundary' value='DBC'/><parameter key='TimeMax' value='4.0'/></case>\n",
                encoding="utf-8",
            )
            xml_paths[label] = xml
            rows = []
            for time_s in (0.0, 1.0, 2.0, 3.0, 4.0):
                rows.append({
                    "time_s": time_s,
                    "native_header": {"MassFluid": {"value": 0.5}, "Dp": {"value": float(dp)}},
                    "observables": {
                        "role_counts": {"fluid": 1, "fixed": 1, "moving": 0, "floating": 0, "total": 2},
                        "fixed_moving_excluded_from_fluid_observables": True,
                        "fluid_observable_using_native_MassFluid": {
                            "sample_mass_kg": 0.5,
                            "weighted_centroid_m": [offset + time_s, 2.0, 3.0],
                            "weighted_velocity_m_per_s": [0.5, 0.25, -0.125],
                            "kinetic_energy_j": 0.25,
                        },
                    },
                })
            report = tmp / f"{label}.json"
            report.write_text(json.dumps({"schema": "ds02.stage2.f1.native-selected-observer.v1", "cases": [{"label": f"F1-S2 {label}", "selected_observations": rows}]}), encoding="utf-8")
            report_paths[label] = report
        proof = tmp / "proof.json"
        proof.write_text("{}\n", encoding="utf-8")
        _contract_data, contract_record = _json_file(CONTRACT, "self-test contract")
        manifest = {
            "schema": MANIFEST_SCHEMA,
            "contract_path": str(CONTRACT),
            "contract_sha256": contract_record["sha256"],
            "source_files": [],
            "producer_proof": {"path": str(proof), "sha256": hashlib.sha256(proof.read_bytes()).hexdigest()},
            "grids": [
                {"label": label, "aliases": [label], "xml_path": str(xml_paths[label]), "xml_sha256": hashlib.sha256(xml_paths[label].read_bytes()).hexdigest(), "report_path": str(report_paths[label]), "report_sha256": hashlib.sha256(report_paths[label].read_bytes()).hexdigest()}
                for label in ("coarse", "medium", "fine")
            ],
        }
        manifest_path = tmp / "manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        output = tmp / "output.json"
        result = run(argparse.Namespace(manifest=manifest_path, output=output))
        assert result["status"] == "COMPLETE_COMPONENT_SPACE_DIAGNOSTICS_NO_SCIENTIFIC_Q"
        assert len(result["grid_metrics"]) == 3
        assert len(result["pairwise_component_diagnostics"]) == 3
        assert result["xml_control"]["diagnostic_status"] == "PASS_SOURCE_CONTROL_JOIN"
        assert result["scientific_qualification"] == QUALIFICATION
    return {"schema": SCHEMA, "status": "PASS", "production_payload_read": False, "solver_started": False, "qualification_credit": 0, "real_manifest_run": True}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--run", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.self_test:
        print(json.dumps(_self_test(), sort_keys=True))
        return 0
    if args.manifest is None or args.output is None:
        parser.error("--manifest and --output are required with --run")
    try:
        result = run(args)
    except Exception as exc:
        print(json.dumps({"schema": SCHEMA, "status": "FAILED_COMPONENT_SPACE_COMPARE", "reason": str(exc), "scientific_qualification": QUALIFICATION}, sort_keys=True))
        return 2
    print(json.dumps({"schema": SCHEMA, "status": result["status"], "output": str(_abs(args.output))}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
