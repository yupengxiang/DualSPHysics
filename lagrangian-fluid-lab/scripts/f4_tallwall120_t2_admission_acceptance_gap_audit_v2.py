#!/usr/bin/env python3
"""Build and verify the current F4 tallwall120 gap-audit namespace.

The v1 builder and its v2 JSON artifact are retained as historical evidence.
This adapter deliberately gives the current snapshot a new schema and output
namespace while reusing the read-only, fail-closed audit implementation.
"""
from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any, Iterator

from scripts import f4_tallwall120_t2_admission_acceptance_gap_audit_v1 as _legacy


SCHEMA = "core.material.f4.tallwall120.t2_admission_acceptance_gap_audit.v2"
DEFAULT_OUTPUT_NAME = (
    "campaigns/core-v1/material/evidence/"
    "f4-tallwall120-t2-admission-acceptance-gap-audit-20260922-v3.json"
)
DEFAULT_REPORT_NAME = (
    "reports/F4-TALLWALL120-T2-ADMISSION-ACCEPTANCE-GAP-AUDIT-2026-09-22-v3.zh-CN.md"
)
INPUTS = dict(_legacy.INPUTS)


@contextlib.contextmanager
def _current_configuration() -> Iterator[None]:
    previous = {
        "SCHEMA": _legacy.SCHEMA,
        "DEFAULT_OUTPUT_NAME": _legacy.DEFAULT_OUTPUT_NAME,
        "DEFAULT_REPORT_NAME": _legacy.DEFAULT_REPORT_NAME,
        "INPUTS": _legacy.INPUTS,
    }
    _legacy.SCHEMA = SCHEMA
    _legacy.DEFAULT_OUTPUT_NAME = DEFAULT_OUTPUT_NAME
    _legacy.DEFAULT_REPORT_NAME = DEFAULT_REPORT_NAME
    _legacy.INPUTS = INPUTS
    try:
        yield
    finally:
        for name, value in previous.items():
            setattr(_legacy, name, value)


def build_audit(lab_root: Path) -> dict[str, Any]:
    with _current_configuration():
        return _legacy.build_audit(lab_root)


def render_report(audit: dict[str, Any], evidence_path: Path) -> str:
    with _current_configuration():
        return _legacy.render_report(audit, evidence_path)


def main() -> int:
    with _current_configuration():
        return _legacy.main()


if __name__ == "__main__":
    raise SystemExit(main())
