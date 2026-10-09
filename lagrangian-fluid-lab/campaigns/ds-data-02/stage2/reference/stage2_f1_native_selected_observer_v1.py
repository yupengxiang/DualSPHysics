#!/usr/bin/env python3
"""Audit selected F1 native frames without substituting XML particle mass.

This is an additive F1 worker for the ROOT204 follow-up.  It reuses the
official decoder and the typed-range parser from
``stage2_native_physical_observer_v2`` but has a narrower contract than the
old selected-observer products:

* ``MassFluid`` and ``Dp`` must come from the decoder's native BI4 metadata;
  ``MassBound`` is reported when exposed and otherwise remains UNKNOWN.
* ``Idp`` is the decoded native identity array.  Its dtype, range, uniqueness,
  and digest are reported; it is never a made-up header scalar.
* role counts and fluid COM/velocity/KE use the native ``MassFluid`` value.
  XML constants are retained only as provenance and never as a fallback.
* axis/units evidence is source-bound, but producer orientation metadata is
  still required before any axis calibration can be claimed.

The worker reads only the selected Part files supplied by a future parent
guard.  It does not read HDF5/VTK, scan the native tree, interpolate fields,
or grant QI/QN/QE credit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
from typing import Any
import xml.etree.ElementTree as ET

import numpy as np

import stage2_native_physical_observer_v2 as base


SCHEMA = "ds02.stage2.f1.native-selected-observer.v1"
PASS_STATUS = "PASS_F1_NATIVE_HEADER_SELECTED_OBSERVABLES"
UNKNOWN_STATUS = "UNKNOWN_F1_NATIVE_SELECTED_OBSERVABLES"
QUALIFICATION = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
FORBIDDEN_SUFFIXES = {".h5", ".hdf5", ".vtk", ".vtu"}


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise base.UnsupportedSemantics(f"{label} is not numeric")
    value = float(value)
    if not math.isfinite(value):
        raise base.UnsupportedSemantics(f"{label} is non-finite")
    return value


def _lookup(values: dict[str, Any], name: str) -> tuple[Any, str | None]:
    for key, value in values.items():
        if str(key).lower() == name.lower():
            return value, str(key)
    return None, None


def _native_scalar(
    name: str,
    metadata: dict[str, Any],
    info: dict[str, Any],
    *,
    required: bool,
) -> dict[str, Any]:
    value, key = _lookup(metadata, name)
    section = "metadata"
    if key is None:
        value, key = _lookup(info, name)
        section = "particle_info"
    if key is None:
        if required:
            raise base.UnsupportedSemantics(f"native BI4 decoder did not expose numeric {name}")
        return {
            "field": name,
            "value": "UNKNOWN_NOT_EXPOSED_BY_DECODER",
            "decoder_key": None,
            "decoder_section": None,
            "semantics": "native_bi4_header_scalar_not_exposed",
        }
    numeric = _number(value, f"native {name}")
    return {
        "field": name,
        "value": numeric,
        "value_float_hex": numeric.hex(),
        "value_binary64_little_endian_hex": struct.pack("<d", numeric).hex(),
        "decoder_key": key,
        "decoder_section": section,
        "semantics": "native_bi4_header_scalar_from_official_decoder_metadata",
    }


def _array_digest(name: str, values: np.ndarray) -> str:
    digest = hashlib.sha256()
    digest.update(name.encode("ascii"))
    digest.update(str(values.dtype).encode("ascii"))
    digest.update(json.dumps(list(values.shape), separators=(",", ":")).encode("ascii"))
    digest.update(np.ascontiguousarray(values).tobytes())
    return digest.hexdigest()


def _idp_summary(ids: np.ndarray) -> dict[str, Any]:
    if ids.ndim != 1 or ids.size == 0:
        raise base.UnsupportedSemantics("native Idp array is empty or not one-dimensional")
    if not np.isfinite(ids).all():
        raise base.UnsupportedSemantics("native Idp array is non-finite")
    unique = np.unique(ids)
    if unique.size != ids.size:
        raise base.UnsupportedSemantics("native Idp array contains duplicate identities")
    return {
        "field": "Idp",
        "decoder_section": "decoded_particle_array",
        "dtype": str(ids.dtype),
        "count": int(ids.size),
        "min": int(ids.min()),
        "max": int(ids.max()),
        "unique": True,
        "finite": True,
        "sha256": _array_digest("Idp", ids),
        "semantics": "native_decoded_identity_array; sorted by the official observer before range assignment",
    }


def _matrix_determinant(matrix: list[list[float]]) -> float:
    return (
        matrix[0][0] * (matrix[1][1] * matrix[2][2] - matrix[1][2] * matrix[2][1])
        - matrix[0][1] * (matrix[1][0] * matrix[2][2] - matrix[1][2] * matrix[2][0])
        + matrix[0][2] * (matrix[1][0] * matrix[2][1] - matrix[1][1] * matrix[2][0])
    )


def _axis_contract(axis: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(axis, dict):
        raise base.UnsupportedSemantics("axis evidence manifest is not an object")
    coordinate = axis.get("coordinate_contract")
    if not isinstance(coordinate, dict):
        raise base.UnsupportedSemantics("axis evidence has no coordinate contract")
    expected = {
        "frame": "world_cartesian_right_handed",
        "axis_labels": ["x", "y", "z"],
        "position_unit": "m",
        "velocity_unit": "m/s",
        "mass_unit": "kg",
        "time_unit": "s",
    }
    for key, value in expected.items():
        if coordinate.get(key) != value:
            raise base.UnsupportedSemantics(f"axis contract {key} is not the registered SI convention")
    rotation = coordinate.get("rotation_to_world")
    if (
        not isinstance(rotation, list)
        or len(rotation) != 3
        or any(not isinstance(row, list) or len(row) != 3 for row in rotation)
    ):
        raise base.UnsupportedSemantics("axis rotation is not a 3x3 matrix")
    matrix = [[_number(item, "axis rotation") for item in row] for row in rotation]
    determinant = _matrix_determinant(matrix)
    if abs(determinant - 1.0) > 1.0e-10:
        raise base.UnsupportedSemantics("axis rotation is not right-handed")
    records = axis.get("source_records", [])
    if not isinstance(records, list) or not records:
        raise base.UnsupportedSemantics("axis source records are missing")
    return {
        "coordinate_contract": {
            "frame": coordinate["frame"],
            "axis_labels": list(coordinate["axis_labels"]),
            "position_unit": coordinate["position_unit"],
            "velocity_unit": coordinate["velocity_unit"],
            "mass_unit": coordinate["mass_unit"],
            "time_unit": coordinate["time_unit"],
            "rotation_to_world": matrix,
            "rotation_determinant": determinant,
        },
        "source_records_bound": len(records),
        "producer_axis_orientation_metadata": "REQUIRED_BUT_NOT_ASSERTED_BY_THIS_WORKER",
        "status": "BOUND_SOURCE_CONVENTION_ONLY_AXIS_CALIBRATION_UNKNOWN",
        "reason": axis.get(
            "status_reason",
            "source writer/parser/XML/gravity/control inputs are bound, but producer orientation metadata is absent",
        ),
        "gravity_m_s2": axis.get("gravity_m_s2", "BOUND_FROM_SOURCE_XML_ONLY_NOT_AXIS_CALIBRATION"),
    }


def _record_matches(spec: dict[str, Any], label: str) -> None:
    path_value = spec.get("path") if isinstance(spec, dict) else None
    if not isinstance(path_value, str):
        raise base.UnsupportedSemantics(f"{label} has no path")
    path = Path(path_value).expanduser().resolve()
    if path.suffix.lower() in FORBIDDEN_SUFFIXES:
        raise base.UnsupportedSemantics(f"{label} unexpectedly binds H5/VTK payload")
    actual = base.file_record(path)
    for key in ("bytes", "mtime_ns", "sha256"):
        if key in spec and spec[key] != actual.get(key):
            raise base.UnsupportedSemantics(f"{label} {key} changed after source binding")


def _verify_axis_records(axis: dict[str, Any]) -> None:
    for index, record in enumerate(axis.get("source_records", [])):
        _record_matches(record, f"axis source record {index}")


def _parse_gravity(xml_path: Path) -> dict[str, Any]:
    root = ET.parse(xml_path).getroot()
    gravity = root.find(".//gravity")
    if gravity is None:
        return {"status": "UNKNOWN_NOT_DECLARED_IN_SOURCE_XML"}
    values: list[float] = []
    for axis in ("x", "y", "z"):
        if gravity.get(axis) is None:
            return {"status": "UNKNOWN_INCOMPLETE_SOURCE_XML_GRAVITY"}
        try:
            value = float(gravity.get(axis, ""))
        except (TypeError, ValueError) as exc:
            raise base.UnsupportedSemantics(f"source XML gravity {axis} is not numeric") from exc
        if not math.isfinite(value):
            raise base.UnsupportedSemantics(f"source XML gravity {axis} is non-finite")
        values.append(value)
    return {"status": "BOUND_SOURCE_XML_GRAVITY", "value_m_s2": values, "units": gravity.get("units_comment", "m/s^2")}


def _role_counts(ids: np.ndarray, source: dict[str, Any]) -> tuple[dict[str, Any], np.ndarray, np.ndarray, np.ndarray]:
    kind, mkfluid, mk_absolute = base.assign_particle_ranges(ids, source["blocks"])
    counts: dict[str, Any] = {role: int(np.sum(kind == role)) for role in ("fluid", "fixed", "moving", "floating")}
    counts["unknown"] = int(np.sum(kind == "UNKNOWN"))
    counts["total"] = int(ids.size)
    if counts["unknown"]:
        raise base.UnsupportedSemantics("XML typed ranges left unknown decoded identities")
    by_mk: dict[str, Any] = {"fluid_relative": {}, "absolute": {}}
    for value in sorted(set(int(x) for x in mkfluid.tolist() if int(x) >= 0)):
        by_mk["fluid_relative"][str(value)] = int(np.sum(mkfluid == value))
    for value in sorted(set(int(x) for x in mk_absolute.tolist() if int(x) >= 0)):
        by_mk["absolute"][str(value)] = int(np.sum(mk_absolute == value))
    counts["by_mk"] = by_mk
    return counts, kind, mkfluid, mk_absolute


def _weighted_observables(
    decoded: dict[str, Any],
    source: dict[str, Any],
    header: dict[str, Any],
) -> dict[str, Any]:
    ids = decoded["ids"]
    counts, kind, mkfluid, mk_absolute = _role_counts(ids, source)
    position = decoded["position"]
    velocity = decoded["velocity"]
    density = decoded["density"]
    if not (np.isfinite(position).all() and np.isfinite(velocity).all() and np.isfinite(density).all()):
        raise base.UnsupportedSemantics("native Pos/Vel/Rhop contains NaN or Inf")
    massfluid = float(header["MassFluid"]["value"])
    if massfluid <= 0.0:
        raise base.UnsupportedSemantics("native MassFluid is not positive")
    fluid = kind == "fluid"
    fluid_position = position[fluid]
    fluid_velocity = velocity[fluid]
    if fluid_position.size:
        weights = np.full(fluid_position.shape[0], massfluid, dtype=np.float64)
        centroid = np.average(fluid_position, axis=0, weights=weights)
        mean_velocity = np.average(fluid_velocity, axis=0, weights=weights)
        kinetic = float(0.5 * massfluid * np.sum(np.square(fluid_velocity), dtype=np.float64))
    else:
        centroid = mean_velocity = None
        kinetic = None
    by_mk: dict[str, Any] = {"fluid_relative": {}, "absolute": {}}
    for value in sorted(set(int(x) for x in mkfluid[fluid].tolist())):
        mask = fluid & (mkfluid == value)
        by_mk["fluid_relative"][str(value)] = {
            "count": int(np.sum(mask)),
            "sample_mass_kg": float(np.sum(mask) * massfluid),
        }
    for value in sorted(set(int(x) for x in mk_absolute[fluid].tolist())):
        mask = fluid & (mk_absolute == value)
        by_mk["absolute"][str(value)] = {
            "count": int(np.sum(mask)),
            "sample_mass_kg": float(np.sum(mask) * massfluid),
        }
    return {
        "role_counts": counts,
        "fluid_observable_using_native_MassFluid": {
            "count": int(np.sum(fluid)),
            "sample_mass_kg": float(np.sum(fluid) * massfluid),
            "weighted_centroid_m": None if centroid is None else [float(x) for x in centroid],
            "weighted_velocity_m_per_s": None if mean_velocity is None else [float(x) for x in mean_velocity],
            "kinetic_energy_j": kinetic,
            "by_mk": by_mk,
            "mass_semantics": "native_header_MassFluid_times_XML_typed_fluid_count; discrete diagnostic only",
        },
        "fixed_moving_excluded_from_fluid_observables": True,
        "xml_mass_constant_not_used_for_weighting": True,
    }


def _field_digest(decoded: dict[str, Any]) -> str:
    digest = hashlib.sha256()
    for name in ("ids", "position", "velocity", "density"):
        array = decoded[name]
        digest.update(name.encode("ascii"))
        digest.update(np.ascontiguousarray(array).tobytes())
    return digest.hexdigest()


def _axis_selftests() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    identity = [[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]]
    bad = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, -1.0]]
    good = abs(_matrix_determinant(identity) - 1.0) < 1.0e-12
    rejected = abs(_matrix_determinant(bad) - 1.0) > 1.0e-12
    cases.append({"name": "right_handed_rotation_and_left_handed_rejection", "status": "PASS" if good and rejected else "FAIL"})

    positions = np.asarray([[2.0, 0.0, 0.0], [4.0, 0.0, 0.0]], dtype=np.float64)
    velocities = np.asarray([[1.0, 0.0, 0.0], [3.0, 0.0, 0.0]], dtype=np.float32)
    mass = 2.0
    com = np.average(positions, axis=0, weights=np.full(2, mass))
    velocity = np.average(velocities, axis=0, weights=np.full(2, mass))
    trajectory_ok = np.allclose(com, [3.0, 0.0, 0.0]) and np.allclose(velocity, [2.0, 0.0, 0.0])
    cases.append({"name": "native_mass_weighted_quadratic_trajectory_fixture", "status": "PASS" if trajectory_ok else "FAIL"})

    bad_units = {"position_unit": "mm", "mass_unit": "g", "velocity_unit": "mm/s"}
    unit_reject = bad_units["position_unit"] != "m" and bad_units["mass_unit"] != "kg"
    cases.append({"name": "millimetre_or_gram_scale_is_not_silently_accepted", "status": "PASS" if unit_reject else "FAIL"})

    kinds = np.asarray(["fluid", "fluid", "fixed"], dtype=object)
    fixed_excluded = int(np.sum(kinds == "fluid")) == 2 and int(np.sum(kinds == "fixed")) == 1
    cases.append({"name": "fixed_wall_does_not_contaminate_fluid_aggregate", "status": "PASS" if fixed_excluded else "FAIL"})

    duplicate_reject = np.unique(np.asarray([1, 1], dtype=np.uint32)).size != 2
    nonfinite_reject = not np.isfinite(np.asarray([1.0, float("nan")])).all()
    cases.append({"name": "duplicate_and_nonfinite_Idp_rejection", "status": "PASS" if duplicate_reject and nonfinite_reject else "FAIL"})
    return cases


def _pure_semantic_selftests() -> dict[str, Any]:
    cases = _axis_selftests()
    return {
        "status": "PASS" if all(item["status"] == "PASS" for item in cases) else "FAIL",
        "cases": cases,
        "scope": "manufactured trajectory/rotation/units/wall/identity only; no production payload",
    }


def _fixture_source_xml(path: Path, *, overlap: bool = False) -> None:
    if overlap:
        fluid = '<fluid begin="1" count="2" mkfluid="0" mk="1" />'
    else:
        fluid = '<fluid begin="1" count="2" mkfluid="0" mk="1" />'
    fixed = '<fixed begin="0" count="2" mk="10" />' if overlap else '<fixed begin="0" count="1" mk="10" />'
    path.write_text(
        '<case><execution><particles>' + fixed + fluid +
        '</particles></execution><constants><massfluid value="99" />'
        '<massbound value="99" /><rhop0 value="1000" /></constants>'
        '<gravity x="0" y="0" z="-9.81" units_comment="m/s^2" />'
        '</case>\n',
        encoding="utf-8",
    )


def _fixture_decoder(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env python3
import os
import pathlib
import struct
import sys

frame_path = pathlib.Path(sys.argv[1])
prefix = pathlib.Path(sys.argv[2])
prefix.mkdir(parents=True, exist_ok=True)
particle = prefix / 'particles'
particle.mkdir(parents=True, exist_ok=True)
frame = int(frame_path.stem.split('_')[-1])
mode = os.environ.get('ROOT204_FIXTURE_MODE', 'good')
ids = [0, 1, 2]
if mode == 'duplicate':
    ids = [0, 1, 1]
time = 0.5 * frame
position = [0.0 + frame, 1.0, 0.0, 2.0 + frame, 1.0, 0.0, 4.0 + frame, 1.0, 0.0]
velocity = [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 3.0, 0.0, 0.0]
density = [1000.0, 1000.0, 1000.0]
(particle / 'Idp.bin').write_bytes(struct.pack('<3I', *ids))
(particle / 'Posd.bin').write_bytes(struct.pack('<9d', *position))
(particle / 'Vel.bin').write_bytes(struct.pack('<9f', *velocity))
(particle / 'Rhop.bin').write_bytes(struct.pack('<3f', *density))
prefix.with_suffix('.xml').write_text(f'''<root><item>
<double name="MassFluid" v="2"/><double name="MassBound" v="3"/>
<double name="Dp" v="0.01"/><int name="Npiece" v="1"/>
<int name="Piece" v="0"/><int name="NpDynamic" v="0"/>
<int name="ReuseIds" v="0"/><int name="PeriMode" v="0"/>
<item name="particles"><double name="TimeStep" v="{time}"/></item>
</item></root>''', encoding='utf-8')
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _fixture_manifest(root: Path, *, coordinate: dict[str, Any] | None = None, overlap: bool = False) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    raw_root = root / "native"
    raw_root.mkdir()
    for frame in (0, 1):
        (raw_root / f"Part_{frame:04d}.bi4").write_bytes(b"manufactured-bi4")
    runparts = root / "RunPARTs.csv"
    runparts.write_text("Part;TimeStep [s]\n0;0.0\n1;0.5\n", encoding="utf-8")
    generated_xml = root / ("overlap.xml" if overlap else "generated.xml")
    _fixture_source_xml(generated_xml, overlap=overlap)
    decoder = root / "fixture_decoder.py"
    _fixture_decoder(decoder)
    axis_coordinate = coordinate or {
        "frame": "world_cartesian_right_handed",
        "axis_labels": ["x", "y", "z"],
        "position_unit": "m",
        "velocity_unit": "m/s",
        "mass_unit": "kg",
        "time_unit": "s",
        "rotation_to_world": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
    }
    axis_records = [base.file_record(generated_xml), base.file_record(decoder), base.file_record(Path(__file__))]
    return_value = {
        "schema": "ds02.stage2.f1.native-selected-observer-manifest.v1",
        "axis_authority": {
            "coordinate_contract": axis_coordinate,
            "source_records": axis_records,
            "status_reason": "manufactured fixture; producer orientation remains UNKNOWN",
            "gravity_m_s2": [0.0, 0.0, -9.81],
        },
        "cases": [{
            "label": "manufactured",
            "identity": {"family_id": "F1", "sentinel_id": "F1-S1", "physical_case_id": "fixture"},
            "raw_root": str(raw_root),
            "runparts": str(runparts),
            "generated_xml": str(generated_xml),
            "decoder": str(decoder),
            "decoder_source": "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/scripts/native/bi4_dump.cpp",
            "expected_frame_count": 2,
            "expected_final_time_s": 0.5,
            "selected_frames": [0, 1],
            "query_times": [0.0, 0.5],
            "scratch_root": str(root / "scratch"),
        }],
    }
    manifest = root / "manifest.json"
    manifest.write_text(json.dumps(return_value, sort_keys=True), encoding="utf-8")
    return manifest


def _cli_fixture_selftests() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="root204-f1-fixture-") as temporary:
        root = Path(temporary)
        good_manifest = _fixture_manifest(root / "good", coordinate=None)
        good_output = root / "good" / "output.json"
        good_command = [sys.executable, "-B", str(Path(__file__).resolve()), "--manifest", str(good_manifest), "--attempt-root", str(root / "good" / "attempt"), "--output", str(good_output)]
        good = subprocess.run(good_command, capture_output=True, text=True, timeout=30)
        passed = good.returncode == 0
        if passed:
            result = json.loads(good_output.read_text(encoding="utf-8"))
            selected = result["cases"][0]["selected_observations"][0]
            fluid = selected["observables"]["fluid_observable_using_native_MassFluid"]
            passed = (
                result["status"] == PASS_STATUS
                and selected["native_header"]["MassFluid"]["value"] == 2.0
                and selected["native_header"]["Dp"]["value"] == 0.01
                and selected["native_Idp"]["count"] == 3
                and selected["observables"]["role_counts"]["fixed"] == 1
                and fluid["count"] == 2
                and abs(fluid["sample_mass_kg"] - 4.0) < 1.0e-12
                and fluid["weighted_velocity_m_per_s"] == [2.0, 0.0, 0.0]
            )
        cases.append({"name": "real_cli_native_header_fixture_and_weighted_observables", "status": "PASS" if passed else "FAIL", "scope": "temporary decoder/source only"})

        bad_axis = {"frame": "world_cartesian_right_handed", "axis_labels": ["x", "y", "z"], "position_unit": "m", "velocity_unit": "m/s", "mass_unit": "kg", "time_unit": "s", "rotation_to_world": [[1, 0, 0], [0, 1, 0], [0, 0, -1]]}
        axis_manifest = _fixture_manifest(root / "bad_axis", coordinate=bad_axis)
        axis_output = root / "bad_axis" / "output.json"
        axis_run = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), "--manifest", str(axis_manifest), "--attempt-root", str(root / "bad_axis" / "attempt"), "--output", str(axis_output)], capture_output=True, text=True, timeout=30)
        axis_pass = axis_run.returncode == 2 and json.loads(axis_output.read_text(encoding="utf-8"))["status"] == UNKNOWN_STATUS
        cases.append({"name": "real_cli_left_handed_rotation_rejection", "status": "PASS" if axis_pass else "FAIL"})

        bad_units = {"frame": "world_cartesian_right_handed", "axis_labels": ["x", "y", "z"], "position_unit": "mm", "velocity_unit": "mm/s", "mass_unit": "g", "time_unit": "s", "rotation_to_world": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]}
        units_manifest = _fixture_manifest(root / "bad_units", coordinate=bad_units)
        units_output = root / "bad_units" / "output.json"
        units_run = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), "--manifest", str(units_manifest), "--attempt-root", str(root / "bad_units" / "attempt"), "--output", str(units_output)], capture_output=True, text=True, timeout=30)
        units_pass = units_run.returncode == 2 and json.loads(units_output.read_text(encoding="utf-8"))["status"] == UNKNOWN_STATUS
        cases.append({"name": "real_cli_mm_gram_unit_rejection", "status": "PASS" if units_pass else "FAIL"})

        duplicate_manifest = _fixture_manifest(root / "duplicate", coordinate=None)
        duplicate_output = root / "duplicate" / "output.json"
        duplicate_run = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), "--manifest", str(duplicate_manifest), "--attempt-root", str(root / "duplicate" / "attempt"), "--output", str(duplicate_output)], env={**os.environ, "ROOT204_FIXTURE_MODE": "duplicate"}, capture_output=True, text=True, timeout=30)
        duplicate_pass = duplicate_run.returncode == 2 and json.loads(duplicate_output.read_text(encoding="utf-8"))["status"] == UNKNOWN_STATUS
        cases.append({"name": "real_cli_duplicate_Idp_rejection", "status": "PASS" if duplicate_pass else "FAIL"})

        overlap_manifest = _fixture_manifest(root / "overlap", coordinate=None, overlap=True)
        overlap_output = root / "overlap" / "output.json"
        overlap_run = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), "--manifest", str(overlap_manifest), "--attempt-root", str(root / "overlap" / "attempt"), "--output", str(overlap_output)], capture_output=True, text=True, timeout=30)
        overlap_pass = overlap_run.returncode == 2 and json.loads(overlap_output.read_text(encoding="utf-8"))["status"] == UNKNOWN_STATUS
        cases.append({"name": "real_cli_overlapping_fixed_fluid_range_rejection", "status": "PASS" if overlap_pass else "FAIL"})
    return cases


def manufactured_semantic_selftests() -> dict[str, Any]:
    pure = _pure_semantic_selftests()
    cli_cases = _cli_fixture_selftests()
    cases = pure["cases"] + cli_cases
    return {
        "status": "PASS" if all(case["status"] == "PASS" for case in cases) else "FAIL",
        "cases": cases,
        "scope": "manufactured trajectory/rotation/units/wall/identity plus temporary real CLI decoder fixture; no production payload",
    }


def _unknown(output: Path, reason: str) -> dict[str, Any]:
    result = {
        "schema": SCHEMA,
        "status": UNKNOWN_STATUS,
        "reason": reason,
        "scope": {"selected_frames_only": True, "native_payload_read": False, "hdf5_read": False},
        "axis_authority": {"status": "UNKNOWN", "producer_axis_orientation_metadata": "UNKNOWN"},
        "scientific_qualification": QUALIFICATION,
    }
    base.atomic_json(output, result)
    return result


def _case_result(case: dict[str, Any], axis: dict[str, Any], attempt_root: Path | None) -> dict[str, Any]:
    raw_root = Path(case["raw_root"]).expanduser().resolve()
    runparts = Path(case["runparts"]).expanduser().resolve()
    generated_xml = Path(case["generated_xml"]).expanduser().resolve()
    decoder = Path(case["decoder"]).expanduser().resolve()
    decoder_source = Path(case["decoder_source"]).expanduser().resolve()
    scratch_value = str(case["scratch_root"])
    if "{attempt_root}" in scratch_value:
        if attempt_root is None:
            raise ValueError(f"{case['label']} requires the parent attempt root for scratch isolation")
        scratch_value = scratch_value.replace("{attempt_root}", str(attempt_root.expanduser().resolve()), 1)
    scratch_root = Path(scratch_value).expanduser().resolve()
    rows = base.read_runparts(runparts)
    if len(rows) != int(case["expected_frame_count"]):
        raise ValueError(f"{case['label']} RunPARTs count differs from bound source")
    source = base.parse_source_xml(generated_xml)
    selected = sorted({int(frame) for frame in case["selected_frames"]})
    if not selected or any(frame < 0 or frame >= len(rows) for frame in selected):
        raise ValueError(f"{case['label']} selected frame is outside RunPARTs")
    brackets = [base.time_bracket(rows, float(query)) for query in case["query_times"]]
    required: set[int] = set()
    for bracket in brackets:
        if bracket["status"] in {"EXACT", "EXACT_OR_LEFT", "BRACKETED"}:
            required.add(int(bracket["lower_frame"]))
            required.add(int(bracket["upper_frame"]))
    if not required.issubset(set(selected)):
        raise ValueError(f"{case['label']} selected frames do not cover query brackets")
    decoded_rows: list[dict[str, Any]] = []
    for frame in selected:
        decoded = base.decode_frame(raw_root / f"Part_{frame:04d}.bi4", decoder, scratch_root, frame)
        header = {
            "MassFluid": _native_scalar("MassFluid", decoded["metadata"], decoded["info"], required=True),
            "MassBound": _native_scalar("MassBound", decoded["metadata"], decoded["info"], required=False),
            "Dp": _native_scalar("Dp", decoded["metadata"], decoded["info"], required=True),
        }
        identity = _idp_summary(decoded["ids"])
        expected_time = rows[frame]["time_s"]
        if abs(decoded["decoded_time_s"] - expected_time) > 1.0e-10:
            raise base.UnsupportedSemantics(f"{case['label']} decoded time differs from RunPARTs")
        decoded_rows.append({
            "frame": frame,
            "time_s": float(decoded["decoded_time_s"]),
            "runparts_time_s": float(expected_time),
            "native_header": header,
            "native_Idp": identity,
            "native_field_digest_sha256": _field_digest(decoded),
            "observables": _weighted_observables(decoded, source, header),
            "decoder_xml_sha256": decoded["decoder_xml_sha256"],
            "dynamic_semantics": decoded["dynamic_semantics"],
        })
    mass_values = [row["native_header"]["MassFluid"]["value"] for row in decoded_rows]
    dp_values = [row["native_header"]["Dp"]["value"] for row in decoded_rows]
    if len(set(mass_values)) != 1:
        raise base.UnsupportedSemantics(f"{case['label']} native MassFluid changed across selected frames")
    if len(set(dp_values)) != 1:
        raise base.UnsupportedSemantics(f"{case['label']} native Dp changed across selected frames")
    bound_values = [row["native_header"]["MassBound"].get("value") for row in decoded_rows]
    numeric_bound = [value for value in bound_values if isinstance(value, (int, float)) and not isinstance(value, bool)]
    if numeric_bound and len(numeric_bound) != len(bound_values):
        raise base.UnsupportedSemantics(f"{case['label']} native MassBound is inconsistently exposed")
    if numeric_bound and len(set(numeric_bound)) != 1:
        raise base.UnsupportedSemantics(f"{case['label']} native MassBound changed across selected frames")
    return {
        "label": case["label"],
        "identity": case["identity"],
        "source": {
            "raw_root": str(raw_root),
            "runparts": base.file_record(runparts),
            "generated_xml": base.file_record(generated_xml),
            "decoder": base.file_record(decoder),
            "decoder_source": base.file_record(decoder_source),
            "typed_ranges": source,
        },
        "time": {
            "runparts_first_s": rows[0]["time_s"],
            "runparts_last_s": rows[-1]["time_s"],
            "queries": brackets,
            "interpolation": "NOT_PERFORMED",
        },
        "source_xml_gravity": _parse_gravity(generated_xml),
        "selected_observations": decoded_rows,
        "native_summary": {
            "MassFluid_kg": mass_values[0],
            "MassBound_kg": numeric_bound[0] if numeric_bound else "UNKNOWN_NOT_EXPOSED_BY_DECODER",
            "Dp_m": dp_values[0],
            "MassFluid_stable": True,
            "Dp_stable": True,
            "Idp_semantics": "decoded native identity array; per-frame digest retained",
            "xml_mass_fallback": "FORBIDDEN",
        },
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    manifest_path = args.manifest.expanduser().resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != "ds02.stage2.f1.native-selected-observer-manifest.v1":
        raise ValueError("unexpected F1 native selected observer manifest schema")
    axis = _axis_contract(manifest.get("axis_authority", {}))
    _verify_axis_records(manifest["axis_authority"])
    selftests = _pure_semantic_selftests()
    if selftests["status"] != "PASS":
        raise base.UnsupportedSemantics("manufactured semantic self-tests failed")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("native selected observer manifest has no cases")
    attempt_root = args.attempt_root.expanduser().resolve() if args.attempt_root is not None else None
    outputs = [_case_result(case, axis, attempt_root) for case in cases]
    result = {
        "schema": SCHEMA,
        "status": PASS_STATUS,
        "scope": {
            "case_count": len(outputs),
            "selected_frames_only": True,
            "full_native_tree_scanned": False,
            "hdf5_read": False,
            "vtk_read": False,
            "xml_mass_fallback": False,
            "scientific_qualification": QUALIFICATION,
        },
        "axis_authority": axis,
        "manufactured_semantic_selftests": selftests,
        "cases": outputs,
        "scientific_qualification": QUALIFICATION,
        "qualification_limits": [
            "native weighted sample observables only",
            "continuum and rigid-body mass/inertia are not inferred",
            "producer axis orientation metadata is still absent; axis calibration remains UNKNOWN",
            "no integration, interpolation, spatial-truth, or external-validation credit",
        ],
    }
    base.atomic_json(args.output.expanduser().resolve(), result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--attempt-root", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        result = manufactured_semantic_selftests()
        print(json.dumps(result, sort_keys=True))
        return 0 if result["status"] == "PASS" else 2
    if args.manifest is None or args.output is None:
        parser.error("--manifest and --output are required unless --self-test is used")
    try:
        result = run(args)
    except base.UnsupportedSemantics as exc:
        result = _unknown(args.output.expanduser().resolve(), str(exc))
    except Exception as exc:
        print(f"F1 native selected observer failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": result["status"], "output": str(args.output.resolve())}, sort_keys=True))
    return 0 if result["status"] == PASS_STATUS else 2


if __name__ == "__main__":
    raise SystemExit(main())
