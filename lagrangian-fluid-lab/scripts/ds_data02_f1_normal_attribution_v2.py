#!/usr/bin/env python3
"""F1 normal attribution v2 with the complete separator face set.

The first additive audit intentionally reused the existing F1 outer-five and
separator-side face vocabulary.  The immutable XML uses ``all^bottom`` for
the separator, which also emits its finite top face at ``z=0.7``.  This
wrapper keeps the v1 implementation and report unchanged while adding that
face to the attribution ledger.  It does not change the source XML or rerun
GenCase/solver.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

LAB = Path(__file__).resolve().parents[1]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from scripts import ds_data02_f1_normal_attribution as _v1


SCHEMA = "ds02.f1.finite-center.initial-normal-attribution.v2"
FACE_SPECS: tuple[dict[str, Any], ...] = _v1.FACE_SPECS + (
    {
        "name": "separator_z_high",
        "population": "separator",
        "mk": 11,
        "axis": 2,
        "target": 0.7,
        "tangent": (0, 1),
        "low": (1.25, 0.34),
        "high": (2.05, 0.4),
    },
)


def audit(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Run the v1 reader with the additive complete face vocabulary."""

    previous_specs = _v1.FACE_SPECS
    previous_schema = _v1.SCHEMA
    _v1.FACE_SPECS = FACE_SPECS
    _v1.SCHEMA = SCHEMA
    try:
        return _v1.audit(*args, **kwargs)
    finally:
        _v1.FACE_SPECS = previous_specs
        _v1.SCHEMA = previous_schema


def main() -> int:
    previous_specs = _v1.FACE_SPECS
    previous_schema = _v1.SCHEMA
    _v1.FACE_SPECS = FACE_SPECS
    _v1.SCHEMA = SCHEMA
    try:
        return _v1.main()
    finally:
        _v1.FACE_SPECS = previous_specs
        _v1.SCHEMA = previous_schema


if __name__ == "__main__":
    raise SystemExit(main())
