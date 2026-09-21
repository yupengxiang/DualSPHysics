#!/usr/bin/env python3
"""Prepare F6 explicit-body v6 with endpoint-safe fluid dimensions."""

from __future__ import annotations

from pathlib import Path
import sys

LAB = Path(__file__).resolve().parents[1]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from scripts import f6_physical_anchor_explicit_body_root_review_v5 as v5  # noqa: E402


ROOT = LAB / "campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-explicit-body-root-review-v6-20260921"
IDENTITY = "CORE_F6_physical_anchor_single_body_gravity_explicit_body_v6_20260921"
BODY_ID = "F6_physical_anchor_body_eta_20260921"
REVISION = "F6_gravity_single_body_entry_buoyancy_explicit_body_endpoint_safe_fluid_v6"
SCRIPT = Path(__file__).resolve()


def configure_base() -> None:
    v5.ROOT = ROOT
    v5.IDENTITY = IDENTITY
    v5.BODY_ID = BODY_ID
    v5.REVISION = REVISION
    v5.SCRIPT = SCRIPT
    v5.configure_base()
    v5.v4.v3.v2.base.FLUID_LOW = (0.18, 0.08, 0.04)
    v5.v4.v3.v2.base.FLUID_SIZE = (1.1399, 0.4399, 0.2399)


def main() -> int:
    configure_base()
    return v5.main()


if __name__ == "__main__":
    raise SystemExit(main())
