#!/usr/bin/env python3
"""Build the current F4 acceptance bridge against the reconciled gap audit."""
from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any, Iterator

from scripts import f4_tallwall120_t2_acceptance_bridge_v1 as _legacy
from scripts import f4_tallwall120_t2_admission_acceptance_gap_audit_v4 as _gap
from scripts.f4_macro_t2_sidecar_preflight_v2 import DEFAULT_OUTPUT, DEFAULT_REPORT


SCHEMA = "core.material.f4.tallwall120.t2_acceptance_bridge.v4"
ENGINEERING_RECEIPT_SCHEMA = "core.material.f4.tallwall120.engineering_receipt.v4"
FORMAL_RECEIPT_SCHEMA = "core.material.f4.tallwall120.scientific_acceptance_receipt.v4"
GAP_SCHEMA = _gap.SCHEMA
DEFAULT_OUTPUT_NAME = Path(
    "campaigns/core-v1/material/evidence/"
    "f4-tallwall120-t2-acceptance-bridge-v1-20260923-v6.json"
)
DEFAULT_REPORT_NAME = Path(
    "reports/F4-TALLWALL120-T2-ACCEPTANCE-BRIDGE-2026-09-23-v6.zh-CN.md"
)
INPUTS = dict(_legacy.INPUTS)
INPUTS.update({
    "t2_gap_audit": _gap.DEFAULT_OUTPUT_NAME,
    "gap_audit_report_reference": _gap.DEFAULT_REPORT_NAME,
    "macro_sidecar_preflight": DEFAULT_OUTPUT,
    "macro_preflight_report_reference": DEFAULT_REPORT,
    "macro_sidecar_preflight_code": Path("scripts/f4_macro_t2_sidecar_preflight_v2.py"),
    "bridge_implementation": Path(__file__),
})


@contextlib.contextmanager
def _current_configuration() -> Iterator[None]:
    names = (
        "SCHEMA", "ENGINEERING_RECEIPT_SCHEMA", "FORMAL_RECEIPT_SCHEMA", "GAP_SCHEMA",
        "DEFAULT_OUTPUT_NAME", "DEFAULT_REPORT_NAME", "INPUTS",
    )
    previous = {name: getattr(_legacy, name) for name in names}
    for name, value in {
        "SCHEMA": SCHEMA,
        "ENGINEERING_RECEIPT_SCHEMA": ENGINEERING_RECEIPT_SCHEMA,
        "FORMAL_RECEIPT_SCHEMA": FORMAL_RECEIPT_SCHEMA,
        "GAP_SCHEMA": GAP_SCHEMA,
        "DEFAULT_OUTPUT_NAME": DEFAULT_OUTPUT_NAME,
        "DEFAULT_REPORT_NAME": DEFAULT_REPORT_NAME,
        "INPUTS": INPUTS,
    }.items():
        setattr(_legacy, name, value)
    try:
        yield
    finally:
        for name, value in previous.items():
            setattr(_legacy, name, value)


def build_bridge(lab_root: str | Path, created_at_utc: str | None = None) -> dict[str, Any]:
    with _current_configuration():
        return _legacy.build_bridge(Path(lab_root), created_at_utc=created_at_utc)


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
