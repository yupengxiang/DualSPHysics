"""Strict terminal-contract tests for the additive V4 overlay builder.

The successful fixture is derived from the shape of an actual native root
proof (ROOT264).  Its request, receipt, manifest, report, fee closure, and
terminal fields remain real source-bound references; only the case partition
is reduced in a temporary test scope so the admission accounting can be
exercised without claiming a production case.  No H5/BI4/OBI4 payload is
opened by these tests.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import ds_data02_stage2_build_native_overlay_adapter_v4 as adapter
import ds_data02_stage2_verify_generic_native_join_v6 as verifier


ROOT = SCRIPT_DIR.parents[0] / "campaigns/ds-data-02/stage2"
REAL_NATIVE_PROOF = ROOT / "checkpoints/GENERIC_NATIVE_EXTRACT_F4_V2_ACTUAL_ROOT_VERIFICATION_264.json"


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _ref(path: Path) -> dict[str, object]:
    stat = path.stat()
    return {
        "path": str(path.resolve()),
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "ctime_ns": stat.st_ctime_ns,
        "st_dev": stat.st_dev,
        "st_ino": stat.st_ino,
        "sha256": _sha(path),
    }


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


class TerminalOverlayV4Tests(unittest.TestCase):
    def _real(self) -> dict[str, object]:
        return json.loads(REAL_NATIVE_PROOF.read_text(encoding="utf-8"))

    def _derived_terminal(self, root: Path, row_index: int = 1) -> tuple[Path, str, dict[str, object]]:
        """Create a tiny terminal proof from the real ROOT264 proof shape."""
        real = self._real()
        rows = real["case_verifications"]
        self.assertIsInstance(rows, list)
        row = copy.deepcopy(rows[row_index])
        case_id = row["physical_case_id"]
        join = copy.deepcopy(real)
        join["case_verifications"] = [row]
        join["actual_completed_physical_cases"] = 1
        join_path = root / "actual-join-proof-derived-from-root264.json"
        _write(join_path, join)
        terminal = copy.deepcopy(real)
        terminal["actual_join_proof"] = _ref(join_path)
        terminal["selected_case_ids"] = [case_id]
        terminal_path = root / "root-terminal-derived-from-root264.json"
        _write(terminal_path, terminal)
        return terminal_path, case_id, row

    def _base(self, root: Path, existing_id: str, unresolved_id: str, existing_proof: Path) -> Path:
        scope = {
            "schema": verifier.SCOPE_SCHEMA,
            "scope": {"unresolved_alias_case_ids": []},
            "case_rows": [
                {"physical_case_id": existing_id, "classification": "NATIVE_CAUSE_BOUND_PER_FLUID_ID"},
                {"physical_case_id": unresolved_id, "classification": "CAUSE_NOT_LOCATED_AFTER_COMPLETED_SCAN"},
            ],
        }
        scope_path = root / "tiny-base-scope.json"
        _write(scope_path, scope)
        base = {
            "schema": adapter.OVERLAY_SCHEMA,
            "status": "VERIFIED_ROOT_TERMINAL_ROLLING_OVERLAY",
            "base_scope": _ref(scope_path),
            "actual_join_proofs": [_ref(existing_proof)],
            "physical_case_count": 2,
            "native_cause_bound_per_fluid_id_cases": 1,
            "cause_not_located_after_completed_scan_cases": 1,
            "actual_typed_native_saved_frame_join_physical_cases": 1,
            "newly_bound_cases": [],
            "remaining_cause_not_located_case_ids": [unresolved_id],
            "claim_boundary": {"physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        }
        base_path = root / "tiny-base-overlay.json"
        _write(base_path, base)
        return base_path

    def _existing_proof(self, root: Path, row: dict[str, object]) -> Path:
        real = self._real()
        proof = copy.deepcopy(real)
        proof["case_verifications"] = [copy.deepcopy(row)]
        proof["actual_completed_physical_cases"] = 1
        path = root / "existing-proof-derived-from-root264.json"
        _write(path, proof)
        return path

    def test_actual_native_rootproof_shape_has_strict_terminal_accounting(self) -> None:
        value = self._real()
        self.assertEqual(adapter._terminal_state(value), "COMPLETED")
        adapter._require_completed_accounting(value)

    def test_real_current_plan_adds_the_unresolved_historical_alias(self) -> None:
        plan = ROOT / "checkpoints/CURRENT336_TYPED_LIFECYCLE_AFTER_ROOT269_V4.json"
        current = Path(json.loads(plan.read_text(encoding="utf-8"))["current_catalog"]["path"])
        _, _, inventory = adapter._load_base(
            ROOT / "checkpoints/ORIGINAL118_NATIVE_CAUSE_AFTER_ROOT268_ACTUAL_OVERLAY_V10.json",
            plan,
            current,
        )
        self.assertEqual(len(inventory["aliases"]), 1)
        self.assertIn("F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090", inventory["aliases"])
        self.assertNotIn("F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090", inventory["existing"])

    def test_empty_execution_and_missing_schema_cannot_become_success(self) -> None:
        value = self._real()
        value["execution"] = {}
        with self.assertRaises(adapter.TerminalOverlayError):
            adapter._require_completed_accounting(value)
        value = self._real()
        value["schema"] = None
        with self.assertRaises(adapter.TerminalOverlayError):
            adapter._terminal_state(value)
        value = self._real()
        value["status"] = "FINISHED_WITHOUT_FAILURE"
        with self.assertRaises(adapter.TerminalOverlayError):
            adapter._terminal_state(value)

    def test_real_shape_without_selected_join_proof_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            real = self._real()
            row_a = copy.deepcopy(real["case_verifications"][0])
            row_b = copy.deepcopy(real["case_verifications"][1])
            existing = self._existing_proof(root, row_a)
            base = self._base(root, row_a["physical_case_id"], row_b["physical_case_id"], existing)
            terminal = root / "real-shape-without-join.json"
            _write(terminal, real)
            with self.assertRaises(adapter.TerminalOverlayError):
                adapter.build(base, terminal, root / "out.json", allow_fixture_context=True)

    def test_derived_real_shape_admits_unresolved_case_and_preserves_v10_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            real = self._real()
            row_a = copy.deepcopy(real["case_verifications"][0])
            existing = self._existing_proof(root, row_a)
            terminal, unresolved_id, _ = self._derived_terminal(root, row_index=1)
            base = self._base(root, row_a["physical_case_id"], unresolved_id, existing)
            output = root / "overlay.json"
            result = adapter.build(base, terminal, output, allow_fixture_context=True)
            self.assertEqual(result["status"], "VERIFIED_ROOT_TERMINAL_ROLLING_OVERLAY")
            self.assertEqual(result["schema"], adapter.OUTPUT_SCHEMA)
            overlay = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(overlay["schema"], adapter.OVERLAY_SCHEMA)
            self.assertEqual(overlay["actual_typed_native_saved_frame_join_physical_cases"], 2)
            self.assertEqual(overlay["native_cause_bound_per_fluid_id_cases"], 2)
            self.assertEqual(overlay["cause_not_located_after_completed_scan_cases"], 0)
            self.assertEqual(overlay["terminal_admission"]["new_cause_case_ids"], [unresolved_id])
            admitted = verifier._base_inventory(output)
            self.assertEqual(admitted["existing"], {row_a["physical_case_id"], unresolved_id})
            self.assertFalse(admitted["unresolved"])

    def test_failed_allowlisted_terminal_is_no_join(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            real = self._real()
            row_a = copy.deepcopy(real["case_verifications"][0])
            row_b = copy.deepcopy(real["case_verifications"][1])
            existing = self._existing_proof(root, row_a)
            base = self._base(root, row_a["physical_case_id"], row_b["physical_case_id"], existing)
            terminal = copy.deepcopy(real)
            terminal["status"] = "FAILED_ROOT_TERMINAL_NO_JOIN"
            terminal.pop("actual_join_proof", None)
            terminal.pop("selected_case_ids", None)
            terminal_path = root / "failed-root-terminal.json"
            _write(terminal_path, terminal)
            output = root / "overlay.json"
            result = adapter.build(base, terminal_path, output, allow_fixture_context=True)
            self.assertEqual(result["status"], "ROOT_TERMINAL_NOT_ADMITTED_NO_JOIN")
            overlay = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(overlay["actual_typed_native_saved_frame_join_physical_cases"], 1)
            self.assertEqual(overlay["newly_bound_cases"], [])
            rejected = verifier._base_inventory(output)
            self.assertEqual(rejected["existing"], {row_a["physical_case_id"]})

    def test_bound_case_adds_join_only_and_not_new_cause(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            real = self._real()
            row_a = copy.deepcopy(real["case_verifications"][0])
            existing = self._existing_proof(root, row_a)
            terminal, bound_id, _ = self._derived_terminal(root, row_index=1)
            base = self._base(root, row_a["physical_case_id"], bound_id, existing)
            base_doc = json.loads(base.read_text(encoding="utf-8"))
            scope_path = Path(base_doc["base_scope"]["path"])
            scope_doc = json.loads(scope_path.read_text(encoding="utf-8"))
            scope_doc["case_rows"][1]["classification"] = "NATIVE_CAUSE_BOUND_PER_FLUID_ID"
            _write(scope_path, scope_doc)
            base_doc["base_scope"] = _ref(scope_path)
            base_doc["native_cause_bound_per_fluid_id_cases"] = 2
            base_doc["cause_not_located_after_completed_scan_cases"] = 0
            base_doc["remaining_cause_not_located_case_ids"] = []
            _write(base, base_doc)
            output = root / "bound-overlay.json"
            result = adapter.build(base, terminal, output, allow_fixture_context=True)
            overlay = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(result["new_native_cause_count"], 0)
            self.assertEqual(overlay["terminal_admission"]["new_cause_case_ids"], [])
            self.assertEqual(overlay["terminal_admission"]["already_cause_bound_join_only_case_ids"], [bound_id])


if __name__ == "__main__":
    unittest.main(verbosity=2)
