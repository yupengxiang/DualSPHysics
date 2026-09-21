#!/usr/bin/env python3
"""Dedicated runtime adapter for the F1 suspended-obstacle scope.

The adapter is intentionally separate from the registered F1 H1 runner.  It
reuses the generic native solver worker and the fixed F1 event observer, then
adds the obstacle penetration/chord audit from ``core_f1.execute_reference``.
It is a runtime entrypoint only: this module never submits a job, updates a
ledger, or edits the central registry.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

LAB = Path(__file__).resolve().parents[1]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from scripts.core_f1 import execute_reference


SCOPE = "F1_suspended_obstacle_gap_v1"
REVISION = "F1_suspended_obstacle_gap_mdbc_v1"


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _verify_root_review(review_path: Path, prepared_path: Path) -> dict:
    """Require an explicit one-anchor root review before touching the solver."""
    review_path = Path(review_path).resolve()
    prepared_path = Path(prepared_path).resolve()
    review = json.loads(review_path.read_text())
    prepared = json.loads(prepared_path.read_text())
    config = prepared.get("config", {})
    if review.get("schema") != "core.root_review.v1":
        raise SystemExit("F1 suspended-obstacle runtime requires core.root_review.v1")
    if review.get("decision") != "approved_for_runtime_smoke":
        raise SystemExit("root review does not approve the protected runtime smoke")
    if review.get("scope_id") != SCOPE or review.get("revision_id") != REVISION:
        raise SystemExit("root review scope/revision mismatch")
    if config.get("scope_id") != SCOPE or config.get("revision_id") != REVISION:
        raise SystemExit("prepared scope/revision mismatch")
    if review.get("qualification_claim") != "none":
        raise SystemExit("root review must keep qualification_claim=none")
    authorization = review.get("authorization", {})
    if authorization.get("solver_launch") is not True or authorization.get("gpu_launch") is not True:
        raise SystemExit("root review does not authorize this runtime anchor")
    if authorization.get("ledger_mutation") not in (False, 0) or authorization.get("registry_mutation") not in (False, 0):
        raise SystemExit("root review permits a forbidden central mutation")
    if review.get("authorized_case_id") != config.get("case_id"):
        raise SystemExit("root review is not bound to this prepared case")
    bindings = review.get("bindings", {})
    expected_prepared = bindings.get("prepared_sha256")
    if expected_prepared != _digest(prepared_path):
        raise SystemExit("prepared hash does not match root review")
    expected_runtime = bindings.get("runtime_adapter_sha256")
    if expected_runtime != _digest(Path(__file__).resolve()):
        raise SystemExit("runtime adapter hash does not match root review")
    candidate = bindings.get("candidate", {})
    matrix = bindings.get("matrix", {})
    for item, label in ((candidate, "candidate"), (matrix, "matrix")):
        path = Path(item.get("path", "")).resolve()
        if not path.is_file() or item.get("sha256") != _digest(path):
            raise SystemExit(f"root review {label} binding is stale")
    if review.get("matrix_submission") is not False:
        raise SystemExit("root review may authorize only one protected anchor")
    return review


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-root", type=Path, required=True)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--root-review", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    _verify_root_review(args.root_review, args.prepared)
    prepared = json.loads(args.prepared.read_text())
    if prepared.get("config", {}).get("scope_id") != SCOPE:
        raise SystemExit("prepared scope does not match the dedicated suspended-obstacle adapter")
    if prepared.get("config", {}).get("recipe") != "mdbc_native":
        raise SystemExit("suspended-obstacle adapter requires the mDBC recipe")
    if not prepared.get("preflight_pass"):
        raise SystemExit("static/native preflight did not pass")
    result = execute_reference(args.prepared.resolve(), args.lab_root.resolve(), args.output.resolve())
    result["runtime_adapter"] = str(Path(__file__).resolve())
    result["runtime_adapter_scope"] = SCOPE
    result["qualification_claim"] = "none; one protected G1 dynamic anchor only"
    result["central_registry_mutated"] = False
    result["central_ledger_mutated"] = False
    result["root_review_path"] = str(args.root_review.resolve())
    result["root_review_sha256"] = _digest(args.root_review)
    # execute_reference has already written result/audit; rewrite the two
    # records with the adapter identity after the generic worker completes.
    for name in ("result.json", "audit.json"):
        path = args.output.resolve() / name
        value = json.loads(path.read_text())
        value.update({k: result[k] for k in ("runtime_adapter", "runtime_adapter_scope", "qualification_claim", "central_registry_mutated", "central_ledger_mutated")})
        path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    print(json.dumps({k: result.get(k) for k in ("hard_integrity_pass", "event_window_complete", "event_window_status", "qualification_claim")}, indent=2))
    return 0 if result.get("hard_integrity_pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
