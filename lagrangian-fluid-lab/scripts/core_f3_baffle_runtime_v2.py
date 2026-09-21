#!/usr/bin/env python3
"""Normals-aware v2 profile for the F3 baffle runtime adapter.

The execution and obstacle audit implementation remains the reviewed F3 core
adapter, while this profile binds a new prepared revision and case identity.
The profile is deliberately narrow: one Ada anchor, the existing 15-row
matrix and denominator, zero matrix credit, and no T1 or registry mutation.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import sys
from typing import Any, Iterator

LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts import core_f3_baffle_runtime as base


SCHEMA = "core.f3.baffle_exchange.runtime_adapter.v2"
REVISION_ID = "F3_baffle_exchange_native_mdbc_normals_v2"
TARGET_CASE_ID = "CORE_F3_BAFFLE_EXCHANGE_q0p50000000_dp0p007500000000_anchor_normals_v2"
TARGET_JOB_ID = "f3-baffle-exchange-q0p5-dp0075-anchor-normals-v2-canary-001"
PARENT_REVISION_ID = "F3_baffle_exchange_native_mdbc_v1"


@contextmanager
def _v2_profile() -> Iterator[None]:
    """Temporarily configure the shared implementation without global leakage."""
    names = ("REVISION_ID", "TARGET_CASE_ID", "TARGET_JOB_ID")
    saved = {name: getattr(base, name) for name in names}
    base.REVISION_ID = REVISION_ID
    base.TARGET_CASE_ID = TARGET_CASE_ID
    base.TARGET_JOB_ID = TARGET_JOB_ID
    try:
        yield
    finally:
        for name, value in saved.items():
            setattr(base, name, value)


def _verify_profile_binding(review: dict[str, Any]) -> None:
    if review.get("revision_id") != REVISION_ID:
        raise ValueError("v2 root review revision mismatch")
    if review.get("authorized_case_ids") != [TARGET_CASE_ID]:
        raise ValueError("v2 root review case mismatch")
    profile = review.get("runtime_adapter_profile", {})
    if profile.get("revision_id") != REVISION_ID or profile.get("parent_revision_id") != PARENT_REVISION_ID:
        raise ValueError("v2 runtime profile binding is incomplete")
    item = review.get("runtime_adapter_wrapper", {})
    path = Path(item.get("path", "")).resolve()
    expected = item.get("sha256")
    live = Path(__file__).resolve()
    if expected != base.digest(live):
        raise ValueError("v2 runtime adapter profile hash is stale")
    if path != live and (not path.is_file() or base.digest(path) != expected):
        raise ValueError("v2 runtime adapter profile source is not a matching file")


def verify_bindings(*, candidate_path: Path, matrix_path: Path, denominator_path: Path,
                    prepared_path: Path, review_path: Path) -> dict[str, Any]:
    with _v2_profile():
        binding = base.verify_bindings(candidate_path=Path(candidate_path), matrix_path=Path(matrix_path),
                                       denominator_path=Path(denominator_path), prepared_path=Path(prepared_path),
                                       review_path=Path(review_path))
    _verify_profile_binding(binding["review"])
    if binding["prepared"].get("parent_revision_id") != PARENT_REVISION_ID:
        raise ValueError("prepared v2 parent revision binding is missing")
    binding["adapter_profile"] = {"schema": SCHEMA, "path": str(Path(__file__).resolve()),
                                  "sha256": base.digest(Path(__file__)),
                                  "revision_id": REVISION_ID, "parent_revision_id": PARENT_REVISION_ID}
    return binding


def build_job(*, lab: Path, candidate: Path, matrix: Path, denominator: Path,
              prepared: Path, review: Path, output: Path) -> dict[str, Any]:
    with _v2_profile():
        spec = base.build_job(lab=Path(lab), candidate=Path(candidate), matrix=Path(matrix),
                              denominator=Path(denominator), prepared=Path(prepared), review=Path(review),
                              output=Path(output))
    spec["schema_adapter"] = SCHEMA
    spec["runtime_adapter_profile"] = {
        "path": str(Path(__file__).resolve()), "sha256": base.digest(Path(__file__)),
        "revision_id": REVISION_ID, "parent_revision_id": PARENT_REVISION_ID,
    }
    spec["parent_revision_id"] = PARENT_REVISION_ID
    # The shared implementation's argv points at its core entrypoint.  The
    # worker must execute this v2 profile so the prepared/review identity is
    # selected before the core verifier runs.
    spec["argv"][1] = str(Path(__file__).resolve())
    profile_ref = base.ref(Path(__file__), "F3 baffle normals-aware v2 runtime adapter profile")
    if not any(item.get("path") == profile_ref["path"] for item in spec["input_files"]):
        spec["input_files"].append(profile_ref)
    from scripts.core_runtime import validate_spec
    validate_spec(json.loads(json.dumps(spec, allow_nan=False)))
    base.write_json(Path(output), spec, overwrite=True)
    return spec


def run_canary(*, lab: Path, candidate: Path, matrix: Path, denominator: Path,
               prepared: Path, review: Path, output: Path) -> dict[str, Any]:
    with _v2_profile():
        result = base.run_canary(lab=Path(lab), candidate=Path(candidate), matrix=Path(matrix),
                                 denominator=Path(denominator), prepared=Path(prepared), review=Path(review),
                                 output=Path(output))
    result.setdefault("source_hashes", {})["adapter_profile"] = base.digest(Path(__file__))
    result["source_hashes"]["adapter_profile_path"] = str(Path(__file__).resolve())
    result["schema"] = "core.f3.baffle_exchange.runtime_result.v2"
    base.write_json(Path(output) / "result.json", result, overwrite=True)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-root", type=Path, default=LAB_ROOT)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("dry-run", "make-job", "run"):
        p = sub.add_parser(command)
        p.add_argument("--candidate", type=Path, required=True)
        p.add_argument("--matrix", type=Path, required=True)
        p.add_argument("--denominator", type=Path, required=True)
        p.add_argument("--prepared", type=Path, required=True)
        p.add_argument("--root-review", type=Path, required=True)
        p.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    kwargs = {"candidate_path": args.candidate, "matrix_path": args.matrix,
              "denominator_path": args.denominator, "prepared_path": args.prepared,
              "review_path": args.root_review}
    if args.command == "dry-run":
        binding = verify_bindings(**kwargs)
        print(json.dumps({"schema": SCHEMA, "status": "dry_run_pass", "matrix_index": base.TARGET_MATRIX_INDEX,
                          "case_id": binding["prepared"]["case_id"], "revision_id": REVISION_ID,
                          "matrix_credit": 0, "normal_geometry": binding["prepared"].get("normal_geometry")}, indent=2))
        return 0
    common = {"lab": args.lab_root.resolve(), "candidate": args.candidate, "matrix": args.matrix,
              "denominator": args.denominator, "prepared": args.prepared, "review": args.root_review,
              "output": args.output}
    if args.command == "make-job":
        spec = build_job(**common)
        print(json.dumps({"schema": SCHEMA, "status": "job_spec_written", "job_id": spec["job_id"],
                          "matrix_index": spec["matrix_index"], "revision_id": spec["revision_id"],
                          "matrix_credit": spec["matrix_credit"]}, indent=2))
        return 0
    result = run_canary(**common)
    print(json.dumps({"schema": SCHEMA, "status": "completed", "case_id": result["case_id"],
                      "hard_integrity_pass": result["hard_integrity_pass"],
                      "requested_horizon_reached": result["requested_horizon_reached"],
                      "event_window_complete": result["event_window_complete"], "matrix_credit": 0}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
