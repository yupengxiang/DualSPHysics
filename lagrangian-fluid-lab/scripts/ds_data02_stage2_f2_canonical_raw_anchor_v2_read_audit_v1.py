#!/usr/bin/env python3
"""Record what the consumed v2 canonical-anchor planner actually read.

The v2 planner predates the stat-only v3 boundary.  Its ``_stat_ref`` helper
hashes selected scientific-looking files when they are below its size
threshold.  This small audit reads only the bounded v2 plan JSON and the
planner source; it never opens a native, CSV, BI4, HDF5, or other payload
path named by the plan.  It exists to keep the historical read fact explicit
when the v3 plan is reviewed.

The report is diagnostic provenance.  It does not retroactively make the v2
request parent-verified and it grants no raw, typed, or label credit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA = "ds02.stage2.f2-canonical-raw-anchor-v2-read-audit.v1"
PLAN_SCHEMA = "ds02.stage2.f2-canonical-raw-anchor-plan.v2"
MAX_JSON_BYTES = 8 * 1024 * 1024
EXPECTED = {
    "motion_dat": {
        "bytes": 14862,
        "sha256": "60eb2187d06f6e688afc336a6a3722fa7026a4f86cc03b9732760dfa6d87b438",
        "read_by_planner": True,
        "status": "CONTENT_SHA_OBSERVED",
    },
    "initial_csv": {
        "bytes": 59656846,
        "sha256": None,
        "read_by_planner": False,
        "status": "PARENT_GUARD_REQUIRED",
    },
    "native_partout": {
        "bytes": 7173,
        "sha256": "248ef327921332beda7efec30ded7612d0d2f6687882a96c40067a0ca04f7b97",
        "read_by_planner": True,
        "status": "CONTENT_SHA_OBSERVED",
    },
    "native_runparts": {
        "bytes": 87821,
        "sha256": "194befc7b5d748289a0a43d45996a4daf024db662d51f2f4ed1659913e84c9c6",
        "read_by_planner": True,
        "status": "CONTENT_SHA_OBSERVED",
    },
}


class AuditError(ValueError):
    """The historical plan does not match the recorded v2 contract."""


def _read_json(path: Path, role: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise AuditError(f"{role} must be a regular file: {path}")
    if path.stat().st_size > MAX_JSON_BYTES:
        raise AuditError(f"{role} exceeds the bounded JSON limit")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise AuditError(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise AuditError(f"{role} must be a JSON object")
    return value


def _canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True).encode("utf-8")).hexdigest()


def _source_records(plan: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    # The v2 plan duplicated the same roles in the request and in the
    # planner-side ``source_bindings``.  The latter is the record that carries
    # the planner's read-status flags, so use it for this historical audit;
    # the request's optimistic parent flag is checked separately below.
    values = plan.get("source_bindings")
    if not isinstance(values, list):
        raise AuditError("v2 request source_files are missing")
    records: dict[str, Mapping[str, Any]] = {}
    for value in values:
        if isinstance(value, Mapping) and isinstance(value.get("role"), str):
            records[str(value["role"])] = value
    return records


def audit(*, plan_path: Path, planner_source_path: Path) -> dict[str, Any]:
    """Audit v2 metadata without reading any path named as a scientific input."""
    plan = _read_json(plan_path, "v2 plan")
    if plan.get("schema") != PLAN_SCHEMA:
        raise AuditError("plan is not the consumed v2 canonical-anchor schema")
    source = planner_source_path.read_text(encoding="utf-8")
    # These source markers are the code-level evidence for the read behavior;
    # the audit never calls the old planner and never opens its payload paths.
    if "CONTENT_SHA_OBSERVED" not in source or "_sha256(path)" not in source:
        raise AuditError("v2 planner source does not expose its content-hash branch")
    records = _source_records(plan)
    observed: list[dict[str, Any]] = []
    for role, expected in EXPECTED.items():
        item = records.get(role)
        if item is None:
            raise AuditError(f"v2 plan is missing source role {role}")
        for key in ("bytes", "sha256"):
            if item.get(key) != expected[key]:
                raise AuditError(f"v2 {role}.{key} differs from the recorded plan")
        actual_read = item.get("content_read_by_planner") is True
        actual_status = item.get("content_sha_status")
        if actual_read != expected["read_by_planner"] or actual_status != expected["status"]:
            raise AuditError(f"v2 {role} read status differs from the recorded plan")
        observed.append({
            "role": role,
            "path": item.get("path"),
            "bytes": expected["bytes"],
            "sha256": expected["sha256"],
            "content_sha_status": expected["status"],
            "content_read_by_planner": expected["read_by_planner"],
            "payload_opened_by_this_audit": False,
        })
    request = plan.get("request_overlay", {}).get("request", {})
    declared_preverified = request.get("source_hashes_preverified_by_parent")
    report = {
        "schema": SCHEMA,
        "status": "HISTORICAL_V2_READ_FACT_RECORDED",
        "plan": {"path": str(plan_path), "schema": PLAN_SCHEMA},
        "planner_source": {"path": str(planner_source_path),
                           "sha256": hashlib.sha256(source.encode("utf-8")).hexdigest()},
        "observed_source_roles": observed,
        "initial_csv_policy": {
            "bytes": EXPECTED["initial_csv"]["bytes"],
            "sha256": None,
            "content_read_by_planner": False,
            "status": "PARENT_GUARD_REQUIRED",
        },
        "v2_request_claim": {
            "source_hashes_preverified_by_parent": declared_preverified,
            "corrected_value": False,
            "reason": "v2 stored content observations before any parent reservation; these are historical planner reads, not a parent guard proof",
        },
        "scientific_credit": "NONE",
        "payload_opened_by_audit": False,
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    report["sha256"] = _canonical_sha(report)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--planner-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = audit(plan_path=args.plan, planner_source_path=args.planner_source)
        if args.output.exists():
            raise AuditError(f"refusing to overwrite {args.output}")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except (OSError, AuditError) as error:
        parser.error(str(error))
    print(json.dumps({"schema": report["schema"], "status": report["status"],
                      "sha256": report["sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
