#!/usr/bin/env python3
"""Root-owned pre-solver GenCase basic initial QA.

This worker is deliberately independent of a native solver receipt.  Root may
enable it only after reviewing the individual completed GenCase evidence in
the binding.  The registered CPU job reads the attested GenCase BI4 through
the frozen safe decoder and checks the actual initial UID/count/3-D/source
partition.  It also checks inclusive XML drawbox extrema, drop/pool
separation, tank containment, and source/recipe invariants.

The source package never opens or hashes BI4.  The future Root-owned worker
does that read-only through the registered decoder, using the producer
attestation as the expected digest.  Initial velocities are reported from
the generated XML declaration only; saved native-frame velocity remains a
separate post-solver audit.  Mass is diagnostic and is never a gate.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import mmap
import os
from pathlib import Path
import sys
from typing import Any
import xml.etree.ElementTree as ET

import numpy as np

RAW_SUFFIXES = {".bi4", ".h5", ".vtk", ".vtu", ".vtp", ".csv"}
HEX = set("0123456789abcdef")
SCHEMA = "ds02.f4.fresh095.gencase-basic-initial-qa.v1"
DECODER_REGISTERED_SHA = "affbbb6c04a4d21d03037e74d0023112c60c7d8e5972cc6dfc882e1c7c5dc319"
PARTVTK_REGISTERED_SHA = "b8ac8cf4aff68ffd089da6cf3ef19dfd0c6473121475f4c198b720a0ddaa8b2e"
TOL = 1e-8


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def dump_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(path)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha_static(path: Path) -> str:
    path = Path(path)
    if path.suffix.lower() in RAW_SUFFIXES:
        raise ValueError(f"source package refuses scientific-payload hash: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def valid_sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value.lower()) <= HEX


def require_file(path: Path) -> Path:
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def canonical_xml(element: ET.Element | None) -> tuple[Any, ...] | None:
    if element is None:
        return None
    return (
        element.tag,
        tuple(sorted(element.attrib.items())),
        tuple(canonical_xml(child) for child in element),
    )


def load_decoder(path: Path):
    if path.suffix.lower() in RAW_SUFFIXES:
        raise ValueError("decoder path cannot be a scientific payload")
    if sha_static(path) != DECODER_REGISTERED_SHA:
        raise ValueError("registered safe decoder SHA drift")
    spec = importlib.util.spec_from_file_location("ds02_f4_fresh095_safe_decoder", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import decoder: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.MAX_RAW_BYTES = 2**40
    module.MAX_ARRAY_COUNT = 10_000_000
    module.MAX_ARRAY_BYTES = 2**40
    module.MAX_ARRAY_BYTES_TOTAL = 2**40
    module.MAX_OUTPUT_BYTES = 2**40
    return module


def parse_xml(binding: dict[str, Any]) -> dict[str, Any]:
    xml_ref = binding["generated_xml"]
    xml_path = require_file(Path(xml_ref["path"]))
    if sha_static(xml_path) != xml_ref["sha256"]:
        raise ValueError("generated XML SHA changed")
    root = ET.parse(xml_path).getroot()
    particles = root.find(".//execution/particles")
    if particles is None:
        raise ValueError("generated XML lacks execution/particles")
    total = int(particles.attrib["np"])
    fixed = int(particles.attrib["nb"])
    fluid_blocks = []
    for element in particles.findall("fluid"):
        fluid_blocks.append(
            {
                "mkfluid": int(element.attrib["mkfluid"]),
                "mk": int(element.attrib["mk"]),
                "begin": int(element.attrib["begin"]),
                "count": int(element.attrib["count"]),
            }
        )
    fluid = sum(row["count"] for row in fluid_blocks)
    expected = binding["expected"]
    if (total, fixed, fluid) != (
        int(expected["total_particles"]),
        int(expected["fixed_particles"]),
        int(expected["fluid_particles"]),
    ):
        raise ValueError("generated XML counts differ from actual GenCase evidence")
    if total != fixed + fluid or total <= 0 or fixed <= 0 or fluid <= 0:
        raise ValueError("generated XML particle partition does not close")
    data2d = root.find(".//execution/constants/data2d")
    if data2d is None:
        data2d = root.find(".//data2d")
    if data2d is None or str(data2d.attrib.get("value", "")).lower() != "false":
        raise ValueError("generated XML is not explicit true 3-D")
    parameters = {
        item.attrib.get("key"): item.attrib.get("value")
        for item in root.findall(".//execution/parameters/parameter")
    }
    if parameters.get("TimeMax") != "1.2" or parameters.get("TimeOut") != "0.001":
        raise ValueError("generated XML time recipe drift")
    definition = root.find(".//geometry/definition")
    if definition is None or abs(float(definition.attrib["dp"]) - float(expected["dp_m"])) > 1e-12:
        raise ValueError("generated XML dp drift")
    by_mkfluid = {row["mkfluid"]: row for row in fluid_blocks}
    source_rows: dict[str, Any] = {}
    for name in ("drop", "pool"):
        source = expected["sources"][name]
        mkfluid = int(source["mkfluid"])
        if mkfluid not in by_mkfluid:
            raise ValueError(f"generated XML lacks {name} mkfluid={mkfluid}")
        row = by_mkfluid[mkfluid]
        source_rows[name] = {**source, "xml_block": row}
    if sum(int(row["xml_block"]["count"]) for row in source_rows.values()) != fluid:
        raise ValueError("source UID blocks do not close over fluid count")
    velocities = []
    for element in root.findall(".//initials/velocity"):
        velocities.append(
            {
                key: element.attrib[key]
                for key in ("mkfluid", "x", "y", "z")
                if key in element.attrib
            }
        )
    return {
        "path": str(xml_path),
        "sha256": xml_ref["sha256"],
        "root": root,
        "counts": {"total": total, "fixed": fixed, "fluid": fluid},
        "fluid_blocks": fluid_blocks,
        "sources": source_rows,
        "velocities": velocities,
        "parameters": parameters,
    }


def verify_static_invariants(binding: dict[str, Any], xml: dict[str, Any]) -> dict[str, Any]:
    source_ref = binding["source_definition"]
    source_path = require_file(Path(source_ref["path"]))
    if sha_static(source_path) != source_ref["sha256"]:
        raise ValueError("source Definition SHA changed")
    source_root = ET.parse(source_path).getroot()
    generated_root = xml["root"]
    same_constants = canonical_xml(source_root.find("casedef/constantsdef")) == canonical_xml(
        generated_root.find("casedef/constantsdef")
    )
    same_initials = canonical_xml(source_root.find("casedef/initials")) == canonical_xml(
        generated_root.find("casedef/initials")
    )
    source_params = {
        x.attrib.get("key"): x.attrib.get("value")
        for x in source_root.findall("./execution/parameters/parameter")
    }
    generated_params = {
        x.attrib.get("key"): x.attrib.get("value")
        for x in generated_root.findall("./execution/parameters/parameter")
    }
    same_parameters = source_params == generated_params
    same_geometry_definition = canonical_xml(
        source_root.find("casedef/geometry/definition")
    ) == canonical_xml(generated_root.find("casedef/geometry/definition"))
    same_geometry_commands = canonical_xml(
        source_root.find("casedef/geometry/commands/mainlist")
    ) == canonical_xml(generated_root.find("casedef/geometry/commands/mainlist"))
    report_ref = binding["prepared_report"]
    report_path = require_file(Path(report_ref["path"]))
    report = load_json(report_path)
    if sha_static(report_path) != report_ref["sha256"]:
        raise ValueError("prepared GenCase report SHA changed")
    receipt_ref = binding["gencase_receipt"]
    receipt_path = require_file(Path(receipt_ref["path"]))
    receipt = load_json(receipt_path)
    if sha_static(receipt_path) != receipt_ref["sha256"]:
        raise ValueError("GenCase receipt SHA changed")
    if receipt.get("status") not in {"completed", "completed/0"} or receipt.get("returncode") != 0:
        raise ValueError("GenCase receipt is not completed/0")
    if receipt.get("solver_dimension_from_gencase") != 3:
        raise ValueError("GenCase receipt is not actual 3-D")
    if report.get("actual_total_particles") not in {None, int(binding["expected"]["total_particles"])}:
        raise ValueError("prepared report total differs from binding")
    actual_data2d = report.get("actual_generated_constants", {}).get("data2d", {}).get("value")
    if actual_data2d not in {None, False, "false"}:
        raise ValueError("prepared report is not explicit 3-D")
    source_invariants = {
        "same_constants": same_constants,
        "same_initials": same_initials,
        "same_execution_parameters": same_parameters,
        "same_geometry_definition": same_geometry_definition,
        "same_geometry_commands": same_geometry_commands,
    }
    if not all(source_invariants.values()):
        raise ValueError("generated XML/Definition source invariants differ")
    return {
        "source_definition_sha256": source_ref["sha256"],
        "gencase_receipt_sha256": receipt_ref["sha256"],
        "prepared_report_sha256": report_ref["sha256"],
        **source_invariants,
        "source_bytes_unchanged": True,
        "raw_receipt_unchanged": True,
        "prepared_report_actual_total": report.get("actual_total_particles"),
        "prepared_report_actual_data2d": actual_data2d,
    }


def source_checks(binding: dict[str, Any], xml: dict[str, Any]) -> dict[str, Any]:
    expected = binding["expected"]
    source_rows = xml["sources"]
    actual_bounds: dict[str, Any] = {}
    for name, source in source_rows.items():
        low = np.asarray(source["low_m"], dtype=float)
        high = low + np.asarray(source["size_m"], dtype=float)
        actual_bounds[name] = {
            "declared_low_m": low.tolist(),
            "declared_high_m": high.tolist(),
            "size_m": np.asarray(source["size_m"], dtype=float).tolist(),
        }
    drop_low = np.asarray(actual_bounds["drop"]["declared_low_m"], dtype=float)
    drop_high = np.asarray(actual_bounds["drop"]["declared_high_m"], dtype=float)
    pool_low = np.asarray(actual_bounds["pool"]["declared_low_m"], dtype=float)
    pool_high = np.asarray(actual_bounds["pool"]["declared_high_m"], dtype=float)
    separations = [
        ("x", max(float(pool_low[0] - drop_high[0]), float(drop_low[0] - pool_high[0]))),
        ("y", max(float(pool_low[1] - drop_high[1]), float(drop_low[1] - pool_high[1]))),
        ("z", max(float(pool_low[2] - drop_high[2]), float(drop_low[2] - pool_high[2]))),
    ]
    gap_axis, declared_gap = max(separations, key=lambda item: item[1])
    tank = expected["tank"]
    tank_low = np.asarray(tank["low_m"], dtype=float)
    tank_high = tank_low + np.asarray(tank["size_m"], dtype=float)
    inside = all(
        bool(
            np.all(np.asarray(actual_bounds[name]["declared_low_m"]) >= tank_low - TOL)
            and np.all(np.asarray(actual_bounds[name]["declared_high_m"]) <= tank_high + TOL)
        )
        for name in ("drop", "pool")
    )
    return {
        "declared_source_bounds_inside_tank": inside,
        "declared_drop_pool_separation": {
            "axis": gap_axis,
            "surface_gap_m": float(declared_gap),
            "positive": bool(declared_gap > TOL),
        },
        "declared_source_bounds": actual_bounds,
        "mass_policy": "diagnostic only; no continuum mass or exact lattice gate",
        "declared_velocity_only": True,
        "declared_initial_velocities": xml["velocities"],
        "native_frame0_velocity_audit": {
            "status": "deferred until post-solver fresh094",
            "pass": None,
            "report": None,
            "sha256": None,
        },
    }


def actual_gencase_audit(
    binding: dict[str, Any],
    xml: dict[str, Any],
    decoder_path: Path,
) -> dict[str, Any]:
    bi4_ref = binding["generated_bi4"]
    bi4_path = require_file(Path(bi4_ref["path"]))
    if not valid_sha(bi4_ref["producer_sha256"]):
        raise ValueError("GenCase BI4 producer attestation is missing")
    if binding["reader"]["partvtk_binary"]["registered_sha256"] != PARTVTK_REGISTERED_SHA:
        raise ValueError("registered PartVTK reader SHA drift")
    decoder = load_decoder(decoder_path)
    flags = getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(bi4_path, os.O_RDONLY | flags)
    before_stat = os.fstat(fd)
    mapped = None
    try:
        scan = decoder.scan_bi4_fd(fd, bi4_ref["producer_sha256"])
        root_values = {item.name: item.value for item in scan.root.values}
        if not scan.root.children:
            raise ValueError("GenCase BI4 lacks particle item")
        particle_name = scan.root.children[0].name
        arrays = {
            item.name: item
            for item in scan.arrays
            if item.item_path[-1] == particle_name
        }
        for name in ("Posd", "Idp"):
            if name not in arrays:
                raise ValueError(f"GenCase BI4 lacks required {name} array")
        expected = binding["expected"]
        total_expected = int(expected["total_particles"])
        fixed_expected = int(expected["fixed_particles"])
        fluid_expected = int(expected["fluid_particles"])
        if int(root_values.get("CaseNp", -1)) != total_expected:
            raise ValueError("GenCase BI4 CaseNp differs from actual receipt")
        if int(root_values.get("CaseNfluid", -1)) != fluid_expected:
            raise ValueError("GenCase BI4 CaseNfluid differs from actual receipt")
        if int(root_values.get("CaseNfixed", -1)) != fixed_expected:
            raise ValueError("GenCase BI4 CaseNfixed differs from actual receipt")
        if root_values.get("Data2d") is not False:
            raise ValueError("GenCase BI4 is not true 3-D")
        pos_record = arrays["Posd"]
        id_record = arrays["Idp"]
        if pos_record.type_code != 23 or pos_record.count != total_expected or id_record.count != total_expected:
            raise ValueError("GenCase BI4 Posd/Idp shape does not match actual counts")
        mapped = mmap.mmap(fd, 0, access=mmap.ACCESS_READ)
        pos = np.ndarray(
            (total_expected, 3),
            dtype=np.dtype("<f8"),
            buffer=mapped,
            offset=pos_record.offset,
        )
        ids = np.ndarray(
            (total_expected,),
            dtype=np.dtype(decoder.TYPE_INFO[id_record.type_code][1]),
            buffer=mapped,
            offset=id_record.offset,
        )
        ids_i64 = ids.astype(np.int64, copy=False)
        finite = bool(np.isfinite(pos).all())
        unique_complete = bool(
            np.array_equal(np.sort(ids_i64), np.arange(total_expected, dtype=np.int64))
        )
        fluid_mask = ids_i64 >= fixed_expected
        fluid_positions = pos[fluid_mask]
        all_axes_levels = [
            int(np.unique(fluid_positions[:, axis]).size) > 1
            for axis in range(3)
        ]
        source_rows: dict[str, Any] = {}
        for name in ("drop", "pool"):
            source = xml["sources"][name]
            block = source["xml_block"]
            mask = (ids_i64 >= int(block["begin"])) & (
                ids_i64 < int(block["begin"] + block["count"])
            )
            cloud = pos[mask]
            if cloud.shape[0] != int(block["count"]):
                raise ValueError(f"{name} source UID count differs from XML")
            declared_low = np.asarray(source["low_m"], dtype=float)
            declared_high = declared_low + np.asarray(source["size_m"], dtype=float)
            actual_low = np.min(cloud, axis=0)
            actual_high = np.max(cloud, axis=0)
            source_rows[name] = {
                "uid_begin": int(block["begin"]),
                "uid_end_exclusive": int(block["begin"] + block["count"]),
                "uid_count": int(cloud.shape[0]),
                "declared_inclusive_bounds_m": [
                    declared_low.tolist(),
                    declared_high.tolist(),
                ],
                "actual_inclusive_bounds_m": [
                    actual_low.tolist(),
                    actual_high.tolist(),
                ],
                "checks": {
                    "exact_xml_uid_block": int(cloud.shape[0]) == int(block["count"]),
                    "finite_positions": bool(np.isfinite(cloud).all()),
                    "inside_declared_drawbox_inclusive": bool(
                        np.all(actual_low >= declared_low - TOL)
                        and np.all(actual_high <= declared_high + TOL)
                    ),
                    "declared_drawbox_inclusive_extrema_match": bool(
                        np.allclose(actual_low, declared_low, rtol=0.0, atol=TOL)
                        and np.allclose(actual_high, declared_high, rtol=0.0, atol=TOL)
                    ),
                    "positive_population": bool(cloud.shape[0] > 0),
                },
            }
        drop_low, drop_high = (
            np.asarray(source_rows["drop"]["actual_inclusive_bounds_m"][i], dtype=float)
            for i in (0, 1)
        )
        pool_low, pool_high = (
            np.asarray(source_rows["pool"]["actual_inclusive_bounds_m"][i], dtype=float)
            for i in (0, 1)
        )
        separations = [
            ("x", max(float(pool_low[0] - drop_high[0]), float(drop_low[0] - pool_high[0]))),
            ("y", max(float(pool_low[1] - drop_high[1]), float(drop_low[1] - pool_high[1]))),
            ("z", max(float(pool_low[2] - drop_high[2]), float(drop_low[2] - pool_high[2]))),
        ]
        gap_axis, measured_gap = max(separations, key=lambda item: item[1])
        tank = expected["tank"]
        tank_low = np.asarray(tank["low_m"], dtype=float)
        tank_high = tank_low + np.asarray(tank["size_m"], dtype=float)
        inside_tank = bool(
            np.all(drop_low >= tank_low - TOL)
            and np.all(drop_high <= tank_high + TOL)
            and np.all(pool_low >= tank_low - TOL)
            and np.all(pool_high <= tank_high + TOL)
        )
        fixed_fluid_partition = bool(
            np.sum(ids_i64 < fixed_expected) == fixed_expected
            and np.sum(ids_i64 >= fixed_expected) == fluid_expected
        )
        nominal_mass = {
            name: float(
                np.prod(np.asarray(expected["sources"][name]["size_m"], dtype=float))
                * float(expected["density_kg_m3"])
            )
            for name in ("drop", "pool")
        }
        massfluid = root_values.get("MassFluid")
        native_mass = (
            None
            if massfluid is None
            else {
                name: float(source_rows[name]["uid_count"] * float(massfluid))
                for name in ("drop", "pool")
            }
        )
        checks = {
            "gencase_receipt_completed0": True,
            "actual_3d": root_values.get("Data2d") is False and pos_record.type_code == 23,
            "finite_positions": finite,
            "unique_complete_initial_uid": unique_complete,
            "exact_actual_total_count": int(root_values["CaseNp"]) == total_expected,
            "exact_actual_fixed_count": int(root_values["CaseNfixed"]) == fixed_expected,
            "exact_actual_fluid_count": int(root_values["CaseNfluid"]) == fluid_expected,
            "fixed_fluid_type_partition": fixed_fluid_partition,
            "source_uid_blocks_exact": all(
                row["checks"]["exact_xml_uid_block"] for row in source_rows.values()
            ),
            "all_fluid_axes_have_multiple_levels": all(all_axes_levels),
            "declared_xml_extrema_match_actual": all(
                row["checks"]["declared_drawbox_inclusive_extrema_match"]
                for row in source_rows.values()
            ),
            "drop_pool_nonoverlap": bool(measured_gap >= -TOL),
            "gap_inside_tank": bool(measured_gap > TOL and inside_tank),
            "source_definition_and_recipe_unchanged": True,
        }
        after_stat = os.fstat(fd)
        input_identity_unchanged = (
            before_stat.st_dev, before_stat.st_ino, before_stat.st_size, before_stat.st_mtime_ns, before_stat.st_ctime_ns
        ) == (
            after_stat.st_dev, after_stat.st_ino, after_stat.st_size, after_stat.st_mtime_ns, after_stat.st_ctime_ns
        )
        if not input_identity_unchanged:
            raise ValueError("GenCase BI4 identity changed during read-only audit")
        return {
            "gencase_bi4_producer_sha256_verified_by_registered_job": True,
            "gencase_bi4_read_only": True,
            "gencase_bi4_identity_unchanged": input_identity_unchanged,
            "root_values": {
                key: root_values.get(key)
                for key in ("CaseNp", "CaseNfixed", "CaseNfluid", "Data2d", "Dp", "MassFluid")
            },
            "array_contract": {
                name: {
                    "type_code": arrays[name].type_code,
                    "count": arrays[name].count,
                    "offset": arrays[name].offset,
                    "byte_count": arrays[name].byte_count,
                }
                for name in ("Posd", "Idp")
            },
            "source_rows": source_rows,
            "all_fluid_axes_have_multiple_levels": all_axes_levels,
            "gap": {
                "axis": gap_axis,
                "measured_inclusive_surface_gap_m": float(measured_gap),
                "declared_source_gap_m": float(expected["parameters"]["gap_m"]),
                "interpretation": "Measured GenCase inclusive extrema are reported separately from the source parameter.",
            },
            "inside_tank": inside_tank,
            "mass": {
                "native_mass_by_source_kg": native_mass,
                "nominal_continuum_mass_by_source_kg": nominal_mass,
                "mass_rescaled": False,
                "is_stage1_gate": False,
                "status": "diagnostic_only",
            },
            "raw_mk_type_observed": False,
            "derived_type_partition": "XML fluid/fixed blocks plus initial Idp ranges",
            "checks": checks,
            "pass": all(checks.values()),
            "arrays_observed_by_registered_job": ["Posd", "Idp"],
            "saved_frame0_velocity_audit": {
                "status": "deferred_until_native_solver",
                "pass": None,
                "report": None,
                "sha256": None,
            },
        }
    finally:
        if mapped is not None:
            mapped.close()
        os.close(fd)


def run(args: argparse.Namespace) -> int:
    binding = load_json(require_file(args.binding))
    if binding.get("schema") != "ds02.f4.fresh095.gencase-basic-input-binding.v1":
        raise ValueError("fresh095 binding schema mismatch")
    if binding.get("source_only") is not True or binding.get("execution_allowed") is not False:
        raise ValueError("fresh095 worker must remain source-only disabled")
    xml = parse_xml(binding)
    invariant = verify_static_invariants(binding, xml)
    source = source_checks(binding, xml)
    result = actual_gencase_audit(
        binding,
        xml,
        Path(binding["decoder"]["path"]),
    )
    report = {
        "schema": SCHEMA,
        "case_id": binding["case_id"],
        "physical_case_id": binding["physical_case_id"],
        "physical_condition_sha256": binding["physical_condition_sha256"],
        "status": "completed",
        "returncode": 0,
        "gencase": {
            "execution_receipt": binding["gencase_receipt"],
            "prepared_report": binding["prepared_report"],
            "generated_xml": binding["generated_xml"],
            "generated_bi4": {
                "path": binding["generated_bi4"]["path"],
                "producer_sha256": binding["generated_bi4"]["producer_sha256"],
                "read_by_source": False,
            },
        },
        "static_invariants": invariant,
        "source_contract": source,
        "audit": result,
        "precision_status": "not_accepted",
        "q_n_status": "not_assessed",
        "production_approval": "none",
        "independent_case_count_increment": 0,
        "arrays_read_by_source": False,
        "claim_boundary": (
            "Pre-solver GenCase basic initial QA only. Initial velocity is an XML "
            "declaration; native frame-0 velocity remains a separate downstream "
            "audit. Mass, exact continuum lattice/center, precision, Q-N, solver, "
            "visual, and production approval are not granted."
        ),
    }
    dump_json(args.output, report)
    return 0 if result["pass"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        return run(args)
    except Exception as error:
        print(
            json.dumps(
                {
                    "schema": SCHEMA,
                    "status": "failed",
                    "error_type": type(error).__name__,
                    "error": str(error),
                    "gencase_parent_receipt_preserved": True,
                    "arrays_read_by_source": False,
                },
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
