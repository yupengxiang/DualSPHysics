#!/usr/bin/env python3
"""Second, bounded lattice-endpoint repair for the F6 domain mother.

The first ``DOMAIN_X_REPAIR_01`` CPU outputs fixed the x endpoint, but its
coarse (dp=0.08) native ``*_Bound.vtk`` still had no fixed y-max face: the
continuous wall remains y=2.4 m while the coarse pointmax y=2.48 m rasterized
only through y=2.32 m.  This additive mother applies the same numerical-only
endpoint rule to coarse y (pointmax y=2.56 m); medium/fine keep their already
passing physical representation.  It preserves all continuous dimensions,
fluid population/mass denominator, floating mass/center/inertia, and paddle
control.  It does not edit DOMAIN_X_REPAIR_01 or any consumed medium input.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path


SCRIPT = Path(__file__).resolve()
V14 = SCRIPT.with_name("ds_data02_f6_handoff_20261002_v14.py")
V13 = SCRIPT.with_name("ds_data02_f6_handoff_20261002_v13.py")
SPEC = importlib.util.spec_from_file_location("f6_domain_x_repair_v13_for_xy", V13)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load DOMAIN_X_REPAIR_01 generator: {V13}")
MODULE_V13 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE_V13)
MODULE = MODULE_V13.MODULE
BASE_DEFINITION_XML = MODULE_V13._definition_xml
BASE_NATIVE_JSON = MODULE_V13._native_json
BASE_REQUEST_INPUT_FILES = MODULE._request_input_files
BASE_PREPARE = MODULE.prepare

DIAGNOSIS_SIDECAR = MODULE_V13.DIAGNOSIS_SIDECAR
MODULE.FAMILY_ROOT = MODULE.REPO_ROOT / "campaigns/ds-data-02/families/F6/handoff_20261002/rigid_contract_003/domain_xy_repair_02"
MODULE.SCRIPT = SCRIPT
MODULE.VERSION = "ds_data02_f6_handoff_20261002.rigid003_domain_xy_repair_02.v1"
MODULE.MECHANISMS = {
    key: {
        **value,
        "case_prefix": value["case_prefix"].replace("_DOMAIN_X_REPAIR_01", "_DOMAIN_XY_REPAIR_02"),
        "physical_case_id": value["physical_case_id"].replace("_DOMAIN_X_REPAIR_01", "_DOMAIN_XY_REPAIR_02"),
        "geometry_family_id": value["geometry_family_id"].replace("_DOMAIN_X_REPAIR_01", "_DOMAIN_XY_REPAIR_02"),
    }
    for key, value in MODULE.MECHANISMS.items()
}


def _request_input_files_with_lineage(*paths: Path) -> list[str]:
    values = BASE_REQUEST_INPUT_FILES(*paths)
    for path in (SCRIPT, V14, V13, DIAGNOSIS_SIDECAR):
        resolved = str(path.resolve())
        if resolved not in values:
            values.append(resolved)
    return values


MODULE._request_input_files = _request_input_files_with_lineage


def _definition_xml(mechanism: str, resolution: str, dp: float) -> str:
    xml = BASE_DEFINITION_XML(mechanism, resolution, dp)
    if abs(dp - 0.08) <= 1.0e-12:
        pattern = re.compile(r'(<pointmax\s+x="4.9"\s+y=")[^"]+("\s+z="[^"]+"\s*/>)')
        xml, count = pattern.subn(r'\g<1>2.56\g<2>', xml, count=1)
        if count != 1:
            raise ValueError("coarse DOMAIN_X_REPAIR_01 pointmax was not found")
    return xml.replace(
        "RIGID003 DOMAIN_X_REPAIR_01: pointmax.x includes frozen x=4.8 wall endpoint; explicit x simulationdomain is numerical margin only; continuous geometry and native rigid contract remain frozen.",
        "RIGID003 DOMAIN_XY_REPAIR_02: coarse pointmax.y includes frozen y=2.4 wall endpoint; x/y simulation-domain margins are numerical only; continuous geometry and native rigid contract remain frozen.",
    )


MODULE._definition_xml = _definition_xml


def _native_json(path: Path, mechanism: str, resolution: str, dp: float) -> dict[str, object]:
    record = BASE_NATIVE_JSON(path, mechanism, resolution, dp)
    payload = MODULE.read_json(path)
    payload["generator_version"] = MODULE.VERSION
    payload["domain_endpoint_repair"] = {
        "repair_id": "F6_HANDOFF_20261002_RIGID003_DOMAIN_XY_REPAIR_02",
        "prior_repair_id": "F6_HANDOFF_20261002_RIGID003_DOMAIN_X_REPAIR_01",
        "diagnosis_sidecar": str(DIAGNOSIS_SIDECAR.resolve()),
        "diagnosis_sidecar_sha256": MODULE.sha256(DIAGNOSIS_SIDECAR),
        "root_cause": "coarse native fixed y-max face absent because pointmax.y=2.48 rasterized only to y=2.32",
        "numerical_only": True,
        "pointmax_x_m": 4.9,
        "pointmax_y_m": 2.56 if abs(dp - 0.08) <= 1.0e-12 else (2.45 if abs(dp - 0.05) <= 1.0e-12 else 2.44),
        "simulationdomain_x_m": [-0.2, 5.0],
        "frozen_physical_tank_xy_m": [[0.0, 4.8], [0.0, 2.4]],
        "continuous_geometry_unchanged": True,
        "fluid_mass_denominator_unchanged": True,
        "floating_mass_center_inertia_unchanged": True,
        "wave_control_unchanged": True,
    }
    MODULE.write_json(path, payload)
    return record


MODULE._native_json = _native_json


def prepare():
    manifest = BASE_PREPARE()
    path = MODULE.FAMILY_ROOT / "manifest.json"
    payload = MODULE.read_json(path)
    payload["domain_endpoint_repair"] = {
        "repair_id": "F6_HANDOFF_20261002_RIGID003_DOMAIN_XY_REPAIR_02",
        "prior_repair_id": "F6_HANDOFF_20261002_RIGID003_DOMAIN_X_REPAIR_01",
        "diagnosis_sidecar": str(DIAGNOSIS_SIDECAR.resolve()),
        "diagnosis_sidecar_sha256": MODULE.sha256(DIAGNOSIS_SIDECAR),
        "change_scope": "coarse numerical lattice y endpoint only; x repair retained",
        "coarse_pointmax_xy_m": [4.9, 2.56],
        "medium_pointmax_xy_m": [4.9, 2.45],
        "fine_pointmax_xy_m": [4.9, 2.44],
        "simulationdomain_x_m": [-0.2, 5.0],
        "frozen_physical_wall_xy_m": [[0.0, 4.8], [0.0, 2.4]],
        "same_continuous_geometry_across_dp": True,
        "old_domain_x_repair_outputs_immutable": True,
        "gpu_launch": False,
    }
    MODULE.write_json(path, payload)
    return payload


MODULE.prepare = prepare


def main() -> int:
    return MODULE.main()


if __name__ == "__main__":
    raise SystemExit(main())
