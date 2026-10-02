#!/usr/bin/env python3
"""Final bounded F6 cell-centre extent repair for handoff_20261002.

Repair-001 showed that GenCase's direct solid drawbox includes the x/y face
endpoints.  Repair-002 changes only those two draw extents to ``L-2*dp`` and
keeps the z extent at ``H-dp``.  It is a new source/definition/request tree;
the v1 and repair-001 bytes and receipts remain immutable negative evidence.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path


SCRIPT = Path(__file__).resolve()
V2 = SCRIPT.with_name("ds_data02_f6_handoff_20261002_v2.py")
SPEC = importlib.util.spec_from_file_location("f6_handoff_20261002_v2", V2)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load repair-001 generator: {V2}")
MODULE_V2 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE_V2)
MODULE = MODULE_V2.MODULE
BASE_DEFINITION_XML = MODULE_V2._repair_definition_xml
V1 = V2.with_name("ds_data02_f6_handoff_20261002.py")

MODULE.FAMILY_ROOT = MODULE.REPO_ROOT / "campaigns/ds-data-02/families/F6/handoff_20261002/repair_002"
MODULE.SCRIPT = SCRIPT
MODULE.VERSION = "ds_data02_f6_handoff_20261002.repair_002.v1"
MODULE.MECHANISMS = {
    key: {**value, "case_prefix": value["case_prefix"].replace("_REPAIR001", "_REPAIR002")}
    for key, value in MODULE.MECHANISMS.items()
}

_BASE_INPUT_FILES = MODULE._request_input_files


def _request_input_files_with_lineage(*paths: Path) -> list[str]:
    values = _BASE_INPUT_FILES(*paths)
    for path in (V2, V1):
        value = str(path.resolve())
        if value not in values:
            values.append(value)
    return values


MODULE._request_input_files = _request_input_files_with_lineage


def _repair_definition_xml(mechanism: str, resolution: str, dp: float) -> str:
    xml = BASE_DEFINITION_XML(mechanism, resolution, dp)
    replacement = (
        f'<size x="{MODULE.fmt(MODULE.FLUID["size"][0] - 2.0 * dp)}" '
        f'y="{MODULE.fmt(MODULE.FLUID["size"][1] - 2.0 * dp)}" '
        f'z="{MODULE.fmt(MODULE.FLUID["size"][2] - dp)}" />'
    )
    pattern = re.compile(
        r'(<drawbox cmt="Frozen continuous fluid cell-centre population">.*?<size )'
        r'x="[^"]+" y="[^"]+" z="[^"]+"(\s*/>)',
        re.DOTALL,
    )
    repaired, count = pattern.subn(rf"\g<1>{replacement[6:-3]}\g<2>", xml, count=1)
    if count != 1:
        raise ValueError("repair-002 fluid drawbox was not found")
    return repaired.replace(
        "Repair-001 direct solid drawbox: dp|bound cell-centre population; v1 endpoint-plane evidence retained separately.",
        "Repair-002 direct solid drawbox: x/y extents L-2dp remove inclusive endpoint planes; v1/repair-001 evidence retained separately.",
    )


MODULE._definition_xml = _repair_definition_xml


def main() -> int:
    return MODULE.main()


if __name__ == "__main__":
    raise SystemExit(main())
