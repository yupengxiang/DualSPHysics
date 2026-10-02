#!/usr/bin/env python3
"""Audit the six completed F2 handoff GenCase artifacts at native precision.

The audit reads generated XML and the BI4 root header/array declarations.  It
uses BI4 ``MassFluid`` as an IEEE-754 value and multiplies it by the native
``CaseNfluid`` count.  PartVTK's decimal CSV is deliberately not used as the
authority for this check.  The raw BI4 files are opened read-only and never
decoded into or rewritten in the source tree.

This is an initial native-input mass/identity audit.  It does not launch a
solver, convert H5, grant Q-I/Q-N, or grant production eligibility.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal, getcontext
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
from typing import Any, Mapping


getcontext().prec = 80

SCHEMA = "ds-data-02.f2.gem-handoff-20261002.native-mass-audit.v1"
FAMILY_ID = "F2"
CONTINUOUS_VOLUME_M3 = Decimal("0.024576")
RHO0_KG_M3 = Decimal("1000")
CONTINUOUS_MASS_KG = CONTINUOUS_VOLUME_M3 * RHO0_KG_M3
MASS_BUDGET_FRACTION = Decimal("1e-12")
CASE_RESOLUTIONS = ("coarse", "medium", "fine")
BACKGROUNDS = ("center_catch", "offset_spill")
SAFE_DECODER_DEFAULT = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/scripts/f8_r008_safe_bi4_decoder_v1.py"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return decimal_string(value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"not JSON serializable: {type(value)!r}")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=_json_default) + "\n", encoding="utf-8")


def _load_safe_decoder(path: Path):
    """Load the pinned read-only BI4 scanner without importing its CLI."""
    spec = importlib.util.spec_from_file_location("ds02_f2_native_bi4_scanner", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load BI4 scanner: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    # The scanner's safety limits are designed for a small diagnostic fixture.
    # F2's completed GenCase files are closed one-piece streams with larger
    # arrays; these larger bounds still only scan metadata and never copy data.
    module.MAX_RAW_BYTES = 2**40
    module.MAX_ARRAY_COUNT = 10_000_000
    module.MAX_ARRAY_BYTES = 2**40
    module.MAX_ARRAY_BYTES_TOTAL = 2**40
    module.MAX_OUTPUT_BYTES = 2**40
    return module


def scan_native_header(path: Path, scanner: Any) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    fd = os.open(path, os.O_RDONLY)
    try:
        expected_sha = scanner._hash_fd(fd, path.stat().st_size)
        scan = scanner.scan_bi4_fd(fd, expected_sha)
    finally:
        os.close(fd)
    root_values = {item.name: item.value for item in scan.root.values}
    part = scan.root.children[0]
    part_values = {item.name: item.value for item in part.values}
    arrays = {
        item.name: {
            "type_code": item.type_code,
            "count": item.count,
            "byte_count": item.byte_count,
            "item_path": list(item.item_path),
        }
        for item in scan.arrays
        if item.item_path[-1] == part.name
    }
    return {
        "path": str(path),
        "sha256": expected_sha,
        "bytes": path.stat().st_size,
        "root_values": root_values,
        "part_values": part_values,
        "arrays": arrays,
    }


def _find(root: ET.Element, path: str) -> ET.Element:
    element = root.find(path)
    if element is None:
        raise ValueError(f"generated XML is missing {path}: {root}")
    return element


def parse_generated_xml(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    particles = _find(root, ".//execution/particles")
    constants = _find(root, ".//execution/constants")
    parameters = {
        item.get("key"): item.get("value")
        for item in root.findall(".//execution/parameters/parameter")
    }
    fluid_blocks = [
        {
            "mk": int(item.get("mk", "-1")),
            "mkfluid": int(item.get("mkfluid", "-1")),
            "begin": int(item.get("begin", "-1")),
            "count": int(item.get("count", "-1")),
        }
        for item in particles.findall("fluid")
    ]
    motion_file = root.find(".//execution/motion/mvrotfile/file")
    if motion_file is None:
        motion_file = root.find(".//execution/motion/objreal/mvrotfile/file")
    if motion_file is None:
        raise ValueError(f"generated XML is missing execution motion file: {root}")
    return {
        "path": str(path),
        "sha256": sha256(path),
        "definition_dp_m": Decimal(_find(root, ".//geometry/definition").get("dp", "0")),
        "data2d": _find(root, ".//execution/constants/data2d").get("value", ""),
        "xml_massfluid_kg": Decimal(constants.find("massfluid").get("value", "0")),
        "xml_rhop0_kg_m3": Decimal(constants.find("rhop0").get("value", "0")),
        "particles_np": int(particles.get("np", "-1")),
        "particles_nfluid": int(particles.find("_summary/fluid").get("count", "-1")),
        "fluid_blocks": fluid_blocks,
        "time_max_s": Decimal(parameters.get("TimeMax", "0")),
        "time_out_s": Decimal(parameters.get("TimeOut", "0")),
        "motion_file": motion_file.get("name"),
    }


def decimal_string(value: Decimal) -> str:
    return format(value, "f")


def _case_receipt(data_root: Path, case: Mapping[str, Any]) -> tuple[Path, Path, Path]:
    request = case["request"]
    attempt = str(request["attempt_id"])
    case_id = str(case["case_id"])
    root = data_root / case_id / attempt
    return root / "execution-receipt.json", root / f"{case_id}.xml", root / f"{case_id}.bi4"


def audit(manifest_path: Path, data_root: Path, report_path: Path, scanner_path: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    scanner = _load_safe_decoder(scanner_path)
    cases = manifest.get("cases", [])
    if len(cases) != 6:
        raise ValueError(f"expected six v2 cases, found {len(cases)}")
    observed: list[dict[str, Any]] = []
    failures: list[str] = []
    for case in cases:
        case_id = str(case["case_id"])
        receipt_path, generated_xml, bi4_path = _case_receipt(data_root, case)
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        xml = parse_generated_xml(generated_xml)
        native = scan_native_header(bi4_path, scanner)
        metadata_path = Path(case["metadata"]["path"])
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata_hash_ok = sha256(metadata_path) == case["metadata"]["sha256"]
        frozen_budget = Decimal(str(metadata["mass_error_budget_fraction"]))
        root_values = native["root_values"]
        arrays = native["arrays"]
        fluid_count = int(root_values["CaseNfluid"])
        case_np = int(root_values["CaseNp"])
        massfluid = float(root_values["MassFluid"])
        native_mass = Decimal.from_float(massfluid) * fluid_count
        abs_error = native_mass - CONTINUOUS_MASS_KG
        relative_error = abs_error / CONTINUOUS_MASS_KG
        xml_mass = xml["xml_massfluid_kg"] * xml["particles_nfluid"]
        xml_abs_error = xml_mass - CONTINUOUS_MASS_KG
        xml_relative_error = xml_abs_error / CONTINUOUS_MASS_KG
        checks = {
            "receipt_completed": receipt.get("status") == "completed" and receipt.get("returncode") == 0,
            "receipt_3d": receipt.get("solver_dimension_from_gencase") == 3,
            "receipt_fluid_matches": receipt.get("fluid_particles") == fluid_count,
            "xml_bi4_case_nfluid_match": xml["particles_nfluid"] == fluid_count,
            "xml_bi4_case_np_match": xml["particles_np"] == case_np,
            "xml_bi4_dp_match": abs(float(xml["definition_dp_m"]) - float(root_values["Dp"])) <= 1e-15,
            "xml_bi4_massfluid_match": abs(float(xml["xml_massfluid_kg"]) - massfluid) <= 1e-14,
            "native_stream_closed_static": root_values.get("Npiece") == 1 and not bool(root_values.get("NpDynamic")) and not bool(root_values.get("ReuseIds")),
            "native_3d": root_values.get("Data2d") is False and arrays.get("Posd", {}).get("type_code") == 23,
            "native_arrays_cover_case": all(arrays.get(name, {}).get("count") == case_np for name in ("Idp", "Posd", "Vel", "Rhop")),
            "typed_fluid_blocks_match": sum(item["count"] for item in xml["fluid_blocks"]) == fluid_count and [item["mk"] for item in xml["fluid_blocks"]] == [1, 2, 3],
            "complete_4s_control": xml["time_max_s"] == Decimal("4") and xml["time_out_s"] == Decimal("0.01"),
            "metadata_sha256_matches_manifest": metadata_hash_ok,
            "metadata_frozen_budget_is_1e-12": frozen_budget == MASS_BUDGET_FRACTION,
            "native_mass_within_frozen_budget": abs(relative_error) <= frozen_budget,
            "xml_mass_within_frozen_budget": abs(xml_relative_error) <= frozen_budget,
        }
        if not all(checks.values()):
            failures.extend(f"{case_id}:{key}" for key, value in checks.items() if not value)
        observed.append(
            {
                "case_id": case_id,
                "background": case["background"],
                "resolution": case["resolution"],
                "physical_case_id": case["physical_case_id"],
                "receipt": {
                    "path": str(receipt_path),
                    "sha256": sha256(receipt_path),
                    "status": receipt.get("status"),
                    "returncode": receipt.get("returncode"),
                    "pid": receipt.get("pid"),
                },
                "generated_xml": xml,
                "frozen_mass_criterion": {
                    "metadata_path": str(metadata_path),
                    "metadata_sha256": sha256(metadata_path),
                    "manifest_metadata_sha256": case["metadata"]["sha256"],
                    "metadata_sha256_matches_manifest": metadata_hash_ok,
                    "mass_error_budget_fraction": decimal_string(frozen_budget),
                },
                "native_bi4": {
                    "path": native["path"],
                    "sha256": native["sha256"],
                    "bytes": native["bytes"],
                    "root_case_np": case_np,
                    "root_case_nfluid": fluid_count,
                    "root_dp_m": root_values["Dp"],
                    "root_massfluid_kg": massfluid,
                    "root_data2d": root_values["Data2d"],
                    "arrays": arrays,
                },
                "mass_authority": {
                    "source": "BI4 root MassFluid IEEE-754 double multiplied by BI4 CaseNfluid",
                    "continuous_volume_m3": decimal_string(CONTINUOUS_VOLUME_M3),
                    "rho0_kg_m3": decimal_string(RHO0_KG_M3),
                    "continuous_mass_kg": decimal_string(CONTINUOUS_MASS_KG),
                    "native_mass_kg_exact_binary_decimal": decimal_string(native_mass),
                    "native_abs_error_kg": decimal_string(abs_error),
                    "native_relative_error": decimal_string(relative_error),
                    "xml_printed_massfluid_total_kg": decimal_string(xml_mass),
                    "xml_printed_mass_abs_error_kg": decimal_string(xml_abs_error),
                    "xml_printed_mass_relative_error": decimal_string(xml_relative_error),
                    "partvtk_csv_is_authority": False,
                },
                "checks": checks,
                "status": "PASS_NATIVE_INITIAL_MASS" if all(checks.values()) else "FAIL_NATIVE_INITIAL_MASS",
            }
        )
    report = {
        "schema": SCHEMA,
        "family_id": FAMILY_ID,
        "scope_id": manifest.get("scope_id"),
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "manifest": {"path": str(manifest_path), "sha256": sha256(manifest_path)},
        "scanner": {"path": str(scanner_path), "sha256": sha256(scanner_path)},
        "continuous_authority": {
            "volume_m3": decimal_string(CONTINUOUS_VOLUME_M3),
            "mass_kg": decimal_string(CONTINUOUS_MASS_KG),
            "mass_budget_fraction": decimal_string(MASS_BUDGET_FRACTION),
            "budget_source": "each case's frozen v2 metadata.mass_error_budget_fraction; all six metadata files must hash-match the manifest",
            "partvtk_csv_used_as_authority": False,
        },
        "cases": observed,
        "status": "PASS_NATIVE_INITIAL_MASS" if not failures else "FAIL_NATIVE_INITIAL_MASS",
        "failures": failures,
        "qualification_claim": "none",
        "production_claim": "none",
        "gpu_launch": False,
        "interpretation": "Native BI4 MassFluid/CaseNfluid and generated-XML MassFluid*CaseNfluid are checked against each case's frozen 1e-12 initial-mass budget. PartVTK decimal CSV rounding remains a separate representation diagnostic and is not used here. This report is not Q-I/Q-N and does not authorize production.",
    }
    write_json(report_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--safe-decoder", type=Path, default=SAFE_DECODER_DEFAULT)
    args = parser.parse_args()
    report = audit(args.manifest, args.data_root, args.report, args.safe_decoder)
    print(json.dumps({"status": report["status"], "report": str(args.report), "failures": report["failures"]}, indent=2))
    return 0 if report["status"] == "PASS_NATIVE_INITIAL_MASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
