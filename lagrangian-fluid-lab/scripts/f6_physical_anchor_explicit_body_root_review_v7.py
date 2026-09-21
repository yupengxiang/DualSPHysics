#!/usr/bin/env python3
"""Prepare F6 explicit-body v7 after the v6 wrapper-order failure."""

from __future__ import annotations

from pathlib import Path
import sys

LAB = Path(__file__).resolve().parents[1]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from scripts import f6_physical_anchor_explicit_body_root_review_v6 as v6  # noqa: E402


ROOT = LAB / "campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-explicit-body-root-review-v7-20260921"
IDENTITY = "CORE_F6_physical_anchor_single_body_gravity_explicit_body_v7_20260921"
BODY_ID = "F6_physical_anchor_body_theta_20260921"
REVISION = "F6_gravity_single_body_entry_buoyancy_explicit_body_endpoint_safe_fluid_v7"
SCRIPT = Path(__file__).resolve()


def configure_base() -> None:
    v6.ROOT = ROOT
    v6.IDENTITY = IDENTITY
    v6.BODY_ID = BODY_ID
    v6.REVISION = REVISION
    v6.SCRIPT = SCRIPT
    v6.configure_base()


def main() -> int:
    configure_base()
    return v6.main()


if __name__ == "__main__":
    raise SystemExit(main())
