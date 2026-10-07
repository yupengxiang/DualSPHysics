#!/usr/bin/env python3
"""Read-only validator for the fresh218 source package and its output.

The validator validates JSON metadata and filesystem metadata only.  It never
opens scientific payloads and never writes outside the caller-provided toy
output directory (the package itself is never modified).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

PACKAGE_SCHEMA = "ds02.f5.fresh218.final48.runtime-bed-primary-gate-repair.v1"
FORBIDDEN = {".h5", ".hdf5", ".bi4", ".ibi4", ".csv", ".dat", ".vtk", ".vtu", ".pvtu", ".pvd"}


class ValidationError(RuntimeError):
    pass


def fail(message: str) -> None:
    raise ValidationError(message)


def load(path: Path) -> Any:
    if not path.is_file():
        fail(f"missing JSON: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"invalid JSON {path}: {exc}")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_catalog(path: Path) -> dict[str, Any]:
    cat = load(path)
    if cat.get("schema") != PACKAGE_SCHEMA:
        fail("catalog schema mismatch")
    if cat.get("status") not in {"readiness", "complete"}:
        fail("catalog status must be readiness or complete")
    if cat.get("complete") is not (cat.get("status") == "complete"):
        fail("complete flag disagrees with status")
    cases = cat.get("cases")
    if not isinstance(cases, list) or len(cases) != 48:
        fail("catalog must contain exactly 48 cases")
    membership = cat.get("membership")
    if not isinstance(membership, dict):
        fail("membership object missing")
    first8 = membership.get("frozen_first8_physical_case_ids")
    first24 = membership.get("actual_first24_physical_case_ids")
    final48 = membership.get("registered_final48_physical_case_ids")
    if not (isinstance(first8, list) and isinstance(first24, list) and isinstance(final48, list)):
        fail("membership arrays missing")
    if (len(first8), len(first24), len(final48)) != (8, 24, 48):
        fail("membership counts are not 8/24/48")
    if len(set(first8)) != 8 or len(set(first24)) != 24 or len(set(final48)) != 48:
        fail("membership arrays contain duplicates")
    if not set(first8) <= set(first24) <= set(final48):
        fail("membership subset relation failed")
    if [c.get("physical_case_id") for c in cases] != final48:
        fail("case order does not preserve frozen registered_final48 order")
    if cat.get("accepted_count") + cat.get("pending_count") != 48:
        fail("accepted/pending counts do not sum to 48")
    actual_accepted = sum(c.get("accepted") is True for c in cases)
    if actual_accepted != cat.get("accepted_count"):
        fail("accepted_count disagrees with case rows")
    if cat.get("new_case_credit") != 0 or cat.get("Q_N") != 0 or cat.get("Q_E") != 0:
        fail("catalog grants credit or qualification")
    if cat.get("scientific_payload_IO") is not False:
        fail("catalog scientific_payload_IO must be false")
    if not isinstance(cat.get("source180_gate_defect_audit"), dict):
        fail("source180 audit reference missing")
    audit_summary = cat.get("source180_audit_summary")
    if not isinstance(audit_summary, dict) or audit_summary.get("approved_as_readiness_only") is not True:
        fail("source180 readiness-only audit summary missing")
    gate = cat.get("completion_gate")
    if not isinstance(gate, dict) or gate.get("requires_execution_receipt_schema") != "ds02.execution-receipt.v1":
        fail("strict execution receipt gate missing")
    if cat.get("status") == "readiness" and cat.get("complete") is not False:
        fail("readiness catalog cannot be complete")
    for case in cases:
        if not isinstance(case, dict):
            fail("case is not an object")
        if case.get("case_credit") != 0:
            fail(f"case credit is nonzero: {case.get('physical_case_id')}")
        gate = case.get("fulltime_gate")
        if not isinstance(gate, dict) or not isinstance(gate.get("pass"), bool):
            fail(f"fulltime gate missing: {case.get('physical_case_id')}")
        evidence = case.get("actual_evidence")
        if not isinstance(evidence, dict):
            fail(f"actual evidence missing: {case.get('physical_case_id')}")
        for value in evidence.values():
            if not isinstance(value, dict):
                continue
            probe = value.get("metadata_probe")
            if isinstance(probe, dict) and probe.get("content_read_or_hashed") and Path(value.get("path", "")).suffix.lower() in FORBIDDEN:
                fail(f"scientific payload read/hash claimed: {value.get('path')}")
        if cat.get("complete"):
            if case.get("accepted") is not True or gate.get("pass") is not True:
                fail(f"complete catalog contains non-passing case: {case.get('physical_case_id')}" )
    return cat


def validate_source(package: Path) -> list[str]:
    required = ["build_fresh218.py", "validate_fresh218.py", "README.md", "package-manifest.json", "tests/test_fresh218_contract.py", "metadata/source180-audit-reference.json"]
    missing = [name for name in required if not (package / name).is_file()]
    if missing:
        fail(f"source package missing: {missing}")
    build_text = (package / "build_fresh218.py").read_text(encoding="utf-8")
    for flag in ("--checkpoint", "--current-index", "--membership", "--legacy-catalog", "--source-audit", "--output-dir"):
        if flag not in build_text:
            fail(f"builder does not expose required CLI flag: {flag}")
    if "refuse overwrite existing output directory" not in build_text:
        fail("builder output overwrite guard missing")
    required_tokens = (
        'status != "completed"', "returncode", "ds02.execution-receipt.",
        "input_hash_transition_not_stable", "typed_composite_uid_identity_missing",
        "initial_exclusion", "render_frame_selection_not_exact_0_to_800",
        "bed_time_provenance_missing_or_invalid", "primary_visual_gate",
        "source180_not_approved_as_standalone_final48_builder",
    )
    for token in required_tokens:
        if token not in build_text:
            fail(f"strict gate token missing: {token}")
    manifest = load(package / "package-manifest.json")
    if manifest.get("schema") != "ds02.f5.fresh218.package-manifest.v1":
        fail("package manifest schema mismatch")
    entries = manifest.get("files")
    if not isinstance(entries, list):
        fail("package manifest files missing")
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            fail("package manifest entry malformed")
        source = package / entry["path"]
        if not source.is_file():
            fail(f"package manifest file missing: {source}")
        if entry.get("bytes") != source.stat().st_size or entry.get("sha256") != sha(source):
            fail(f"package manifest byte/hash mismatch: {source}")
    return required


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--package", type=Path, default=Path(__file__).resolve().parent)
    p.add_argument("--output-dir", type=Path)
    args = p.parse_args(argv)
    try:
        files = validate_source(args.package.resolve())
        result: dict[str, Any] = {"source": "PASS", "files": files}
        if args.output_dir is not None:
            candidates = [p for p in args.output_dir.iterdir() if p.name.endswith(".json") and p.name in {"readiness.json", "final48.json"}] if args.output_dir.is_dir() else []
            if len(candidates) != 1:
                fail("output directory must contain exactly one readiness.json or final48.json")
            cat = validate_catalog(candidates[0])
            result.update({"output": "PASS", "status": cat["status"], "accepted_count": cat["accepted_count"], "pending_count": cat["pending_count"]})
        print(json.dumps(result, sort_keys=True))
        return 0
    except ValidationError as exc:
        print(f"fresh218 validation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
