#!/usr/bin/env python3
"""F6 RIGID003 domain/wall-endpoint repair, additive CPU GenCase mother.

The immutable RIGID003 medium solver failures are diagnosed in
``domain_diagnosis_002``.  Native ``*_Bound.vtk`` shows that the declared
finite right wall has no interior x-max particles because the numerical
lattice stopped at x=4.75 m while the continuous wall endpoint is x=4.8 m;
the automatic solver domain also stopped at x=4.7552 m.  This module keeps
the continuous tank, fluid, body, mass, inertia, and wave control unchanged,
then changes only numerical representation:

* ``pointmax.x`` is extended from 4.85 to 4.90 so the x=4.8 wall endpoint is
  represented by the lattice;
* the solver simulation domain receives explicit x bounds [-0.2, 5.0] m,
  leaving a positive numerical margin around the frozen physical tank.

It is a new mother scope.  It never edits consumed RIGID003 definitions,
receipts, or solver outputs and never launches a solver/GPU.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path


SCRIPT = Path(__file__).resolve()
V12 = SCRIPT.with_name("ds_data02_f6_handoff_20261002_v12.py")
V9 = SCRIPT.with_name("ds_data02_f6_handoff_20261002_v9.py")
SPEC = importlib.util.spec_from_file_location("f6_handoff_20261002_v9_domain_x", V9)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load RIGID003 generator: {V9}")
MODULE_V9 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE_V9)
MODULE = MODULE_V9.MODULE
BASE_DEFINITION_XML = MODULE_V9._definition_xml
BASE_NATIVE_JSON = MODULE_V9._native_json
BASE_REQUEST_INPUT_FILES = MODULE._request_input_files
BASE_PREPARE = MODULE.prepare

DIAGNOSIS_SIDECAR = (
    MODULE.REPO_ROOT
    / "campaigns/ds-data-02/families/F6/handoff_20261002/rigid_contract_003/domain_diagnosis_002/diagnosis_receipt_sidecar.json"
)

MODULE.FAMILY_ROOT = MODULE.REPO_ROOT / "campaigns/ds-data-02/families/F6/handoff_20261002/rigid_contract_003/domain_x_repair_01"
MODULE.SCRIPT = SCRIPT
MODULE.VERSION = "ds_data02_f6_handoff_20261002.rigid003_domain_x_repair_01.v1"
MODULE.MECHANISMS = {
    key: {
        **value,
        "case_prefix": value["case_prefix"].replace("_RIGID003", "_RIGID003_DOMAIN_X_REPAIR_01"),
        "physical_case_id": value["physical_case_id"] + "_DOMAIN_X_REPAIR_01",
        "geometry_family_id": value["geometry_family_id"] + "_DOMAIN_X_REPAIR_01",
    }
    for key, value in MODULE.MECHANISMS.items()
}


def _request_input_files_with_lineage(*paths: Path) -> list[str]:
    values = BASE_REQUEST_INPUT_FILES(*paths)
    for path in (SCRIPT, V12, V9, DIAGNOSIS_SIDECAR):
        resolved = str(path.resolve())
        if resolved not in values:
            values.append(resolved)
    return values


MODULE._request_input_files = _request_input_files_with_lineage


def _definition_xml(mechanism: str, resolution: str, dp: float) -> str:
    xml = BASE_DEFINITION_XML(mechanism, resolution, dp)
    # This edit is numerical only.  The drawbox physical wall remains
    # point=(0,0,0), size=(4.8,2.4,2.4), and the direct fluid/body drawboxes
    # are inherited unchanged from RIGID003.
    pattern = re.compile(
        r'(<pointmax\s+x=")([^"]+)("\s+y="[^"]+"\s+z="[^"]+"\s*/>)'
    )
    xml, pointmax_count = pattern.subn(r'\g<1>4.9\g<3>', xml, count=1)
    if pointmax_count != 1:
        raise ValueError("RIGID003 pointmax was not found")
    posmin = re.compile(r'(<posmin\s+x=")default("\s+y="default"\s+z="default"[^>]*/>)')
    xml, posmin_count = posmin.subn(r'\g<1>-0.2\g<2>', xml, count=1)
    posmax = re.compile(r'(<posmax\s+x=")default("\s+y="default"\s+z="default \+ 20%"[^>]*/>)')
    xml, posmax_count = posmax.subn(r'\g<1>5.0\g<2>', xml, count=1)
    if posmin_count != 1 or posmax_count != 1:
        raise ValueError("RIGID003 simulationdomain defaults were not found")
    return xml.replace(
        "RIGID003 direct solid drawbox: measured GenCase lattice span; continuous physical faces and native rigid center/inertia remain frozen.",
        "RIGID003 DOMAIN_X_REPAIR_01: pointmax.x includes frozen x=4.8 wall endpoint; explicit x simulationdomain is numerical margin only; continuous geometry and native rigid contract remain frozen.",
    )


MODULE._definition_xml = _definition_xml


def _native_json(path: Path, mechanism: str, resolution: str, dp: float) -> dict[str, object]:
    record = BASE_NATIVE_JSON(path, mechanism, resolution, dp)
    payload = MODULE.read_json(path)
    payload["generator_version"] = MODULE.VERSION
    payload["domain_repair"] = {
        "repair_id": "F6_HANDOFF_20261002_RIGID003_DOMAIN_X_REPAIR_01",
        "diagnosis_sidecar": str(DIAGNOSIS_SIDECAR.resolve()),
        "diagnosis_sidecar_sha256": MODULE.sha256(DIAGNOSIS_SIDECAR),
        "root_cause": "native fixed x-max face absent and automatic MapRealPos x limit below frozen wall endpoint",
        "numerical_only": True,
        "pointmax_x_m": 4.9,
        "simulationdomain_x_m": [-0.2, 5.0],
        "frozen_physical_tank_x_m": [0.0, 4.8],
        "continuous_geometry_unchanged": True,
        "fluid_mass_denominator_unchanged": True,
        "floating_mass_center_inertia_unchanged": True,
        "wave_control_unchanged": True,
    }
    payload["geometry_contract"]["pointmax_is_computational_only"] = True
    payload["geometry_contract"]["numerical_domain_x_m"] = [-0.2, 5.0]
    MODULE.write_json(path, payload)
    return record


MODULE._native_json = _native_json


def prepare():
    manifest = BASE_PREPARE()
    path = MODULE.FAMILY_ROOT / "manifest.json"
    payload = MODULE.read_json(path)
    payload["domain_repair"] = {
        "repair_id": "F6_HANDOFF_20261002_RIGID003_DOMAIN_X_REPAIR_01",
        "diagnosis_sidecar": str(DIAGNOSIS_SIDECAR.resolve()),
        "diagnosis_sidecar_sha256": MODULE.sha256(DIAGNOSIS_SIDECAR),
        "change_scope": "numerical lattice endpoint plus explicit solver x bounds",
        "pointmax_x_m": 4.9,
        "simulationdomain_x_m": [-0.2, 5.0],
        "frozen_physical_wall_x_m": [0.0, 4.8],
        "same_continuous_geometry_across_dp": True,
        "old_rigid003_outputs_immutable": True,
        "gpu_launch": False,
    }
    MODULE.write_json(path, payload)
    return payload


MODULE.prepare = prepare


def main() -> int:
    return MODULE.main()


if __name__ == "__main__":
    raise SystemExit(main())
