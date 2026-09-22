#!/usr/bin/env python3
"""Build the v3 current F4 gap-audit namespace without rewriting receipts."""
from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Any, Iterator

from scripts import f4_tallwall120_t2_admission_acceptance_gap_audit_v2 as _legacy


SCHEMA = "core.material.f4.tallwall120.t2_admission_acceptance_gap_audit.v3"
DEFAULT_OUTPUT_NAME = (
    "campaigns/core-v1/material/evidence/"
    "f4-tallwall120-t2-admission-acceptance-gap-audit-20260923-v4.json"
)
DEFAULT_REPORT_NAME = (
    "reports/F4-TALLWALL120-T2-ADMISSION-ACCEPTANCE-GAP-AUDIT-2026-09-23-v4.zh-CN.md"
)
INPUTS = dict(_legacy.INPUTS)


@contextlib.contextmanager
def _current_configuration() -> Iterator[None]:
    previous = {name: getattr(_legacy, name) for name in (
        "SCHEMA", "DEFAULT_OUTPUT_NAME", "DEFAULT_REPORT_NAME", "INPUTS"
    )}
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
        return _legacy.render_report(audit, evidence_path).replace("2026-09-22", "2026-09-23")


def write_artifacts(value: dict[str, Any], output: Path, report: Path) -> None:
    output, report = Path(output).resolve(), Path(report).resolve()
    if output.exists() or report.exists():
        raise FileExistsError("refusing to overwrite an existing gap audit artifact")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(value, output), encoding="utf-8")
