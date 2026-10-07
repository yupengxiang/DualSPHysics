#!/usr/bin/env python3
"""Build the two F6 angular-velocity endpoint Definitions.

The builder is deliberately source-only.  It reads the accepted coarse
Definition, changes only the three numerical attributes on the one
``casedef/floatings/floating/angularvelini`` element, and writes two genuine
GenCase ``*_Def.xml`` inputs.  It never invokes GenCase, PartVTK, a solver,
conversion, or any data exporter.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

BASE_OMEGA = (0.08, 0.12, 0.06)
ENDPOINTS = (
    {
        "endpoint_id": "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S025_DP025",
        "scale": 0.25,
        "omega": (0.02, 0.03, 0.015),
        "role": "angular_velocity_endpoint_low",
    },
    {
        "endpoint_id": "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S200_DP025",
        "scale": 2.0,
        "omega": (0.16, 0.24, 0.12),
        "role": "angular_velocity_endpoint_high",
    },
)

MOTHER = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003/"
    "prospective_angular_release_001/cases/coarse/F6_ANGULAR_RELEASE_DP025_Def.xml"
)
MOTHER_SHA256 = "9a052a620be27668ca5b8f42b0b91f2280a5b85588a94ccf845fb46905d258ba"
SCHEMA = "ds02.f6.omega-scale-source-builder-receipt.v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def expected_xml_checks(root: ET.Element, omega: tuple[float, float, float]) -> dict[str, Any]:
    definition = root.find(".//geometry/definition")
    params = {node.get("key"): node.get("value") for node in root.findall(".//execution/parameters/parameter")}
    floating = root.find(".//casedef/floatings/floating")
    if definition is None or floating is None:
        raise ValueError("mother Definition lacks geometry or floating source")
    angular = floating.find("angularvelini")
    center = floating.find("center")
    inertia = floating.find("inertia")
    massbody = floating.find("massbody")
    tdof = floating.find("translationDOF")
    rdof = floating.find("rotationDOF")
    if any(node is None for node in (angular, center, inertia, massbody, tdof, rdof)):
        raise ValueError("mother Definition lacks required floating fields")
    actual_omega = [float(angular.get(axis, "nan")) for axis in ("x", "y", "z")]
    checks = {
        "dp_m": float(definition.get("dp", "nan")),
        "time_max_s": float(params.get("TimeMax", "nan")),
        "time_out_s": float(params.get("TimeOut", "nan")),
        "angularvelini_rad_s": actual_omega,
        "angularvelini_matches_endpoint": all(abs(a - b) <= 1e-12 for a, b in zip(actual_omega, omega)),
        "center_m": [float(center.get(axis, "nan")) for axis in ("x", "y", "z")],
        "inertia_kg_m2": [float(inertia.get(axis, "nan")) for axis in ("x", "y", "z")],
        "massbody_kg": float(massbody.get("value", "nan")),
        "translation_dof": [int(tdof.get(axis, "-1")) for axis in ("x", "y", "z")],
        "rotation_dof": [int(rdof.get(axis, "-1")) for axis in ("x", "y", "z")],
    }
    if checks["dp_m"] != 0.025 or checks["time_max_s"] != 12.0 or checks["time_out_s"] != 0.05:
        raise ValueError(f"mother numerical recipe changed unexpectedly: {checks}")
    if checks["massbody_kg"] != 128.0 or checks["center_m"] != [2.4, 1.2, 1.08]:
        raise ValueError(f"mother physical rigid fields changed unexpectedly: {checks}")
    if checks["translation_dof"] != [1, 1, 1] or checks["rotation_dof"] != [1, 1, 1]:
        raise ValueError(f"mother is not free 6DOF: {checks}")
    return checks


def only_angularvelini_changed(mother: str, candidate: str) -> bool:
    old = mother.splitlines(keepends=True)
    new = candidate.splitlines(keepends=True)
    if len(old) != len(new):
        return False
    changed = [index for index, (left, right) in enumerate(zip(old, new), 1) if left != right]
    if changed != [64]:
        return False
    # The source line is intentionally the only edit.  XML parsing below
    # independently verifies that its numerical values are the requested ones.
    return (
        old[63].startswith("                <angularvelini ")
        and new[63].startswith("                <angularvelini ")
        and 'units_comment="rad/s; finite 3D angular release excitation"' in new[63]
    )


def build(source_root: Path, output_dir: Path, receipt_path: Path) -> int:
    mother = source_root
    if mother != MOTHER:
        # A root reviewer may supply an equivalent path only if it is the
        # anchored file; its digest remains the authority.
        observed = sha256(mother)
        if observed != MOTHER_SHA256:
            raise RuntimeError(f"mother Definition digest mismatch: {observed}")
    if not mother.is_file():
        raise FileNotFoundError(mother)
    if sha256(mother) != MOTHER_SHA256:
        raise RuntimeError("anchored mother Definition changed")
    mother_text = mother.read_text(encoding="utf-8")
    if mother_text.count("<angularvelini ") != 1:
        raise ValueError("expected exactly one casedef angularvelini in mother")
    mother_root = ET.fromstring(mother_text)
    # Validate the frozen recipe before writing either endpoint.
    expected_xml_checks(mother_root, BASE_OMEGA)

    output_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    for endpoint in ENDPOINTS:
        omega = tuple(float(value) for value in endpoint["omega"])
        if tuple(round(endpoint["scale"] * value, 12) for value in BASE_OMEGA) != omega:
            raise ValueError(f"endpoint is not scale*baseline: {endpoint}")
        values = [f"{value:g}" for value in omega]
        replacement = (
            f'                <angularvelini x="{values[0]}" y="{values[1]}" '
            f'z="{values[2]}" units_comment="rad/s; finite 3D angular release excitation" />\n'
        )
        candidate_text, replacements = re.subn(
            r'(?m)^                <angularvelini x="0\.08" y="0\.12" z="0\.06" '
            r'units_comment="rad/s; finite 3D angular release excitation" />\n',
            replacement,
            mother_text,
        )
        if replacements != 1 or not only_angularvelini_changed(mother_text, candidate_text):
            raise RuntimeError(f"candidate contains a non-angular source edit: {endpoint['endpoint_id']}")
        candidate_root = ET.fromstring(candidate_text)
        checks = expected_xml_checks(candidate_root, omega)
        if not checks["angularvelini_matches_endpoint"]:
            raise RuntimeError(f"candidate angular velocity mismatch: {endpoint['endpoint_id']}")
        output = output_dir / f"{endpoint['endpoint_id']}_Def.xml"
        output.write_text(candidate_text, encoding="utf-8")
        condition = {
            "family_id": "F6",
            "physical_case_id": endpoint["endpoint_id"],
            "source_mother": "F6_ANGULAR_RELEASE_DP025",
            "angular_velocity_scale_s": endpoint["scale"],
            "angular_velocity_rad_s": list(omega),
            "orientation_quaternion": [1.0, 0.0, 0.0, 0.0],
            "linear_velocity_m_s": [0.0, 0.0, 0.0],
            "center_m": [2.4, 1.2, 1.08],
            "body_geometry_m": {"low": [2.0, 0.8, 0.88], "size": [0.8, 0.8, 0.4]},
            "physical_mass_kg": 128.0,
            "native_support_mass_kg": 256.0,
            "dp_m": 0.025,
            "time_max_s": 12.0,
            "time_out_s": 0.05,
            "changed_source_paths": ["casedef.floatings.floating.angularvelini.@x", "casedef.floatings.floating.angularvelini.@y", "casedef.floatings.floating.angularvelini.@z"],
            "mass_policy": "physical 128 kg and native support 256 kg remain distinct; no rescale",
        }
        condition_bytes = json.dumps(condition, sort_keys=True, separators=(",", ":")).encode("utf-8")
        records.append(
            {
                "endpoint_id": endpoint["endpoint_id"],
                "role": endpoint["role"],
                "angular_velocity_scale_s": endpoint["scale"],
                "angular_velocity_rad_s": list(omega),
                "source_definition_output": str(output),
                "source_definition_sha256": sha256(output),
                "source_definition_bytes": output.stat().st_size,
                "source_changed_line_numbers": [64],
                "source_changed_paths": condition["changed_source_paths"],
                "physical_condition": condition,
                "physical_condition_sha256": hashlib.sha256(condition_bytes).hexdigest(),
                "xml_recipe_checks": checks,
                "gencase_executed": False,
                "bi4_written": False,
            }
        )

    receipt = {
        "schema": SCHEMA,
        "family_id": "F6",
        "scope_id": "root_followup_063_stage1_omega_scale_endpoints_v1",
        "status": "source_built_only",
        "source_mother": str(mother),
        "source_mother_sha256": MOTHER_SHA256,
        "base_angular_velocity_rad_s": list(BASE_OMEGA),
        "endpoint_count": len(records),
        "endpoints": records,
        "execution_policy": {
            "gencase": "not invoked by builder; Root strict request only",
            "bi4": "never copied or cloned",
            "partvtk": "not invoked by builder",
            "csv": "not generated",
            "arrays": "not generated",
            "solver": "not invoked",
            "h5": "not read or written",
            "rendering": "not invoked",
        },
        "launch_allowed": False,
        "independent_case_count_increment": 0,
    }
    dump(receipt_path, receipt)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mother", type=Path, default=MOTHER)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    return build(args.mother, args.output_dir, args.receipt)


if __name__ == "__main__":
    raise SystemExit(main())
