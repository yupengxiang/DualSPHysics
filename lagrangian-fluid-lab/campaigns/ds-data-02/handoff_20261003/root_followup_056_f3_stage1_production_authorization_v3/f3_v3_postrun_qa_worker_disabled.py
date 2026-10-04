#!/usr/bin/env python3
"""Bounded metadata-only post-run QA gate for the F3 v3 package.

This module is intentionally disabled.  It records the checks that must be
supplied after an actual complete case run, while refusing to launch a solver,
read raw particle arrays, infer loss, or create an approval.  Root can use the
returned checklist when attaching the real typed/native and visual evidence to
one of the five prospective cases.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping


HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "F3_FIRST8_V3_CASE_MANIFEST.json"
ENABLED = False
PROSPECTIVE_CASE_IDS = (
    "F3_STAGE1_DP006_P1000_AY0320",
    "F3_STAGE1_DP006_P1000_AY0390",
    "F3_STAGE1_DP006_P1000_AY0460",
    "F3_STAGE1_DP006_P1000_AY0570",
    "F3_STAGE1_DP006_P1000_AY0640",
)


class DisabledQAError(ValueError):
    """Raised for malformed metadata or an attempt to treat this as a runner."""


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DisabledQAError(message)


def checklist(case_id: str, *, postrun_evidence: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Return a bounded QA checklist without executing or authorizing a case.

    ``postrun_evidence`` is deliberately optional and is not synthesized from
    the initial metadata.  When supplied, the worker only checks that the
    caller explicitly reports the required fields; it does not certify them.
    """

    _require(ENABLED is False, "the bounded QA worker must remain disabled")
    _require(case_id in PROSPECTIVE_CASE_IDS, f"unknown prospective case: {case_id}")
    manifest = _load(MANIFEST)
    row = next((item for item in manifest.get("cases", []) if item.get("case_id") == case_id), None)
    _require(isinstance(row, Mapping), f"manifest row is missing: {case_id}")
    _require(row.get("production_approval") == "none", f"{case_id} already claims approval")
    _require(row.get("root_visual_decision") is None, f"{case_id} already has a visual decision")
    _require(row.get("full_saved_frame_integrity") is None, f"{case_id} already has a frame report")

    required = {
        "execution_receipt_with_returncode_zero",
        "typed_native_identity_report",
        "complete_event_window_report",
        "all_original_saved_frames_integrity_report",
        "finite_state_and_no_overlap_report",
        "root_visual_decision",
    }
    supplied = set(postrun_evidence or {})
    return {
        "schema": "ds02.stage1.f3.disabled-postrun-qa-checklist.v1",
        "status": "disabled_pending_actual_complete_run",
        "enabled": False,
        "execution_allowed": False,
        "production_scope_approval": False,
        "case_id": case_id,
        "initial_metadata_only": True,
        "raw_particle_arrays_read": False,
        "unknown_loss_preserved": True,
        "required_after_actual_complete_run": sorted(required),
        "supplied_evidence_keys": sorted(supplied),
        "all_required_evidence_supplied": supplied == required,
        "approval_created": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-id", choices=PROSPECTIVE_CASE_IDS)
    args = parser.parse_args(argv)
    case_ids = (args.case_id,) if args.case_id else PROSPECTIVE_CASE_IDS
    print(json.dumps({case_id: checklist(case_id) for case_id in case_ids}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
