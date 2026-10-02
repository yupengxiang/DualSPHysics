#!/usr/bin/env python3
"""Final tie-break completion of the bounded F6 handoff_20261002 repair.

The repair-002 receipts are retained.  They exposed deterministic lattice
roundoff (one x/y endpoint layer at medium/fine) and a fine-grid body/free-
surface coincidence.  This additive version keeps the same continuous mother,
uses a 1e-6 m numerical drawbox tie-break, moves the body's initial lower face
0.04 m above the liquid face, and shortens the non-overlapping piston to
0.32 m.  No physical tank or fluid-box face is moved and no mass is rescaled.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path


SCRIPT = Path(__file__).resolve()
V3 = SCRIPT.with_name("ds_data02_f6_handoff_20261002_v3.py")
SPEC = importlib.util.spec_from_file_location("f6_handoff_20261002_v3", V3)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load repair-002 generator: {V3}")
MODULE_V3 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE_V3)
MODULE = MODULE_V3.MODULE
BASE_DEFINITION_XML = MODULE_V3._repair_definition_xml
V2 = V3.with_name("ds_data02_f6_handoff_20261002_v2.py")
V1 = V3.with_name("ds_data02_f6_handoff_20261002.py")
ROUNDING_EPSILON_M = 1.0e-6

MODULE.FAMILY_ROOT = MODULE.REPO_ROOT / "campaigns/ds-data-02/families/F6/handoff_20261002/repair_002b"
MODULE.SCRIPT = SCRIPT
MODULE.VERSION = "ds_data02_f6_handoff_20261002.repair_002b.v1"
MODULE.MECHANISMS = {
    key: {**value, "case_prefix": value["case_prefix"].replace("_REPAIR002", "_REPAIR002B")}
    for key, value in MODULE.MECHANISMS.items()
}
MODULE.BODY = {**MODULE.BODY, "point": [2.0, 0.8, 0.88]}
MODULE.PADDLE = {**MODULE.PADDLE, "size": [0.32, MODULE.PADDLE["size"][1], MODULE.PADDLE["size"][2]]}

_BASE_INPUT_FILES = MODULE._request_input_files


def _request_input_files_with_lineage(*paths: Path) -> list[str]:
    values = _BASE_INPUT_FILES(*paths)
    for path in (V3, V2, V1):
        value = str(path.resolve())
        if value not in values:
            values.append(value)
    return values


MODULE._request_input_files = _request_input_files_with_lineage


_BASE_NATIVE_JSON = MODULE._native_json


def _native_json(path: Path, mechanism: str, resolution: str, dp: float) -> dict[str, object]:
    record = _BASE_NATIVE_JSON(path, mechanism, resolution, dp)
    payload = MODULE.read_json(path)
    payload["rigid_body"]["initial_pose"]["center_m"] = [2.4, 1.2, 1.08]
    payload["initialization_repair"] = {
        "repair_id": "F6_HANDOFF_20261002_REPAIR_002B",
        "roundoff_epsilon_m": ROUNDING_EPSILON_M,
        "body_initial_lower_face_m": 0.88,
        "paddle_x_size_m": 0.32,
        "same_continuous_geometry": True,
    }
    MODULE.write_json(path, payload)
    return {"path": str(path.resolve()), "sha256": MODULE.sha256(path)}


MODULE._native_json = _native_json


def _repair_definition_xml(mechanism: str, resolution: str, dp: float) -> str:
    xml = BASE_DEFINITION_XML(mechanism, resolution, dp)
    replacement = (
        f'<size x="{MODULE.fmt(MODULE.FLUID["size"][0] - 2.0 * dp + ROUNDING_EPSILON_M)}" '
        f'y="{MODULE.fmt(MODULE.FLUID["size"][1] - 2.0 * dp + ROUNDING_EPSILON_M)}" '
        f'z="{MODULE.fmt(MODULE.FLUID["size"][2] - dp)}" />'
    )
    pattern = re.compile(
        r'(<drawbox cmt="Frozen continuous fluid cell-centre population">.*?<size )'
        r'x="[^"]+" y="[^"]+" z="[^"]+"(\s*/>)',
        re.DOTALL,
    )
    repaired, count = pattern.subn(rf"\g<1>{replacement[6:-3]}\g<2>", xml, count=1)
    if count != 1:
        raise ValueError("repair-002b fluid drawbox was not found")
    return repaired.replace(
        "Repair-002 direct solid drawbox: x/y extents L-2dp remove inclusive endpoint planes; v1/repair-001 evidence retained separately.",
        "Repair-002B direct solid drawbox: x/y extents L-2dp+1e-6m tie-break; body/paddle clear of initial fluid centres.",
    )


MODULE._definition_xml = _repair_definition_xml


def main() -> int:
    return MODULE.main()


if __name__ == "__main__":
    raise SystemExit(main())
