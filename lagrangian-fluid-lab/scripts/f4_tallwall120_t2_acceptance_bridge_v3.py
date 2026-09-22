#!/usr/bin/env python3
"""Build the current F4 bridge v3 in a new read-only evidence namespace."""
from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any, Iterator

from scripts import f4_tallwall120_t2_acceptance_bridge_v1 as _legacy
from scripts import f4_tallwall120_t2_admission_acceptance_gap_audit_v3 as _current_gap


SCHEMA = "core.material.f4.tallwall120.t2_acceptance_bridge.v3"
ENGINEERING_RECEIPT_SCHEMA = "core.material.f4.tallwall120.engineering_receipt.v3"
FORMAL_RECEIPT_SCHEMA = "core.material.f4.tallwall120.scientific_acceptance_receipt.v3"
GAP_SCHEMA = _current_gap.SCHEMA
DEFAULT_OUTPUT_NAME = (
    "campaigns/core-v1/material/evidence/"
    "f4-tallwall120-t2-acceptance-bridge-v1-20260923-v5.json"
)
DEFAULT_REPORT_NAME = "reports/F4-TALLWALL120-T2-ACCEPTANCE-BRIDGE-2026-09-23-v5.zh-CN.md"
INPUTS = dict(_legacy.INPUTS)
INPUTS.update({
    "t2_gap_audit": Path(_current_gap.DEFAULT_OUTPUT_NAME),
    "gap_audit_report_reference": Path(_current_gap.DEFAULT_REPORT_NAME),
    "bridge_implementation": Path("scripts/f4_tallwall120_t2_acceptance_bridge_v3.py"),
})


@contextlib.contextmanager
def _current_configuration() -> Iterator[None]:
    previous = {name: getattr(_legacy, name) for name in (
        "SCHEMA", "ENGINEERING_RECEIPT_SCHEMA", "FORMAL_RECEIPT_SCHEMA", "GAP_SCHEMA",
        "DEFAULT_OUTPUT_NAME", "DEFAULT_REPORT_NAME", "INPUTS"
    )}
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
        return _legacy.render_report(value, evidence_path).replace("2026-09-22", "2026-09-23")


def write_artifacts(value: dict[str, Any], output: Path, report: Path) -> None:
    with _current_configuration():
        _legacy.write_artifacts(value, output, report)


def verify_receipt(path: Path, lab_root: Path) -> dict[str, Any]:
    with _current_configuration():
        return _legacy.verify_receipt(path, lab_root)


def main(argv: list[str] | None = None) -> int:
    with _current_configuration():
        return _legacy.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
