#!/usr/bin/env python3
"""Prepare a conservative seven-family streaming raw-anchor plan.

The v14 anchor files are source-bound plans, not completed reconstructions.
This planner connects all seven exact CURRENT rows to a single streaming
operator contract: decode one native ``Part_%04d.bi4`` at a time, update the
typed output in bounded particle chunks, compare fixed identity/lifecycle
fields, then run labels only after the raw producer tree and reference source
are parent-verified.  It does not open BI4/HDF5 and it does not invent a
family-specific request where that request has not been source-closed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA = "ds02.stage2.seven-family-raw-anchor-stream-plan.v1"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
FAMILIES = tuple(f"F{index}" for index in range(1, 8))


class RawAnchorStreamPlanError(ValueError):
    """Raised when one of the seven exact anchor plans is incomplete."""


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha(value: Mapping[str, Any]) -> str:
    payload = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def _load(path: Path | str) -> dict[str, Any]:
    value = json.loads(Path(path).expanduser().resolve().read_text())
    if not isinstance(value, dict):
        raise RawAnchorStreamPlanError(f"JSON object required: {path}")
    return value


def _write_new(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        raise RawAnchorStreamPlanError(f"refusing to overwrite output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def build(index_path: Path | str, output_path: Path | str) -> dict[str, Any]:
    index_file = Path(index_path).expanduser().resolve()
    output_file = Path(output_path).expanduser().resolve()
    index = _load(index_file)
    if index.get("schema") != "ds02.stage2.family-raw-anchor-plan-index.v1" or index.get("seven_family_coverage") is not True:
        raise RawAnchorStreamPlanError("seven-family anchor index schema/coverage is invalid")
    rows = index.get("families")
    if not isinstance(rows, list) or len(rows) != 7:
        raise RawAnchorStreamPlanError("exactly seven anchor rows are required")
    jobs: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping) or row.get("family_id") not in FAMILIES:
            raise RawAnchorStreamPlanError("anchor row has an unknown family")
        family = str(row["family_id"])
        if family in jobs:
            raise RawAnchorStreamPlanError(f"duplicate family anchor: {family}")
        plan_path = Path(str(row.get("path", ""))).expanduser().resolve()
        if not plan_path.is_file():
            raise RawAnchorStreamPlanError(f"anchor plan is missing: {plan_path}")
        plan = _load(plan_path)
        anchor = plan.get("anchor_case")
        raw = plan.get("raw_anchor")
        if not isinstance(anchor, Mapping) or not isinstance(raw, Mapping):
            raise RawAnchorStreamPlanError(f"anchor/raw metadata is missing: {family}")
        if anchor.get("current_index") != row.get("anchor_current_index"):
            raise RawAnchorStreamPlanError(f"CURRENT index differs in {family} anchor")
        if anchor.get("physical_case_id") != row.get("anchor_physical_case_id"):
            raise RawAnchorStreamPlanError(f"physical case differs in {family} anchor")
        if raw.get("frame_count_expected") != anchor.get("frames"):
            raise RawAnchorStreamPlanError(f"frame count differs in {family} anchor")
        if raw.get("raw_root") != row.get("raw_root") or raw.get("raw_root_exists") is not True:
            raise RawAnchorStreamPlanError(f"raw root binding differs or is not present in {family} anchor")
        jobs[family] = {
            "family_id": family,
            "current_index": int(anchor["current_index"]),
            "physical_case_id": anchor["physical_case_id"],
            "runtime_case_alias": anchor.get("runtime_case_alias"),
            "frames": int(anchor["frames"]),
            "particles": int(anchor["particles"]),
            "time_window_s": anchor.get("actual_time_window_s"),
            "raw_root_path_provenance": raw.get("raw_root"),
            "raw_frame_pattern": raw.get("frame_pattern"),
            "required_source_arrays": raw.get("required_source_arrays"),
            "anchor_plan_path": str(plan_path),
            "anchor_plan_sha256": sha256_file(plan_path),
            "selection_policy": plan.get("selection_policy"),
            "status": "F2_REQUEST_READY" if family == "F2" else "PLAN_ONLY_FAMILY_REQUEST_PENDING",
            "unknown_scope": plan.get("unknown_scope", []),
        }
    report = {
        "schema": SCHEMA,
        "status": "SEVEN_FAMILY_STREAMING_PLAN; PARENT_GUARD_REQUIRED; QUALIFICATION_UNKNOWN",
        "source_index": {"path": str(index_file), "sha256": sha256_file(index_file),
                         "raw_read_status": index.get("raw_read_status")},
        "jobs": [jobs[family] for family in FAMILIES],
        "stream_operator_contract": {
            "frame_input": "exact Part_%04d.bi4 rows from bound raw_root; all frames once",
            "partout_runparts": "provenance only; never typed source arrays",
            "decoder": "bound BI4 decoder and source SHA required per family",
            "typed_write": "new HDF5/output only; particle chunks bounded and identity axis fixed (Zone,Idp)",
            "lifecycle": "valid=false retains identity; physical state/fate remains unknown",
            "comparison": "reference HDF5 full SHA/stat and per-frame identity/lifecycle/numeric compare under parent guard",
            "labels": "v15/v16 only after typed comparison; evaluator optional and development-only",
            "resume": "cache per-frame SHA plus before/after tree digest; resume only when exact source stat/hash and unchanged tree are proven",
            "path_policy": "CURRENT-bound source paths; no latest glob, arbitrary Run.out, or fixed legacy case list",
        },
        "resource_contract": {
            "particle_chunk": 65536,
            "read_pattern": "one frame then bounded particle chunks; do not materialize full timeline arrays",
            "rss_policy": "parent guard records ru_maxrss; no unclaimed hard RSS enforcement",
            "output_policy": "new output root only; raw/typed/labels/access receipts retained",
        },
        "seven_family_execution_boundary": {
            "completed_raw_reconstructions": 0,
            "family_specific_parent_guard_requests": ["F2"],
            "remaining_plan_only_families": [family for family in FAMILIES if family != "F2"],
            "qualification": UNKNOWN,
        },
        "qualification": UNKNOWN,
        "model_invoked": False,
        "cfd_invoked": False,
        "limitations": [
            "Anchor plans and this stream route are development metadata; they do not constitute seven raw reconstructions.",
            "F2 is ready through the separate v4 source-bound request; F1/F3/F4/F5/F6/F7 still need family-specific raw/H5/receipt closure.",
            "Recovery, cross-resolution equivalence, prospective split safety, and QI/QN/QE remain UNKNOWN.",
        ],
    }
    report["sha256"] = canonical_sha(report)
    _write_new(output_file, report)
    return {"path": str(output_file), "sha256": report["sha256"], "jobs": len(jobs)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--anchor-index", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = build(args.anchor_index, args.output)
    except (OSError, json.JSONDecodeError, RawAnchorStreamPlanError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
