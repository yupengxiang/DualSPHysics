#!/usr/bin/env python3
"""Additive initialization repair for the F6 handoff_20261002 mother.

The first fresh mother was retained as negative evidence: ``dp | real | bound``
caused GenCase to include the x/y endpoint planes in the direct fluid drawbox.
This wrapper imports the frozen v1 generator, changes only the shape-mode
sampling token, and writes every v2 definition/request under a new repair
directory with new case/attempt identities.  The v1 source, definitions and
receipt are never edited or reused as v2 evidence.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve()
V1 = SCRIPT.with_name("ds_data02_f6_handoff_20261002.py")
SPEC = importlib.util.spec_from_file_location("f6_handoff_20261002_v1", V1)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load frozen v1 generator: {V1}")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

MODULE.FAMILY_ROOT = MODULE.REPO_ROOT / "campaigns/ds-data-02/families/F6/handoff_20261002/repair_001"
MODULE.SCRIPT = SCRIPT
MODULE.VERSION = "ds_data02_f6_handoff_20261002.repair_001.v1"
MODULE.MECHANISMS = {
    key: {**value, "case_prefix": value["case_prefix"] + "_REPAIR001"}
    for key, value in MODULE.MECHANISMS.items()
}
_V1_DEFINITION_XML = MODULE._definition_xml


def _repair_definition_xml(mechanism: str, resolution: str, dp: float) -> str:
    xml = _V1_DEFINITION_XML(mechanism, resolution, dp)
    replaced = xml.replace("dp | real | bound", "dp | bound")
    if replaced == xml:
        raise ValueError("repair token was absent from v1 Definition")
    return replaced.replace(
        "Direct solid drawbox: first centre = continuous low + dp/2.",
        "Repair-001 direct solid drawbox: dp|bound cell-centre population; v1 endpoint-plane evidence retained separately.",
    )


MODULE._definition_xml = _repair_definition_xml


def main() -> int:
    return MODULE.main()


if __name__ == "__main__":
    raise SystemExit(main())
