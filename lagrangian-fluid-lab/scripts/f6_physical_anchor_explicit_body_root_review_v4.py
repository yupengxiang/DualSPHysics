#!/usr/bin/env python3
"""Prepare F6 explicit-body v4 with dp-aligned fluid height."""

from __future__ import annotations

from pathlib import Path
import sys

LAB = Path(__file__).resolve().parents[1]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from scripts import f6_physical_anchor_explicit_body_root_review_v3 as v3  # noqa: E402


ROOT = LAB / "campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-explicit-body-root-review-v4-20260921"
IDENTITY = "CORE_F6_physical_anchor_single_body_gravity_explicit_body_v4_20260921"
BODY_ID = "F6_physical_anchor_body_epsilon_20260921"
REVISION = "F6_gravity_single_body_entry_buoyancy_explicit_body_dp_aligned_fluid_v4"
SCRIPT = Path(__file__).resolve()


def configure_base() -> None:
    v3.ROOT = ROOT
    v3.IDENTITY = IDENTITY
    v3.BODY_ID = BODY_ID
    v3.REVISION = REVISION
    v3.SCRIPT = SCRIPT
    v3.v2.base.FLUID_SIZE = (1.14, 0.44, 0.24)
    v3.configure_base()


def main() -> int:
    configure_base()
    receipt = v3.main()
    return receipt


if __name__ == "__main__":
    raise SystemExit(main())
