#!/usr/bin/env python3
"""Prepare an explicit rigid-contract dp=.025 F6 GenCase mother.

The first additive dp=.025 GenCase run is retained under
``commensurate_dp025``.  Its fluid and wall counts passed, but the generated
XML derived the floating center/inertia from the rasterized solid cloud.  This
new scope keeps those bytes immutable and inserts the already validated
RIGID003 explicit center and diagonal inertia into fresh Definition XML files.
Only bounded CPU GenCase requests are produced and executed through the
shared runner; no solver or GPU is launched here.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
V26 = SCRIPT.with_name("ds_data02_f6_handoff_20261002_v26.py")
SPEC = importlib.util.spec_from_file_location("f6_handoff_dp025_v26_base", V26)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load dp025 mother generator: {V26}")
BASE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BASE)
MODULE = BASE.MODULE

FAMILY_ROOT = MODULE.REPO_ROOT / "campaigns/ds-data-02/families/F6/handoff_20261002/commensurate_dp025_rigid003"
VERSION = "ds_data02_f6_handoff_20261002.commensurate_dp025_rigid003.v1"
SCHEMA = "ds-data-02.f6.handoff-20261002.commensurate_dp025_rigid003.v1"
DP_LABEL = "dp025"
DP_M = 0.025
RIGID_CENTER = [2.4, 1.2, 1.08]
RIGID_INERTIA = [8.533333333333335, 8.533333333333335, 13.653333333333336]

# All wrapped v1/v5 functions resolve their module-level names dynamically.
MODULE.FAMILY_ROOT = FAMILY_ROOT
MODULE.SCRIPT = SCRIPT
MODULE.VERSION = VERSION
MODULE.SCHEMA = SCHEMA
MODULE.DP_LADDER = ((DP_LABEL, DP_M),)
BASE.BASE = getattr(BASE, "BASE", BASE)
if hasattr(BASE, "BASE"):
    BASE.BASE.SCRIPT = SCRIPT
BASE.SCRIPT = SCRIPT

_base_mechanisms = MODULE.MECHANISMS
MODULE.MECHANISMS = {
    mechanism: {
        **spec,
        "case_prefix": spec["case_prefix"].replace("_COMMENSURATE", "_COMMENSURATE_RIGID003"),
        "physical_case_id": spec["physical_case_id"] + "_RIGID003",
        "geometry_family_id": spec["geometry_family_id"] + "_RIGID003",
    }
    for mechanism, spec in _base_mechanisms.items()
}

_base_request_input_files = MODULE._request_input_files


def _request_input_files(*paths: Path) -> list[str]:
    values = _base_request_input_files(*paths)
    for path in (V26, BASE.V5 if hasattr(BASE, "V5") else V26):
        value = str(Path(path).resolve())
        if value not in values:
            values.append(value)
    return values


MODULE._request_input_files = _request_input_files

_base_native_json = MODULE._native_json


def _native_json(path: Path, mechanism: str, resolution: str, dp: float) -> dict[str, Any]:
    record = _base_native_json(path, mechanism, resolution, dp)
    payload = MODULE.read_json(path)
    payload["rigid_contract_003_dp025_scope"] = {
        "mother_id": "F6_HANDOFF_20261002_COMMENSURATE_DP025_RIGID003",
        "spatial_resolution_m": DP_M,
        "explicit_center_m": RIGID_CENTER,
        "explicit_inertia_kg_m2": [[RIGID_INERTIA[0], 0.0, 0.0], [0.0, RIGID_INERTIA[1], 0.0], [0.0, 0.0, RIGID_INERTIA[2]]],
        "aggregate_massbody_kg": 128.0,
        "floatingtype": 2,
        "strict_fluid_mass_kg": 5120.0,
        "same_continuous_geometry_and_control": True,
        "source_negative_evidence": "commensurate_dp025 generated XML without explicit rigid contract",
        "no_mass_rescaling": True,
        "old_dp025_outputs_immutable": True,
    }
    payload["rigid_body"]["initial_pose"]["center_m"] = RIGID_CENTER
    payload["rigid_body"]["source_inertia_kg_m2"] = [[RIGID_INERTIA[0], 0.0, 0.0], [0.0, RIGID_INERTIA[1], 0.0], [0.0, 0.0, RIGID_INERTIA[2]]]
    MODULE.write_json(path, payload)
    return {"path": str(path.resolve()), "sha256": MODULE.sha256(path)}


MODULE._native_json = _native_json

_base_definition_xml = MODULE._definition_xml


def _definition_xml(mechanism: str, resolution: str, dp: float) -> str:
    xml = _base_definition_xml(mechanism, resolution, dp)
    pattern = re.compile(
        r'(<floating mkbound="50">\s*<massbody value="[^"]+" />)'
        r'(\s*<translationDOF)',
        re.DOTALL,
    )
    insertion = (
        f'<center x="{MODULE.fmt(RIGID_CENTER[0])}" y="{MODULE.fmt(RIGID_CENTER[1])}" '
        f'z="{MODULE.fmt(RIGID_CENTER[2])}" units_comment="metres (m); frozen physical center" />\n'
        f'                <inertia x="{MODULE.fmt(RIGID_INERTIA[0])}" y="{MODULE.fmt(RIGID_INERTIA[1])}" '
        f'z="{MODULE.fmt(RIGID_INERTIA[2])}" units_comment="kg*m^2; frozen physical inertia" />'
    )
    repaired, count = pattern.subn(rf"\g<1>\n                {insertion}\g<2>", xml, count=1)
    if count != 1:
        raise ValueError("dp025 RIGID003 floating contract insertion point not found")
    return repaired.replace(
        "Dense dp025 mother direct solid drawbox: measured GenCase lattice span; continuous physical faces remain frozen.",
        "Dense dp025 RIGID003 direct solid drawbox: lattice span and explicit native rigid center/inertia; continuous physical faces remain frozen.",
    )


MODULE._definition_xml = _definition_xml


def _scope_record(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": SCHEMA + ".scope",
        "family_id": "F6",
        "generator_version": VERSION,
        "scope_id": "F6_HANDOFF_20261002_COMMENSURATE_DP025_RIGID003",
        "status": "cpu_gencase_pending",
        "gpu_launch": False,
        "solver_launch": False,
        "source_negative_evidence": {
            "prior_scope": str((MODULE.REPO_ROOT / "campaigns/ds-data-02/families/F6/handoff_20261002/commensurate_dp025/scope.json").resolve()),
            "prior_issue": "GenCase rasterized floating body gave center z=1.075 m and inertia [9.17333,9.17333,14.5067] without explicit Def contract",
            "prior_outputs_immutable": True,
        },
        "frozen_physical_contract": {
            "fluid_low_m": MODULE.FLUID["low"],
            "fluid_size_m": MODULE.FLUID["size"],
            "fluid_volume_m3": MODULE.continuous_fluid_volume(),
            "fluid_mass_kg": MODULE.continuous_fluid_volume() * MODULE.RHO_WATER,
            "finite_walls": ["bottom", "left", "right", "front", "back"],
            "body": MODULE.BODY,
            "floatingtype": 2,
            "aggregate_massbody_kg": 128.0,
            "center_m": RIGID_CENTER,
            "inertia_diag_kg_m2": RIGID_INERTIA,
            "initial_submerged_body_volume_m3": MODULE.initial_submerged_body_volume(),
            "same_geometry_and_control_as_dp025": True,
        },
        "discrete_contract": {
            "dp_m": DP_M,
            "expected_fluid_particles": MODULE.expected_fluid_particles(DP_M),
            "expected_transverse_layers": round(MODULE.FLUID["size"][1] / DP_M),
            "expected_fluid_mass_kg": MODULE.expected_fluid_particles(DP_M) * DP_M**3 * MODULE.RHO_WATER,
            "explicit_center_and_inertia_in_definition": True,
        },
        "case_count": len(manifest.get("cases", [])),
        "case_ids": [case["case_id"] for case in manifest.get("cases", [])],
        "manifest_sha256_after_write": MODULE.sha256(FAMILY_ROOT / "manifest.json"),
        "physical_geometry_sha256": MODULE.sha256(FAMILY_ROOT / "physical_mother_geometry.json"),
    }


def prepare() -> dict[str, Any]:
    manifest = MODULE.prepare()
    manifest["status"] = "fresh_dp025_rigid003_cpu_gencase_pending"
    manifest["scope_id"] = "F6_HANDOFF_20261002_COMMENSURATE_DP025_RIGID003"
    manifest["history_boundary"] = {
        "new_rigid_contract_scope": True,
        "prior_dp025_outputs_immutable": True,
        "prior_commensurate_mother_immutable": True,
        "old_domain_xy_repair_02_immutable": True,
        "reason": "explicit generated XML rigid center/inertia are required before any solver request",
    }
    MODULE.write_json(FAMILY_ROOT / "manifest.json", manifest)
    scope = _scope_record(manifest)
    MODULE.write_json(FAMILY_ROOT / "scope.json", scope)
    return {"manifest": manifest, "scope": scope}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare"])
    args = parser.parse_args()
    result = prepare() if args.action == "prepare" else None
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
