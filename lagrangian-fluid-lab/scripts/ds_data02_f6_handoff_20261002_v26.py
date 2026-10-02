#!/usr/bin/env python3
"""Register the additive F6 dp=.025 spatial mother and CPU GenCase requests.

This is a new numerical scope after the coarse/medium/fine native comparison
remained above the frozen macro budget.  It reuses the frozen continuous
4.0 x 1.6 x 0.8 m fluid box, finite tank, wave control, and 128 kg floating
body contract from the commensurate cell-centre generator, but writes all
inputs under a new ``commensurate_dp025`` directory.  It only prepares the
two CPU GenCase requests; it never launches GenCase, a solver, or a GPU job.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
V5 = SCRIPT.with_name("ds_data02_f6_handoff_20261002_v5.py")
SPEC = importlib.util.spec_from_file_location("f6_handoff_commensurate_dp025_base", V5)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load commensurate mother generator: {V5}")
BASE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BASE)
MODULE = BASE.MODULE

FAMILY_ROOT = MODULE.REPO_ROOT / "campaigns/ds-data-02/families/F6/handoff_20261002/commensurate_dp025"
VERSION = "ds_data02_f6_handoff_20261002.commensurate_dp025.v1"
SCHEMA = "ds-data-02.f6.handoff-20261002.commensurate_dp025.v1"
DP_LABEL = "dp025"
DP_M = 0.025

# The wrapped v1 functions resolve these names from their defining modules.
MODULE.FAMILY_ROOT = FAMILY_ROOT
MODULE.SCRIPT = SCRIPT
MODULE.VERSION = VERSION
MODULE.SCHEMA = SCHEMA
MODULE.DP_LADDER = ((DP_LABEL, DP_M),)
BASE.SCRIPT = SCRIPT

_base_mechanisms = MODULE.MECHANISMS
MODULE.MECHANISMS = {
    mechanism: {
        **spec,
        "case_prefix": spec["case_prefix"],
        "physical_case_id": spec["physical_case_id"] + "_DP025",
        "geometry_family_id": spec["geometry_family_id"] + "_DP025",
    }
    for mechanism, spec in _base_mechanisms.items()
}

_base_native_json = MODULE._native_json


def _native_json(path: Path, mechanism: str, resolution: str, dp: float) -> dict[str, Any]:
    record = _base_native_json(path, mechanism, resolution, dp)
    payload = MODULE.read_json(path)
    payload["dense_dp025_scope"] = {
        "mother_id": "F6_HANDOFF_20261002_COMMENSURATE_DP025",
        "spatial_resolution_m": DP_M,
        "source_negative_evidence": "postprocessing_008 six-case macro comparison remained above the frozen 5 percent budget",
        "same_continuous_geometry": True,
        "same_control_and_rigid_contract": True,
        "strict_fluid_mass_kg": 5120.0,
        "aggregate_massbody_kg": 128.0,
        "floatingtype": 2,
        "analytic_inertia_kg_m2": MODULE.body_inertia(),
        "cell_centre_population": True,
        "no_mass_rescaling": True,
        "old_mothers_immutable": True,
    }
    MODULE.write_json(path, payload)
    return {"path": str(path.resolve()), "sha256": MODULE.sha256(path)}


MODULE._native_json = _native_json

_base_definition_xml = MODULE._definition_xml


def _definition_xml(mechanism: str, resolution: str, dp: float) -> str:
    xml = _base_definition_xml(mechanism, resolution, dp)
    return xml.replace(
        "Commensurate mother direct solid drawbox: measured GenCase lattice span; continuous physical faces remain frozen.",
        "Dense dp025 mother direct solid drawbox: measured GenCase lattice span; continuous physical faces remain frozen.",
    )


MODULE._definition_xml = _definition_xml


def _scope_record(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": SCHEMA + ".scope",
        "family_id": "F6",
        "generator_version": VERSION,
        "scope_id": "F6_HANDOFF_20261002_COMMENSURATE_DP025",
        "status": "cpu_gencase_pending",
        "gpu_launch": False,
        "solver_launch": False,
        "source_negative_evidence": {
            "comparison": str((MODULE.REPO_ROOT / "campaigns/ds-data-02/families/F6/handoff_20261002/rigid_contract_003/domain_xy_repair_02/postprocessing_008/six_case_macro_comparison_001.json").resolve()),
            "macro_budget_relative": 0.05,
            "event_budget_relative": 0.02,
            "interpretation": "old coarse/medium/fine rows remain descriptive evidence; this scope is not a qualification result",
        },
        "frozen_physical_contract": {
            "fluid_low_m": MODULE.FLUID["low"],
            "fluid_size_m": MODULE.FLUID["size"],
            "fluid_volume_m3": MODULE.continuous_fluid_volume(),
            "fluid_mass_kg": MODULE.continuous_fluid_volume() * MODULE.RHO_WATER,
            "tank_low_m": MODULE.TANK["low"],
            "tank_size_m": MODULE.TANK["size"],
            "finite_walls": ["bottom", "left", "right", "front", "back"],
            "body": MODULE.BODY,
            "floatingtype": 2,
            "aggregate_massbody_kg": MODULE.BODY["mass_kg"],
            "analytic_inertia_kg_m2": MODULE.body_inertia(),
            "initial_submerged_body_volume_m3": MODULE.initial_submerged_body_volume(),
            "same_geometry_and_control_as_registered_mother": True,
        },
        "discrete_contract": {
            "dp_m": DP_M,
            "expected_fluid_particles": MODULE.expected_fluid_particles(DP_M),
            "expected_transverse_layers": round(MODULE.FLUID["size"][1] / DP_M),
            "expected_fluid_mass_kg": MODULE.expected_fluid_particles(DP_M) * DP_M**3 * MODULE.RHO_WATER,
            "direct_cell_centre_rule": "continuous low + dp/2 with measured inclusive span; no fillbox|void",
        },
        "case_count": len(manifest.get("cases", [])),
        "case_ids": [case["case_id"] for case in manifest.get("cases", [])],
        "manifest_sha256_after_write": MODULE.sha256(FAMILY_ROOT / "manifest.json"),
        "physical_geometry_sha256": MODULE.sha256(FAMILY_ROOT / "physical_mother_geometry.json"),
        "old_scope_preserved": True,
    }


def prepare() -> dict[str, Any]:
    manifest = MODULE.prepare()
    manifest["status"] = "fresh_dp025_cpu_gencase_pending"
    manifest["scope_id"] = "F6_HANDOFF_20261002_COMMENSURATE_DP025"
    manifest["history_boundary"] = {
        "new_spatial_scope": True,
        "old_commensurate_mother_immutable": True,
        "old_domain_xy_repair_02_immutable": True,
        "old_fallback_and_failed_repairs_preserved": True,
        "reason": "dp025 is a registered spatial follow-up after the actual six-case macro comparison; no old result is relabeled",
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
