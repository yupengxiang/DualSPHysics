#!/usr/bin/env python3
"""Prepare F6 explicit-body v5 with dp-aligned fluid low point."""

from __future__ import annotations

from pathlib import Path
import sys

LAB = Path(__file__).resolve().parents[1]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from scripts import f6_physical_anchor_explicit_body_root_review_v4 as v4  # noqa: E402


ROOT = LAB / "campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-explicit-body-root-review-v5-20260921"
IDENTITY = "CORE_F6_physical_anchor_single_body_gravity_explicit_body_v5_20260921"
BODY_ID = "F6_physical_anchor_body_zeta_20260921"
REVISION = "F6_gravity_single_body_entry_buoyancy_explicit_body_dp_aligned_origin_v5"
SCRIPT = Path(__file__).resolve()


def configure_base() -> None:
    v4.ROOT = ROOT
    v4.IDENTITY = IDENTITY
    v4.BODY_ID = BODY_ID
    v4.REVISION = REVISION
    v4.SCRIPT = SCRIPT
    v4.v3.v2.base.FLUID_LOW = (0.18, 0.08, 0.04)
    v4.configure_base()


def main() -> int:
    configure_base()
    return v4.main()


if __name__ == "__main__":
    raise SystemExit(main())
