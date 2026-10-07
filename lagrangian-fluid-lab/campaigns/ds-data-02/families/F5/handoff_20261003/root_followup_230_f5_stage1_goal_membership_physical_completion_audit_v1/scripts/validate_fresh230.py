#!/usr/bin/env python3
"""Read-only structural validator for the fresh230 metadata handoff."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ALLOWED_SUFFIXES = {".json", ".md", ".py"}
FORBIDDEN_SUFFIXES = {".h5", ".bi4", ".ibi4", ".csv", ".dat", ".vtk", ".png", ".xmf"}


def load(rel: str):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    manifest = load("manifest.json")
    check(manifest["schema"] == "ds02.f5.fresh230.source-only-manifest.v1", "manifest schema")
    check(manifest["source_only"] is True, "source-only flag")
    check(manifest["scientific_payload_IO"] is False, "payload IO flag")
    check(manifest["global_stage1_completion_claim"] is False, "completion must remain false")
    check(manifest["case_credit"] == 0 and manifest["Q_N"] is False and manifest["Q_E"] is False, "credit/Q flags")

    for item in manifest["files"]:
        rel = item["path"]
        p = ROOT / rel
        check(p.is_file(), f"missing manifest file: {rel}")
        check(p.suffix.lower() in ALLOWED_SUFFIXES, f"unexpected file suffix: {rel}")
        check(item["sha256"] == sha(p), f"manifest SHA mismatch: {rel}")

    for p in ROOT.rglob("*"):
        if p.is_file():
            check(p.suffix.lower() not in FORBIDDEN_SUFFIXES, f"scientific/PNG payload in source package: {p}")

    req = load("metadata/goal-requirements.json")
    check(req["source"]["baseline_commit"] == "0081645116664386f76f2bfa2ef428bcd74e846e", "goal baseline")
    check(len(req["requirements"]) == 6, "requirement matrix")

    membership = load("metadata/membership-audit.json")
    expected = {"F1": 48, "F2": 48, "F3": 48, "F4": 48, "F5": 48, "F6": 48, "F7": 48}
    all_final = []
    for family, count in expected.items():
        row = membership["families"][family]
        check(row["first8_count"] == 8 and row["first24_count"] == 24 and row["final48_count"] == count, f"counts {family}")
        check(row["first8_unique"] and row["first24_unique"] and row["final48_unique"], f"uniqueness {family}")
        check(row["first8_subset_first24"] and row["first24_subset_final48"], f"subset {family}")
        all_final.extend([f"{family}:{i}" for i in range(count)])
    global_row = membership["families"]["global_final_roster"]
    check(global_row["declared_final_roster_count"] == 336, "global roster count")
    check(global_row["unique_cross_family_physical_ids"] and global_row["cross_family_duplicate_count"] == 0, "cross-family duplicates")
    check(global_row["checkpoint331_accepted_count"] == 334 and global_row["checkpoint331_pending_count"] == 2, "checkpoint counts")

    matrix = load("metadata/family-delivery-matrix.json")
    snap = matrix["snapshot"]
    check(snap["checkpoint"] == 331, "matrix checkpoint")
    check(snap["accepted_independent_cases"] == 334 and snap["target_independent_cases"] == 336, "matrix accepted/target")
    check(sum(snap["accepted_per_family"].values()) == 334, "per-family accepted total")
    check(matrix["global_completion"]["complete"] is False, "global completion")
    check(len(matrix["global_completion"]["pending_cases"]) == 2, "pending cases")
    check(matrix["families"]["F3"]["pending_case"]["main_checkpoint_state"] == "pending_primary_integration", "F3 pending state")
    check(matrix["families"]["F5"]["pending_case"]["QI_visual_status"] == "pending delegated personal34contacts9keys", "F5 pending state")

    pending = load("metadata/pending-and-limits.json")
    check(pending["global_decision"] == "stage1_not_complete_at_checkpoint331", "pending decision")
    check(len(pending["pending_gates"]) == 2, "pending gate count")
    check(pending["resource_snapshot"]["limits_unchanged"] is True, "resource limits")

    print("fresh230 validator: PASS (metadata-only; global stage1 remains 334/336, not complete)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
