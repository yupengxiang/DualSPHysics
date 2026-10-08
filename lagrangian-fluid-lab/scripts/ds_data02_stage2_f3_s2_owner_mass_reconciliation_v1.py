#!/usr/bin/env python3
"""Reconcile the F3-S2 continuous-owner and three-grid sample masses.

This is a source/XML/JSON audit.  It deliberately does not open VTK, BI4, or
HDF5 payloads.  The corrected ROOT086 source-clone report is the authority for
the continuous owner contract; the historical ROOT081 three-grid report is
used only for its already recorded grid mass and acceleration-control joins.
The generated particle sum remains a discrete initialization diagnostic and
does not grant QI/QN/QE.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any
import xml.etree.ElementTree as ET


SCHEMA = "ds02.stage2.f3.s2.owner-mass-reconciliation.v1"
PHYSICAL_CASE_ID = "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT"
OWNER_LOW_M = [-0.45, -0.09, 0.0]
OWNER_SIZE_M = [0.9, 0.18, 0.09]
OWNER_VOLUME_M3 = 0.01458
OWNER_DENSITY_KG_M3 = 1000.0
OWNER_MASS_KG = 14.58
SOURCE_XML_SHA256 = "1162322010c42b9a084d76db0e20de571111cb009eb3afb699f2ee4c17d37406"
SOURCE_CONTROL_SHA256 = "9a776c1c02aeeb779902964953cd51b2af1f8ab41905398bb5125a44b93e6989"
ROOT081_SHA256 = "3a882f545b4393f1d56863c54a6057871c31ba44e5db64a9a01cea7f343c64c0"
ROOT086_REPORT_SHA256 = "5b1e0c3d3526dd48ad5b1bcf7934011cd5ec926ab8713d5ee324e9fea43be202"
ROOT086_RECEIPT_SHA256 = "68ce1e593c568941af8ffadcf37949a1a53714f2e9b99f203b715ed47931e14f"
ROOT086_XML_SHA256 = "3ae2aae572b0fc8cb0687e0590b0fb1762af61212d037da603d4bc8326a8ae9d"
MASS_TOLERANCE_KG = 1e-12


class AuditError(ValueError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise AuditError(f"missing input: {path}")
    stat = path.stat()
    return {
        "path": str(path), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns,
        "ctime_ns": stat.st_ctime_ns, "st_dev": stat.st_dev, "st_ino": stat.st_ino,
        "sha256": sha256(path),
    }


def require_file(value: str | Path, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise AuditError(f"{label} is not a regular file: {path}")
    return path


def write_new(path: Path, value: Any) -> None:
    path = Path(path).expanduser().resolve()
    if path.exists():
        raise FileExistsError(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def local(node: ET.Element) -> str:
    return node.tag.rsplit("}", 1)[-1]


def first(root: ET.Element, name: str, label: str) -> ET.Element:
    for node in root.iter():
        if local(node) == name:
            return node
    raise AuditError(f"{label} has no <{name}>")


def number(value: str | None, label: str) -> float:
    if value is None:
        raise AuditError(f"{label} has no number")
    try:
        result = float(value)
    except ValueError as exc:
        raise AuditError(f"{label} is not numeric: {value!r}") from exc
    if not math.isfinite(result):
        raise AuditError(f"{label} is not finite")
    return result


def canonical(node: ET.Element) -> tuple[Any, ...]:
    return (local(node), tuple(sorted(node.attrib.items())), (node.text or "").strip(),
            tuple(canonical(child) for child in list(node)))


def xml_projection(path: Path, label: str) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    case = first(root, "casedef", label)
    definition = first(case, "definition", label)
    particles = first(root, "particles", label)
    massfluid = first(root, "massfluid", label)
    counts: dict[str, int] = {}
    for child in list(particles):
        if local(child) in {"fixed", "fluid", "floating", "moving"} and child.get("count") is not None:
            counts[local(child)] = counts.get(local(child), 0) + int(child.get("count"))
    return {
        "casedef": canonical(case),
        "dp_m": number(definition.get("dp"), f"{label}.dp"),
        "counts": counts,
        "massfluid_kg": number(massfluid.get("value"), f"{label}.massfluid"),
        "sample_fluid_mass_kg": counts.get("fluid", 0) * number(massfluid.get("value"), f"{label}.massfluid"),
    }


def classify_grid_mass(sample_mass_kg: float, owner_mass_kg: float, old_gate: str) -> dict[str, Any]:
    error = sample_mass_kg / owner_mass_kg - 1.0
    if abs(error) <= 0.01:
        status = "PASS_DISCRETE_SAMPLE_MASS_MATCHES_OWNER_DIAGNOSTIC_ONLY"
    elif abs(error) <= 0.02:
        status = "MARGINAL_DISCRETE_SAMPLE_MASS_DIAGNOSTIC_ONLY"
    else:
        status = "HARDFAIL_DISCRETE_SAMPLE_MASS_OVER_TWO_PERCENT"
    return {
        "sample_mass_kg": sample_mass_kg,
        "continuous_owner_mass_kg": owner_mass_kg,
        "relative_error_vs_continuous_owner_fraction": error,
        "relative_error_vs_continuous_owner_percent": error * 100.0,
        "historical_discrete_gate": old_gate,
        "mass_status": status,
        "mass_rescale": False,
        "interpretation": "particle sample diagnostic; not continuum or dynamics credit",
    }


def audit(manifest_path: Path, output_path: Path) -> dict[str, Any]:
    manifest_path = require_file(manifest_path, "manifest")
    manifest_pre = record(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != "ds02.stage2.f3.s2.owner-mass-reconciliation.manifest.v1":
        raise AuditError("unexpected F3 owner-mass manifest schema")
    paths: dict[str, Path] = {"manifest": manifest_path}
    for key, label in (
        ("source_xml", "corrected source XML"), ("source_control", "source control"),
        ("prepared_report", "prepared source report"), ("root081_report", "ROOT081 support report"),
        ("root086_report", "ROOT086 source-clone report"), ("root086_receipt", "ROOT086 execution receipt"),
        ("root086_generated_xml", "ROOT086 generated XML"),
    ):
        paths[key] = require_file(manifest["inputs"][key]["path"], label)
    pre = {key: record(path) for key, path in paths.items()}
    if pre["manifest"] != manifest_pre:
        raise AuditError("manifest changed before static audit")
    for key, expected in (
        ("source_xml", SOURCE_XML_SHA256), ("source_control", SOURCE_CONTROL_SHA256),
        ("root081_report", ROOT081_SHA256), ("root086_report", ROOT086_REPORT_SHA256),
        ("root086_receipt", ROOT086_RECEIPT_SHA256), ("root086_generated_xml", ROOT086_XML_SHA256),
    ):
        if pre[key]["sha256"] != expected:
            raise AuditError(f"{key} SHA does not match reviewed source")
    source = xml_projection(paths["source_xml"], "corrected source XML")
    generated = xml_projection(paths["root086_generated_xml"], "ROOT086 generated XML")
    root081 = json.loads(paths["root081_report"].read_text(encoding="utf-8"))
    root086 = json.loads(paths["root086_report"].read_text(encoding="utf-8"))
    receipt = json.loads(paths["root086_receipt"].read_text(encoding="utf-8"))
    if root081.get("physical_case_id") != PHYSICAL_CASE_ID or root086.get("physical_case_id") != PHYSICAL_CASE_ID:
        raise AuditError("source reports have different physical case identities")
    if root086.get("status") != "completed_source_clone_gencase" or receipt.get("status") != "completed":
        raise AuditError("ROOT086 source clone is not a completed GenCase producer")
    binding = root086.get("source_binding") or {}
    if binding.get("xml", {}).get("sha256") != SOURCE_XML_SHA256 or binding.get("control", {}).get("sha256") != SOURCE_CONTROL_SHA256:
        raise AuditError("ROOT086 source binding differs from corrected S2 source")
    owner = root086.get("continuous_owner") or {}
    if owner.get("low_m") != OWNER_LOW_M or owner.get("size_m") != OWNER_SIZE_M:
        raise AuditError("ROOT086 continuous owner geometry mismatch")
    if abs(float(owner.get("volume_m3", -1)) - OWNER_VOLUME_M3) > MASS_TOLERANCE_KG / OWNER_DENSITY_KG_M3:
        raise AuditError("ROOT086 continuous owner volume mismatch")
    if abs(float(owner.get("mass_kg", -1)) - OWNER_MASS_KG) > MASS_TOLERANCE_KG:
        raise AuditError("ROOT086 continuous owner mass mismatch")
    if source["casedef"] != generated["casedef"]:
        raise AuditError("ROOT086 generated XML casedef differs from corrected source")
    if abs(generated["sample_fluid_mass_kg"] - OWNER_MASS_KG) > MASS_TOLERANCE_KG:
        raise AuditError("ROOT086 corrected dp006 sample mass does not match owner mass")
    if generated["counts"] != {"fixed": 111708, "fluid": 67500} or abs(generated["dp_m"] - 0.006) > 0.0:
        raise AuditError("ROOT086 corrected generated counts/dp mismatch")
    cases = root081.get("cases") or {}
    expected_cases = {"original_dp006", "coarse_dp0075", "fine_dp0048"}
    if set(cases) != expected_cases:
        raise AuditError("ROOT081 three-grid case set changed")
    control_match = root081.get("forcing_control_comparison", {}).get("case_matches_s2_reference") or {}
    grid_rows: dict[str, Any] = {}
    for key in ("original_dp006", "coarse_dp0075", "fine_dp0048"):
        mass = cases[key].get("mass_audit") or {}
        grid_rows[key] = {
            "role": cases[key].get("role"),
            "sample_mass": classify_grid_mass(
                float(mass["sample_mass_kg"]), OWNER_MASS_KG, str(mass.get("discrete_sample_gate"))
            ),
            "s2_control_matches": bool(control_match.get(key, False)),
            "historical_continuous_owner_field": mass.get("continuous_owner_mass_kg"),
            "scientific_scope": "mass/source diagnostic only; no QI/QN/QE or physical fate",
        }
    post = {key: record(path) for key, path in paths.items()}
    if pre != post:
        raise AuditError("static source changed during reconciliation")
    report = {
        "schema": SCHEMA,
        "status": "COMPLETED_F3_S2_OWNER_MASS_RECONCILIATION",
        "physical_case_id": PHYSICAL_CASE_ID,
        "input_stability": {"pre": pre, "post": post, "all_equal": pre == post},
        "continuous_owner": {
            "source_authority": "ROOT086 completed source-clone report",
            "low_m": OWNER_LOW_M, "size_m": OWNER_SIZE_M,
            "volume_m3": OWNER_VOLUME_M3, "density_kg_m3": OWNER_DENSITY_KG_M3,
            "mass_kg": OWNER_MASS_KG,
            "sample_sum_is_not_continuum_definition": True,
        },
        "matched_s2_dp006": {
            "source_xml_sha256": SOURCE_XML_SHA256,
            "source_control_sha256": SOURCE_CONTROL_SHA256,
            "generated_xml_sha256": ROOT086_XML_SHA256,
            "dp_m": generated["dp_m"], "fluid_count": generated["counts"]["fluid"],
            "sample_mass_kg": generated["sample_fluid_mass_kg"],
            "sample_vs_owner_relative_error_fraction": generated["sample_fluid_mass_kg"] / OWNER_MASS_KG - 1.0,
            "status": "PASS_SAMPLE_MASS_EQUALS_CONTINUOUS_OWNER_DIAGNOSTIC_ONLY",
        },
        "historical_root081_three_grid": grid_rows,
        "interpretation": {
            "fine_2p958_percent_hardfail_preserved": grid_rows["fine_dp0048"]["sample_mass"]["mass_status"].startswith("HARDFAIL"),
            "original_control_not_s2": grid_rows["original_dp006"]["s2_control_matches"] is False,
            "coarse_and_fine_control_s2_match": grid_rows["coarse_dp0075"]["s2_control_matches"] and grid_rows["fine_dp0048"]["s2_control_matches"],
            "no_mass_rescale": True,
            "physical_fate": "UNKNOWN",
            "dynamics": "UNKNOWN",
            "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
        },
        "scope": {"xml_json_only": True, "vtk_opened": False, "bi4_opened": False,
                  "hdf5_opened": False, "solver_started": False, "gencase_started": False,
                  "old_products_modified": False},
    }
    write_new(output_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        report = audit(Path(args.manifest), Path(args.output))
    except Exception as exc:
        print(f"F3 owner mass reconciliation failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"schema": report["schema"], "status": report["status"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
