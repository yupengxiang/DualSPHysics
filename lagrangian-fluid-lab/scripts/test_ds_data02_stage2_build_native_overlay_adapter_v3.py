"""Focused tests for terminal-proof-bound rolling overlay admission."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import ds_data02_stage2_build_native_overlay_adapter_v3 as adapter
import ds_data02_stage2_verify_generic_native_join_v6 as verifier


BASE = SCRIPT_DIR.parents[0] / "campaigns/ds-data-02/stage2/checkpoints/ORIGINAL118_NATIVE_CAUSE_AFTER_ROOT268_ACTUAL_OVERLAY_V10.json"


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _ref(path: Path) -> dict[str, object]:
    stat = path.stat()
    return {"path": str(path.resolve()), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "ctime_ns": stat.st_ctime_ns, "st_dev": stat.st_dev, "st_ino": stat.st_ino, "sha256": _sha(path)}


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


class TerminalOverlayV3Tests(unittest.TestCase):
    def _terminal(self, root: Path, case_id: str, *, already_bound: bool = False, failed: bool = False) -> Path:
        proof_path = root / "terminal-join-proof.json"
        _write(proof_path, {
            "schema": "ds02.stage2.root-terminal-native-join-proof.v1",
            "status": "VERIFIED_ACTUAL_NATIVE_TYPED_JOIN",
            "counts": {"cases_requested": 1, "completed": 1, "failed": 0},
            "case_verifications": [{"physical_case_id": case_id, "status": "VERIFIED_PER_CASE_NATIVE_TYPED_JOIN"}],
        })
        value: dict[str, object] = {
            "schema": adapter.TERMINAL_PROOF_SCHEMA,
            "status": "ROOT_TERMINAL_FAILED" if failed else "VERIFIED_ACTUAL_ROOT_TERMINAL",
            "actual_join_proof": _ref(proof_path),
            "selected_case_ids": [case_id],
            "execution": {"status": "FAILED" if failed else "COMPLETED", "returncode": 1 if failed else 0},
            "parent_charge": {"status": "failed" if failed else "completed"},
            "parent_reservation_released": not failed,
            "repeat_fee_idempotent": not failed,
            "outer_unit_result": "failed" if failed else "success",
            "guarded_receipt_status": "failed" if failed else "completed",
            "prior_classification": "NATIVE_CAUSE_BOUND_PER_FLUID_ID" if already_bound else "CAUSE_NOT_LOCATED_AFTER_COMPLETED_SCAN",
        }
        terminal_path = root / ("failed-terminal-proof.json" if failed else "terminal-proof.json")
        _write(terminal_path, value)
        return terminal_path

    def test_completed_unresolved_case_appends_proof_and_new_cause_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = json.loads(BASE.read_text(encoding="utf-8"))
            case_id = base["remaining_cause_not_located_case_ids"][0]
            terminal = self._terminal(root, case_id)
            output = root / "overlay.json"
            result = adapter.build(BASE, terminal, output)
            self.assertEqual(result["status"], "VERIFIED_ROOT_TERMINAL_ROLLING_OVERLAY")
            overlay = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(len(overlay["actual_join_proofs"]), len(base["actual_join_proofs"]) + 1)
            self.assertEqual(overlay["actual_typed_native_saved_frame_join_physical_cases"], base["actual_typed_native_saved_frame_join_physical_cases"] + 1)
            rows = [row for row in overlay["newly_bound_cases"] if row["physical_case_id"] == case_id]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["native_cause_credit"], "NEW_CASE_ALLOWED")

    def test_completed_cause_bound_case_adds_join_without_new_cause(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inventory = verifier._base_inventory(BASE)
            case_id = sorted(inventory["bound"] - inventory["existing"])[0]
            base = json.loads(BASE.read_text(encoding="utf-8"))
            terminal = self._terminal(root, case_id, already_bound=True)
            output = root / "overlay.json"
            adapter.build(BASE, terminal, output)
            overlay = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(overlay["actual_typed_native_saved_frame_join_physical_cases"], base["actual_typed_native_saved_frame_join_physical_cases"] + 1)
            self.assertNotIn(case_id, {row["physical_case_id"] for row in overlay["newly_bound_cases"]})
            self.assertEqual(overlay["terminal_admission"]["already_cause_bound_join_only_case_ids"], [case_id])

    def test_failed_terminal_proof_keeps_previous_proof_list_and_grants_no_join(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = json.loads(BASE.read_text(encoding="utf-8"))
            case_id = base["remaining_cause_not_located_case_ids"][0]
            terminal = self._terminal(root, case_id, failed=True)
            output = root / "overlay.json"
            result = adapter.build(BASE, terminal, output)
            self.assertEqual(result["status"], "ROOT_TERMINAL_NOT_ADMITTED_NO_JOIN")
            overlay = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(overlay["actual_join_proofs"], base["actual_join_proofs"])
            self.assertEqual(overlay["actual_typed_native_saved_frame_join_physical_cases"], base["actual_typed_native_saved_frame_join_physical_cases"])
            self.assertEqual(overlay["newly_bound_cases"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
