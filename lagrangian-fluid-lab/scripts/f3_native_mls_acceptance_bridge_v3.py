#!/usr/bin/env python3
"""Version v3 of the read-only F3 native-MLS acceptance reconciliation.

It creates a new hash-bound namespace after the material reliability-censoring
implementation changed.  Historical v2 receipts are immutable.
"""
from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any, Iterator

from scripts import f3_native_mls_acceptance_bridge_v2 as _legacy


SCHEMA = "core.material.f3.native_volume_mls.acceptance_bridge.v3"
RECEIPT_SCHEMA = "core.material.f3.native_volume_mls.acceptance_reconciliation.v2"
DEFAULT_OUTPUT_NAME = (
    "campaigns/core-v1/material/evidence/"
    "f3-native-mls-acceptance-bridge-v3/reconciliation-v2-20260923.json"
)
DEFAULT_REPORT_NAME = "reports/F3-NATIVE-MLS-ACCEPTANCE-BRIDGE-V3-2026-09-23.zh-CN.md"
INPUTS = dict(_legacy.INPUTS)
INPUTS["bridge_implementation"] = Path("scripts/f3_native_mls_acceptance_bridge_v3.py")


@contextlib.contextmanager
def _current_configuration() -> Iterator[None]:
    previous = {name: getattr(_legacy, name) for name in (
        "SCHEMA", "RECEIPT_SCHEMA", "DEFAULT_OUTPUT_NAME", "DEFAULT_REPORT_NAME", "INPUTS"
    )}
    _legacy.SCHEMA = SCHEMA
    _legacy.RECEIPT_SCHEMA = RECEIPT_SCHEMA
    _legacy.DEFAULT_OUTPUT_NAME = DEFAULT_OUTPUT_NAME
    _legacy.DEFAULT_REPORT_NAME = DEFAULT_REPORT_NAME
    _legacy.INPUTS = INPUTS
    try:
        yield
    finally:
        for name, value in previous.items():
            setattr(_legacy, name, value)


def build_reconciliation(lab_root: Path) -> dict[str, Any]:
    with _current_configuration():
        return _legacy.build_reconciliation(lab_root)


def render_report(value: dict[str, Any], evidence_path: Path) -> str:
    with _current_configuration():
        return _legacy.render_report(value, evidence_path).replace(
            "F3 native-MLS acceptance bridge v2/source-closure reconciliation（2026-09-22）",
            "F3 native-MLS acceptance bridge v3/source-closure reconciliation（2026-09-23）",
        )


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
