#!/usr/bin/env python3
"""Run the F7 fresh075 native initial QA after Root enables the request.

The source package never invokes this worker.  Root's isolated CPU job invokes
official PartVTK, writes CSV files under its own attempt directory, and then
uses NumPy for the typed checks.  No CSV/BI4/H5 payload is read during source
preparation.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import numpy as np


FIELDS = [
    "Pos.x [m]", "Pos.y [m]", "Pos.z [m]", "Zone", "Idp", "Type", "Mk",
    "Mass [kg]", "Vel.x [m/s]", "Vel.y [m/s]", "Vel.z [m/s]",
    "Rhop [kg/m^3]", "Press [Pa]",
]
RAW_SUFFIXES = {".bi4", ".csv", ".h5", ".hdf5", ".dat", ".ibi4"}


class QAError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise QAError(message)


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"JSON object required: {path}")
    return value


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def export_csv(case: dict[str, Any], output_dir: Path, partvtk: str) -> tuple[np.ndarray, dict[str, Any]]:
    bi4 = Path(case["generated_bi4"])
    xml = Path(case["generated_xml"])
    csv_path = output_dir / f"{case['case_id']}-initial-all.csv"
    require(not csv_path.exists(), f"refusing to overwrite CSV: {csv_path}")
    before = sha(bi4)
    command = [
        partvtk, "-filedata", str(bi4), "-filexml", str(xml), "-threads:2",
        "-savecsv", str(csv_path), "-onlytype:+all",
        "-vars:-all,+idp,+vel,+rhop,+press,+type,+mk,+mass,+zone", "-csvsep:1",
    ]
    subprocess.run(command, cwd=str(output_dir), check=True)
    require(sha(bi4) == before, f"{case['case_id']}: PartVTK changed BI4")
    require(csv_path.is_file(), f"{case['case_id']}: PartVTK CSV missing")
    with csv_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    header_index = next(
        (index for index, row in enumerate(rows) if "Pos.x [m]" in row), None
    )
    require(header_index is not None, f"{case['case_id']}: official CSV header missing")
    header = rows[header_index]
    indices = [header.index(field) for field in FIELDS]
    data = rows[header_index + 1 :]
    while data and not any(cell.strip() for cell in data[-1]):
        data.pop()
    require(all(any(cell.strip() for cell in row) for row in data),
            f"{case['case_id']}: empty row inside official CSV")
    expected = case["expected"]["total_particles"]
    require(len(data) == expected,
            f"{case['case_id']}: CSV rows {len(data)} != {expected}")
    values = np.asarray(
        [[float(row[index]) for index in indices] for row in data], dtype=float
    )
    require(values.shape == (expected, len(FIELDS)),
            f"{case['case_id']}: CSV shape {values.shape} is not ({expected}, 13)")
    return values, {
        "official_csv": str(csv_path),
        "official_csv_sha256": sha(csv_path),
        "initial_bi4_sha256": before,
        "csv_header_index": header_index,
        "partvtk_command": command,
    }


def check_xml(case: dict[str, Any]) -> dict[str, Any]:
    path = Path(case["generated_xml"])
    root = ET.parse(path).getroot()
    constants = root.find("./execution/constants")
    particles = root.find("./execution/particles")
    definition = root.find("./casedef/geometry/definition")
    require(constants is not None and particles is not None and definition is not None,
            f"{case['case_id']}: generated XML sections missing")
    data2d = constants.find("data2d")
    require(data2d is not None and data2d.get("value") == "false",
            f"{case['case_id']}: generated XML is not 3D")
    params = {
        node.get("key"): node.get("value")
        for node in root.findall("./execution/parameters/parameter")
    }
    require(definition.get("dp") == "0.02" and params.get("TimeMax") == "12" and
            params.get("TimeOut") == "0.02",
            f"{case['case_id']}: native recipe changed")
    blocks: dict[str, dict[str, int]] = {}
    for block in case["expected"]["type_mk_blocks"]:
        node = particles.find(block["name"])
        if node is None:
            require(block["count"] == 0,
                    f"{case['case_id']}: missing nonzero {block['name']} block")
            continue
        observed = {
            "begin": int(node.get("begin", "-1")),
            "count": int(node.get("count", "-1")),
            "type": int(block["type"]),
            "mk": int(node.get("mk", "-1")),
        }
        expected = {key: int(block[key]) for key in ("begin", "count", "type", "mk")}
        require(observed == expected,
                f"{case['case_id']}: XML {block['name']} block {observed} != {expected}")
        blocks[block["name"]] = observed
    require(int(particles.get("np", "-1")) == case["expected"]["total_particles"],
            f"{case['case_id']}: XML total mismatch")
    return {
        "xml_contract": True,
        "xml_sha256": sha(path),
        "native_type_mk_blocks": blocks,
        "floating_node_present": particles.find("floating") is not None,
    }


def check_rows(case: dict[str, Any], values: np.ndarray) -> dict[str, Any]:
    expected = case["expected"]
    require(bool(np.isfinite(values).all()), f"{case['case_id']}: nonfinite native field")
    require(bool(np.equal(values[:, 3:7], np.floor(values[:, 3:7])).all()),
            f"{case['case_id']}: categorical field is not integral")
    zone = values[:, 3].astype(np.int64)
    uid = values[:, 4].astype(np.int64)
    types = values[:, 5].astype(np.int64)
    mks = values[:, 6].astype(np.int64)
    require(bool(np.equal(zone, 0).all()), f"{case['case_id']}: nonzero zone")
    require(bool(np.array_equal(np.sort(uid), np.arange(expected["total_particles"]))),
            f"{case['case_id']}: UID set/loss mismatch")
    order = np.argsort(uid, kind="stable")
    values = values[order]
    types = types[order]
    mks = mks[order]

    named_sets: dict[str, set[tuple[float, float, float]]] = {}
    block_checks: dict[str, Any] = {}
    for block in expected["type_mk_blocks"]:
        start = int(block["begin"])
        stop = start + int(block["count"])
        segment = slice(start, stop)
        require(bool(np.equal(types[segment], int(block["type"])).all()),
                f"{case['case_id']}: {block['name']} Type mismatch")
        require(bool(np.equal(mks[segment], int(block["mk"])).all()),
                f"{case['case_id']}: {block['name']} Mk mismatch")
        named_sets[block["name"]] = {tuple(row) for row in values[segment, :3]}
        block_checks[block["name"]] = {
            "count": int(block["count"]), "type": int(block["type"]),
            "mk": int(block["mk"]), "uid_range_exact": True,
        }

    require(bool(np.all(values[:, 7] > 0)),
            f"{case['case_id']}: nonpositive native weights")
    require(bool(np.all(values[:, 11] > 0)),
            f"{case['case_id']}: nonpositive native density")
    require(float(np.max(np.abs(values[:, 8:11]))) <=
            float(expected["velocity_zero_tolerance_m_per_s"]),
            f"{case['case_id']}: initial velocity exceeds strict tolerance")
    coordinates = values[:, :3]
    require(np.unique(coordinates, axis=0).shape[0] == len(values),
            f"{case['case_id']}: duplicate initial coordinates")
    overlap = {
        "fixed_moving": len(named_sets.get("fixed", set()) & named_sets.get("moving", set())),
        "fixed_floating": len(named_sets.get("fixed", set()) & named_sets.get("floating", set())),
        "fixed_fluid": len(named_sets.get("fixed", set()) & named_sets.get("fluid", set())),
        "moving_floating": len(named_sets.get("moving", set()) & named_sets.get("floating", set())),
        "moving_fluid": len(named_sets.get("moving", set()) & named_sets.get("fluid", set())),
        "floating_fluid": len(named_sets.get("floating", set()) & named_sets.get("fluid", set())),
    }
    require(all(count == 0 for count in overlap.values()),
            f"{case['case_id']}: initial block overlap {overlap}")
    fluid = types == 3
    require(int(fluid.sum()) == int(expected["fluid_particles"]),
            f"{case['case_id']}: fluid count mismatch")
    fluid_coordinates = coordinates[fluid]
    require(all(np.unique(fluid_coordinates[:, axis]).size > 1 for axis in range(3)),
            f"{case['case_id']}: fluid is not genuinely 3D")
    native_mass = float(values[fluid, 7].sum())
    require(np.isfinite(native_mass) and abs(native_mass -
            float(expected["native_fluid_mass_kg"])) <=
            float(expected["mass_tolerance_kg"]),
            f"{case['case_id']}: native mass {native_mass} differs from registered mass")
    return {
        "row_shape_exact": True,
        "all_13_fields_finite": True,
        "uid_exact_sorted_unique": True,
        "native_type_mk_blocks": block_checks,
        "all_native_weights_positive": True,
        "all_native_densities_positive": True,
        "initial_velocity_zero_within_tolerance": True,
        "global_coordinate_unique": True,
        "pairwise_initial_overlap_counts": overlap,
        "no_initial_overlap": True,
        "fluid_count_exact": True,
        "actual_3d": True,
        "actual_fluid_envelope_m": [
            fluid_coordinates.min(axis=0).tolist(),
            fluid_coordinates.max(axis=0).tolist(),
        ],
        "official_CSV_fluid_mass_sum_kg": native_mass,
        "registered_native_fluid_mass_kg": expected["native_fluid_mass_kg"],
        "continuum_envelope_mass_kg": expected["continuum_envelope_mass_kg"],
        "mass_policy": "native unscaled; continuum comparison separately reported; no rescale",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    binding = load(args.binding)
    require(binding.get("schema") ==
            "ds02.f7.fresh075.actual-gencase-native-qa-binding.v1",
            "fresh075 binding schema mismatch")
    require(binding.get("launch_allowed") is False and
            binding.get("execution_allowed") is False,
            "fresh075 binding unexpectedly enabled")
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    results = []
    for case in binding["cases"]:
        for key in ("gencase_receipt", "prepared_input_report", "generated_xml",
                    "generated_bi4", "generated_definition", "generated_motion"):
            require(Path(case[key]).is_file(), f"{case['case_id']}: missing {key}")
        receipt = load(Path(case["gencase_receipt"]))
        require(receipt.get("status") == "completed" and receipt.get("returncode") == 0,
                f"{case['case_id']}: GenCase receipt is not completed/0")
        xml_checks = check_xml(case)
        values, provenance = export_csv(case, output, binding["partvtk"])
        row_checks = check_rows(case, values)
        results.append({
            "case_id": case["case_id"],
            "physical_condition_sha256": case["physical_condition_sha256"],
            "canonical_physical_binding_sha256": case["canonical_physical_binding_sha256"],
            "native_particles": int(values.shape[0]),
            "checks": {**xml_checks, **provenance, **row_checks},
            "passed": True,
        })
    report = {
        "schema": "ds02.f7.fresh075.actual-native-initial-qa.v1",
        "scope_id": binding["scope_id"],
        "binding": str(args.binding),
        "binding_sha256": sha(args.binding),
        "cases": results,
        "all_cases_passed": True,
        "independent_case_count_increment": 0,
        "q_n": "not_granted",
        "production_approval": "none",
        "precision_status": "not_accepted",
        "visual_acceptance": "not_assessed",
        "claim_boundary": (
            "Native initial UID/type/Mk/positive-field/zero-velocity/unique-"
            "coordinate/no-overlap/3D/mass QA only; no full12 dynamics, visual, "
            "Q-N, precision, or production claim."
        ),
    }
    (output / "native-initial-qa.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except QAError as exc:
        raise SystemExit(f"fresh075 native initial QA failed: {exc}") from exc
