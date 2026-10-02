#!/usr/bin/env python3
"""Additive commensurate-cell mother after the repair-002b negative audit.

The repair-002b receipts showed that GenCase's lattice rasteriser includes the
drawbox endpoints differently at dp=.05/.04 than at dp=.08.  This module keeps
the registered continuous tank, fluid box, body, mass and paddle unchanged and
changes only the numerical drawbox span needed to emit exactly the registered
cell-centre count at the two affected resolutions.  The coarse span remains
the measured passing span.  It is a new mother scope; all prior definitions
and receipts remain immutable negative evidence.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path


SCRIPT = Path(__file__).resolve()
V4 = SCRIPT.with_name("ds_data02_f6_handoff_20261002_v4.py")
SPEC = importlib.util.spec_from_file_location("f6_handoff_20261002_v4", V4)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load repair-002b generator: {V4}")
MODULE_V4 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE_V4)
MODULE = MODULE_V4.MODULE
BASE_DEFINITION_XML = MODULE_V4._repair_definition_xml
V3 = V4.with_name("ds_data02_f6_handoff_20261002_v3.py")
V2 = V4.with_name("ds_data02_f6_handoff_20261002_v2.py")
V1 = V4.with_name("ds_data02_f6_handoff_20261002.py")
ROUNDING_EPSILON_M = 1.0e-6

MODULE.FAMILY_ROOT = MODULE.REPO_ROOT / "campaigns/ds-data-02/families/F6/handoff_20261002/commensurate_mother"
MODULE.SCRIPT = SCRIPT
MODULE.VERSION = "ds_data02_f6_handoff_20261002.commensurate_mother.v1"
MODULE.MECHANISMS = {
    key: {
        **value,
        "case_prefix": value["case_prefix"].replace("_REPAIR002B", "_COMMENSURATE"),
        "physical_case_id": value["physical_case_id"] + "_COMMENSURATE_CELL_CENTRE",
        "geometry_family_id": value["geometry_family_id"] + "_COMMENSURATE_CELL_CENTRE",
    }
    for key, value in MODULE.MECHANISMS.items()
}


_BASE_INPUT_FILES = MODULE._request_input_files


def _request_input_files_with_lineage(*paths: Path) -> list[str]:
    values = _BASE_INPUT_FILES(*paths)
    for path in (V4, V3, V2, V1):
        value = str(path.resolve())
        if value not in values:
            values.append(value)
    return values


MODULE._request_input_files = _request_input_files_with_lineage


_BASE_NATIVE_JSON = MODULE._native_json


def _native_json(path: Path, mechanism: str, resolution: str, dp: float) -> dict[str, object]:
    record = _BASE_NATIVE_JSON(path, mechanism, resolution, dp)
    payload = MODULE.read_json(path)
    payload["initialization_repair"] = {
        "mother_id": "F6_HANDOFF_20261002_COMMENSURATE_CELL_CENTRE",
        "source_negative_evidence": "repair_002b medium/fine endpoint counts",
        "lattice_span_rule": "coarse uses measured L-2dp+epsilon; medium/fine use L-dp+epsilon to emit N=L/dp points",
        "same_continuous_geometry": True,
        "body_initial_lower_face_m": 0.88,
        "paddle_x_size_m": 0.32,
        "no_mass_rescaling": True,
    }
    MODULE.write_json(path, payload)
    return {"path": str(path.resolve()), "sha256": MODULE.sha256(path)}


MODULE._native_json = _native_json


def _definition_xml(mechanism: str, resolution: str, dp: float) -> str:
    xml = BASE_DEFINITION_XML(mechanism, resolution, dp)
    # GenCase's measured inclusive rasterisation: repair-002b already emitted
    # the exact coarse count.  Medium/fine need one additional dp in x/y span;
    # the physical FLUID low/high faces in the manifest never move.
    xy_extra = 0.0 if abs(dp - 0.08) <= 1.0e-12 else dp
    x_size = MODULE.FLUID["size"][0] - 2.0 * dp + xy_extra + ROUNDING_EPSILON_M
    y_size = MODULE.FLUID["size"][1] - 2.0 * dp + xy_extra + ROUNDING_EPSILON_M
    replacement = f'<size x="{MODULE.fmt(x_size)}" y="{MODULE.fmt(y_size)}" z="{MODULE.fmt(MODULE.FLUID["size"][2] - dp)}" />'
    pattern = re.compile(
        r'(<drawbox cmt="Frozen continuous fluid cell-centre population">.*?<size )'
        r'x="[^"]+" y="[^"]+" z="[^"]+"(\s*/>)',
        re.DOTALL,
    )
    repaired, count = pattern.subn(rf"\g<1>{replacement[6:-3]}\g<2>", xml, count=1)
    if count != 1:
        raise ValueError("commensurate mother fluid drawbox was not found")
    return repaired.replace(
        "Repair-002B direct solid drawbox: x/y extents L-2dp+1e-6m tie-break; body/paddle clear of initial fluid centres.",
        "Commensurate mother direct solid drawbox: measured GenCase lattice span; continuous physical faces remain frozen.",
    )


MODULE._definition_xml = _definition_xml


def main() -> int:
    return MODULE.main()


if __name__ == "__main__":
    raise SystemExit(main())
