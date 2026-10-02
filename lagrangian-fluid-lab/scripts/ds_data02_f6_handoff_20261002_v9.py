#!/usr/bin/env python3
"""F6 RIGID003 mother with explicit native aggregate center/inertia.

The previous commensurate mother left center/inertia implicit, so GenCase
derived them from DP-dependent boundary particles.  The official XML contract
supports explicit ``center`` and diagonal ``inertia`` under ``floating``.
This additive generator keeps the same continuous geometry and particle
population rule, while binding the native aggregate rigid parameters to the
same physical values at all three DPs.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path


SCRIPT = Path(__file__).resolve()
V5 = SCRIPT.with_name("ds_data02_f6_handoff_20261002_v5.py")
SPEC = importlib.util.spec_from_file_location("f6_handoff_20261002_v5", V5)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load commensurate mother generator: {V5}")
MODULE_V5 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE_V5)
MODULE = MODULE_V5.MODULE
BASE_DEFINITION_XML = MODULE_V5._definition_xml
V4 = V5.with_name("ds_data02_f6_handoff_20261002_v4.py")
V3 = V5.with_name("ds_data02_f6_handoff_20261002_v3.py")
V2 = V5.with_name("ds_data02_f6_handoff_20261002_v2.py")
V1 = V5.with_name("ds_data02_f6_handoff_20261002.py")

MODULE.FAMILY_ROOT = MODULE.REPO_ROOT / "campaigns/ds-data-02/families/F6/handoff_20261002/rigid_contract_003"
MODULE.SCRIPT = SCRIPT
MODULE.VERSION = "ds_data02_f6_handoff_20261002.rigid_contract_003.v1"
MODULE.MECHANISMS = {
    key: {
        **value,
        "case_prefix": value["case_prefix"].replace("_COMMENSURATE", "_RIGID003"),
        "physical_case_id": value["physical_case_id"] + "_RIGID_CONTRACT_003",
        "geometry_family_id": value["geometry_family_id"] + "_RIGID_CONTRACT_003",
    }
    for key, value in MODULE.MECHANISMS.items()
}

RIGID_CENTER = [2.4, 1.2, 1.08]
RIGID_INERTIA = [8.533333333333335, 8.533333333333335, 13.653333333333336]


_BASE_INPUT_FILES = MODULE._request_input_files


def _request_input_files_with_lineage(*paths: Path) -> list[str]:
    values = _BASE_INPUT_FILES(*paths)
    for path in (V5, V4, V3, V2, V1):
        value = str(path.resolve())
        if value not in values:
            values.append(value)
    return values


MODULE._request_input_files = _request_input_files_with_lineage


def _definition_xml(mechanism: str, resolution: str, dp: float) -> str:
    xml = BASE_DEFINITION_XML(mechanism, resolution, dp)
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
        raise ValueError("RIGID003 floating contract insertion point not found")
    return repaired.replace(
        "Commensurate mother direct solid drawbox: measured GenCase lattice span; continuous physical faces remain frozen.",
        "RIGID003 direct solid drawbox: measured GenCase lattice span; continuous physical faces and native rigid center/inertia remain frozen.",
    )


MODULE._definition_xml = _definition_xml


_BASE_NATIVE_JSON = MODULE._native_json


def _native_json(path: Path, mechanism: str, resolution: str, dp: float) -> dict[str, object]:
    record = _BASE_NATIVE_JSON(path, mechanism, resolution, dp)
    payload = MODULE.read_json(path)
    payload["generator_version"] = MODULE.VERSION
    payload["initialization_repair"] = {
        "mother_id": "F6_HANDOFF_20261002_RIGID_CONTRACT_003",
        "same_continuous_geometry": True,
        "body_initial_lower_face_m": 0.88,
        "continuous_fluid_top_m": 0.84,
        "explicit_native_center_m": RIGID_CENTER,
        "explicit_native_inertia_kg_m2": [[RIGID_INERTIA[0], 0.0, 0.0], [0.0, RIGID_INERTIA[1], 0.0], [0.0, 0.0, RIGID_INERTIA[2]]],
        "no_mass_rescaling": True,
    }
    payload["geometry_contract"]["body_fluid_overlap_initial"] = "zero: body bottom z=0.88 m, continuous fluid top z=0.84 m"
    payload["rigid_body"]["initial_pose"]["center_m"] = RIGID_CENTER
    payload["rigid_body"]["source_inertia_kg_m2"] = [[RIGID_INERTIA[0], 0.0, 0.0], [0.0, RIGID_INERTIA[1], 0.0], [0.0, 0.0, RIGID_INERTIA[2]]]
    payload["rigid_body"]["explicit_def_contract"] = {"center_m": RIGID_CENTER, "inertia_kg_m2": payload["rigid_body"]["source_inertia_kg_m2"]}
    MODULE.write_json(path, payload)
    return {"path": str(path.resolve()), "sha256": MODULE.sha256(path)}


MODULE._native_json = _native_json


def main() -> int:
    return MODULE.main()


if __name__ == "__main__":
    raise SystemExit(main())
