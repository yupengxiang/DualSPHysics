#!/usr/bin/env python3
"""Build and verify the current F4 tallwall120 acceptance-bridge namespace.

The v1 bridge and v3 JSON artifact remain immutable historical evidence.  This
current builder binds the current gap-audit namespace and the current material
implementations, while retaining the bridge's read-only and zero-credit
semantics.
"""
from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any, Iterator

from scripts import f4_tallwall120_t2_acceptance_bridge_v1 as _legacy
from scripts import f4_tallwall120_t2_admission_acceptance_gap_audit_v2 as _current_gap


SCHEMA = "core.material.f4.tallwall120.t2_acceptance_bridge.v2"
ENGINEERING_RECEIPT_SCHEMA = "core.material.f4.tallwall120.engineering_receipt.v2"
FORMAL_RECEIPT_SCHEMA = "core.material.f4.tallwall120.scientific_acceptance_receipt.v2"
GAP_SCHEMA = _current_gap.SCHEMA
DEFAULT_OUTPUT_NAME = (
    "campaigns/core-v1/material/evidence/"
    "f4-tallwall120-t2-acceptance-bridge-v1-20260922-v4.json"
)
DEFAULT_REPORT_NAME = "reports/F4-TALLWALL120-T2-ACCEPTANCE-BRIDGE-2026-09-22-v4.zh-CN.md"
INPUTS = dict(_legacy.INPUTS)
INPUTS.update(
    {
        "t2_gap_audit": Path(_current_gap.DEFAULT_OUTPUT_NAME),
        "gap_audit_report_reference": Path(_current_gap.DEFAULT_REPORT_NAME),
        "bridge_implementation": Path("scripts") / Path(__file__).name,
    }
)


@contextlib.contextmanager
def _current_configuration() -> Iterator[None]:
    previous = {
        "SCHEMA": _legacy.SCHEMA,
        "ENGINEERING_RECEIPT_SCHEMA": _legacy.ENGINEERING_RECEIPT_SCHEMA,
        "FORMAL_RECEIPT_SCHEMA": _legacy.FORMAL_RECEIPT_SCHEMA,
        "GAP_SCHEMA": _legacy.GAP_SCHEMA,
        "DEFAULT_OUTPUT_NAME": _legacy.DEFAULT_OUTPUT_NAME,
        "DEFAULT_REPORT_NAME": _legacy.DEFAULT_REPORT_NAME,
        "INPUTS": _legacy.INPUTS,
    }
    _legacy.SCHEMA = SCHEMA
    _legacy.ENGINEERING_RECEIPT_SCHEMA = ENGINEERING_RECEIPT_SCHEMA
    _legacy.FORMAL_RECEIPT_SCHEMA = FORMAL_RECEIPT_SCHEMA
    _legacy.GAP_SCHEMA = GAP_SCHEMA
    _legacy.DEFAULT_OUTPUT_NAME = DEFAULT_OUTPUT_NAME
    _legacy.DEFAULT_REPORT_NAME = DEFAULT_REPORT_NAME
    _legacy.INPUTS = INPUTS
    try:
        yield
    finally:
        for name, value in previous.items():
            setattr(_legacy, name, value)


def build_bridge(lab_root: Path, created_at_utc: str | None = None) -> dict[str, Any]:
    with _current_configuration():
        return _legacy.build_bridge(lab_root, created_at_utc=created_at_utc)


def render_report(value: dict[str, Any], evidence_path: Path) -> str:
    with _current_configuration():
        return _legacy.render_report(value, evidence_path)


def verify_receipt(path: Path, lab_root: Path) -> dict[str, Any]:
    with _current_configuration():
        return _legacy.verify_receipt(path, lab_root)


def write_artifacts(value: dict[str, Any], output: Path, report: Path) -> None:
    with _current_configuration():
        _legacy.write_artifacts(value, output, report)


def main(argv: list[str] | None = None) -> int:
    with _current_configuration():
        return _legacy.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
