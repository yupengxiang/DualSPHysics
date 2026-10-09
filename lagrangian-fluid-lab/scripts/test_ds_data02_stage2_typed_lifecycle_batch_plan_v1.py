from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ds_data02_stage2_typed_lifecycle_batch_plan_v1 as subject


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> str:
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return sha(path)


def fixture(root: Path) -> tuple[Path, Path, str, str, str]:
    scan = root / "scan.json"
    receipt = root / "receipt.json"
    scan.write_text("{}\n", encoding="utf-8")
    receipt.write_text("{}\n", encoding="utf-8")
    current_cases = []
    audit_cases = []
    alias = "F2_ALIAS_CASE"
    for index in range(336):
        family = "F1" if index < 168 else "F2"
        case_id = alias if index == 3 else f"{family}_CASE_{index:03d}"
        size = 1300 if index == 4 else 100 + (index % 5) * 10
        trajectory = root / family / f"{case_id}.h5"
        trajectory.parent.mkdir(parents=True, exist_ok=True)
        trajectory.write_bytes(b"metadata-only fixture; not an HDF5 payload\n" + b"x" * max(0, size - 40))
        declared_sha = f"{index + 1:064x}"[-64:]
        current_cases.append({
            "family_id": family,
            "physical_case_id": case_id,
            "runtime_case_alias": f"runtime-{index}",
            "frames": 4,
            "particles": 4,
            "trajectory": {"path": str(trajectory), "producer_declared_sha256": declared_sha, "bytes": trajectory.stat().st_size},
        })
        audit_cases.append({
            "family_id": family,
            "physical_case_id": case_id,
            "trajectory": str(trajectory),
            "trajectory_verified_sha256": declared_sha,
            "scan": str(scan), "scan_sha256": sha(scan),
            "receipt": str(receipt), "receipt_sha256": sha(receipt),
            "scan_status": "SCANNED", "field_failures": [],
            "exact_CURRENT_path_and_declared_sha_match": True,
        })
    current = root / "CURRENT336.json"
    current_sha = write_json(current, {"schema": subject.CURRENT_SCHEMA, "cases": current_cases})
    audit = root / "audit023.json"
    audit_sha = write_json(audit, {
        "schema": subject.AUDIT_SCHEMA,
        "current_catalog": {"path": str(current), "sha256": current_sha},
        "verified_cases": audit_cases,
    })
    return current, audit, current_sha, audit_sha, alias


class BatchPlanTests(unittest.TestCase):
    def test_self_test(self) -> None:
        self.assertEqual(subject.self_test()["status"], "PASS")

    def test_plan_stats_only_groups_by_family_and_isolates_alias_and_oversize(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            current, audit, current_sha, audit_sha, alias = fixture(Path(directory))
            output = Path(directory) / "plan.json"
            result = subject.build_plan(
                current, audit, output,
                expected_current_sha256=current_sha,
                expected_audit_sha256=audit_sha,
                alias_case=alias,
                max_group_bytes=1000,
                max_group_cases=3,
            )
            self.assertEqual(result["case_count"], 336)
            self.assertFalse(result["trajectory_content_opened"])
            self.assertFalse(result["trajectory_content_hashed"])
            plan = json.loads(output.read_text())
            self.assertEqual(plan["status"], "PREPARED_METADATA_ONLY_NO_LAUNCH")
            self.assertEqual(plan["counts"]["exact_current_audit_metadata_joins"], 335)
            self.assertEqual(plan["counts"]["historical_alias_unresolved"], 1)
            self.assertFalse(any(group["launch_allowed_by_planner"] for group in plan["groups"]))
            alias_groups = [group for group in plan["groups"] if alias in group["case_ids"]]
            self.assertEqual(len(alias_groups), 1)
            self.assertEqual(alias_groups[0]["case_count"], 1)
            self.assertTrue(alias_groups[0]["historical_alias_group"])
            self.assertTrue(any(group["oversize_single_case"] for group in plan["groups"]))
            for group in plan["groups"]:
                self.assertEqual(len({case.split("_")[0] for case in group["case_ids"]}), 1)
                self.assertEqual(group["attempt_remaining"], "ROOT_OWNED_NOT_COMPUTED_BY_PLANNER")

    def test_wrong_current_sha_and_case_set_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            current, audit, current_sha, audit_sha, alias = fixture(Path(directory))
            with self.assertRaises(subject.PlanError):
                subject.build_plan(current, audit, Path(directory) / "bad.json", expected_current_sha256="0" * 64, expected_audit_sha256=audit_sha, alias_case=alias)
            value = json.loads(audit.read_text())
            value["verified_cases"].pop()
            audit.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(subject.PlanError):
                subject.build_plan(current, audit, Path(directory) / "bad2.json", expected_current_sha256=current_sha, expected_audit_sha256=sha(audit), alias_case=alias)


if __name__ == "__main__":
    unittest.main()
