#!/usr/bin/env python3
"""Current v4 F3 reconciliation: a new hash-bound, zero-credit namespace."""
from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any, Iterator

from scripts import f3_native_mls_acceptance_bridge_v3 as _legacy


SCHEMA = "core.material.f3.native_volume_mls.acceptance_bridge.v4"
RECEIPT_SCHEMA = "core.material.f3.native_volume_mls.acceptance_reconciliation.v3"
UNKNOWN_LIMIT = _legacy._legacy.UNKNOWN_LIMIT
CDF_LIMIT = _legacy._legacy.CDF_LIMIT
NATIVE_INTERVAL_S = _legacy._legacy.NATIVE_INTERVAL_S
FULL_WINDOW_S = _legacy._legacy.FULL_WINDOW_S
DEFAULT_OUTPUT_NAME = (
    "campaigns/core-v1/material/evidence/"
    "f3-native-mls-acceptance-bridge-v4/reconciliation-v3-20260923.json"
)
DEFAULT_REPORT_NAME = "reports/F3-NATIVE-MLS-ACCEPTANCE-BRIDGE-V4-2026-09-23.zh-CN.md"
INPUTS = dict(_legacy.INPUTS)
INPUTS["bridge_implementation"] = Path("scripts/f3_native_mls_acceptance_bridge_v4.py")


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
        return _legacy.render_report(value, evidence_path).replace("bridge v3", "bridge v4")


def write_artifacts(value: dict[str, Any], output: Path, report: Path) -> None:
    output, report = Path(output).resolve(), Path(report).resolve()
    if output.exists() or report.exists():
        raise FileExistsError("refusing to overwrite versioned reconciliation artifacts")
    import json
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(value, output), encoding="utf-8")


def verify_receipt(path: Path, lab_root: Path) -> dict[str, Any]:
    with _current_configuration():
        return _legacy.verify_receipt(path, lab_root)


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parents[1]
    parser.add_argument("--lab-root", type=Path, default=root)
    parser.add_argument("--output", type=Path, default=root / DEFAULT_OUTPUT_NAME)
    parser.add_argument("--report", type=Path, default=root / DEFAULT_REPORT_NAME)
    args = parser.parse_args(argv)
    write_artifacts(build_reconciliation(args.lab_root.resolve()), args.output, args.report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
