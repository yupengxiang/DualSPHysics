"""Strict producer/terminal identity tests for the additive V5 overlay builder.

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

import ds_data02_stage2_build_native_overlay_adapter_v5 as adapter
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


class TerminalOverlayV5Tests(unittest.TestCase):
    def test_metadata_limit_is_ten_mib_or_less(self) -> None:
        self.assertLessEqual(adapter.MAX_JSON, 10 * 1024 * 1024)

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

    def _derived_terminal_for_case(self, root: Path, case_id: str, suffix: str) -> Path:
        """Make a test-only success for an exact CURRENT unresolved case.

        ROOT264 supplies the complete producer/receipt/fee shape.  The row's
        physical case key is deliberately replaced with the selected
        unresolved CURRENT key so that two successive admissions can exercise
        rolling identity accounting without opening or claiming any payload.
        """
        real = self._real()
        rows = real["case_verifications"]
        self.assertIsInstance(rows, list)
        row = copy.deepcopy(rows[0])
        row["physical_case_id"] = case_id
        join = copy.deepcopy(real)
        join["case_verifications"] = [row]
        join["actual_completed_physical_cases"] = 1
        join_path = root / f"actual-join-proof-{suffix}.json"
        _write(join_path, join)
        terminal = copy.deepcopy(real)
        terminal["actual_join_proof"] = _ref(join_path)
        terminal["selected_case_ids"] = [case_id]
        terminal_path = root / f"root-terminal-{suffix}.json"
        _write(terminal_path, terminal)
        return terminal_path

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

    def test_real_native_proof_binds_to_itself_but_not_to_another_success(self) -> None:
        real = self._real()
        real_ref = _ref(REAL_NATIVE_PROOF)
        adapter._bind_join_proof_to_terminal(real, real, real_ref, real_ref)
        wrong_path = ROOT / "checkpoints/GENERIC_NATIVE_EXTRACT_F6_V1_ACTUAL_ROOT_VERIFICATION_258.json"
        wrong = json.loads(wrong_path.read_text(encoding="utf-8"))
        with self.assertRaises(adapter.TerminalOverlayError):
            adapter._bind_join_proof_to_terminal(real, wrong, real_ref, _ref(wrong_path))

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

    def test_v6_consumes_strict_plan_alias_overlay_and_second_build_does_not_double_count(self) -> None:
        base = ROOT / "checkpoints/ORIGINAL118_NATIVE_CAUSE_AFTER_ROOT268_ACTUAL_OVERLAY_V10.json"
        plan = ROOT / "checkpoints/CURRENT336_TYPED_LIFECYCLE_AFTER_ROOT269_V4.json"
        current = Path(json.loads(plan.read_text(encoding="utf-8"))["current_catalog"]["path"])
        real = self._real()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            terminal = copy.deepcopy(real)
            terminal["status"] = "FAILED_ROOT_TERMINAL_NO_JOIN"
            terminal.pop("actual_join_proof", None)
            terminal.pop("selected_case_ids", None)
            terminal_path = root / "failed-terminal.json"
            _write(terminal_path, terminal)
            first = root / "overlay-first.json"
            result = adapter.build(base, terminal_path, first, plan, current)
            self.assertEqual(result["status"], "ROOT_TERMINAL_NOT_ADMITTED_NO_JOIN")
            loaded, _ = verifier._load_scope_v5(first, plan, current)
            self.assertEqual(loaded["case_scope"]["historical_alias_count"], 1)
            self.assertEqual(loaded["case_scope"]["canonical_cause_bound_missing_join_count"], 46)
            self.assertEqual(loaded["existing"], verifier._base_inventory(first)["existing"])
            second = root / "overlay-second.json"
            result2 = adapter.build(first, terminal_path, second, plan, current)
            self.assertEqual(result2["new_join_count"], 0)
            loaded2, _ = verifier._load_scope_v5(second, plan, current)
            self.assertEqual(loaded2["case_scope"]["historical_alias_count"], 1)
            self.assertEqual(loaded2["existing"], loaded["existing"])

    def test_two_successive_v5_outputs_reenter_v6_without_alias_or_count_drift(self) -> None:
        """Exercise success→V6→success, including canonical 117+alias accounting.

        The two terminal documents are test-owned derivatives of the actual
        ROOT264 proof shape.  They add two different unresolved CURRENT IDs;
        this proves the rolling adapter can consume its own first output and
        admit a second exact proof without treating the historical alias as a
        canonical case or double-counting an existing join.
        """
        base = ROOT / "checkpoints/ORIGINAL118_NATIVE_CAUSE_AFTER_ROOT268_ACTUAL_OVERLAY_V10.json"
        plan = ROOT / "checkpoints/CURRENT336_TYPED_LIFECYCLE_AFTER_ROOT269_V4.json"
        current = Path(json.loads(plan.read_text(encoding="utf-8"))["current_catalog"]["path"])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, inventory = adapter._load_base(base, plan, current)
            unresolved = sorted(inventory["unresolved"])
            self.assertGreaterEqual(len(unresolved), 2)
            first_id, second_id = unresolved[:2]

            first_terminal = self._derived_terminal_for_case(root, first_id, "first-success")
            first_output = root / "overlay-first-success.json"
            first_result = adapter.build(base, first_terminal, first_output, plan, current)
            self.assertEqual(first_result["status"], "VERIFIED_ROOT_TERMINAL_ROLLING_OVERLAY")

            first_loaded, _ = verifier._load_scope_v5(first_output, plan, current)
            first_inventory = verifier._base_inventory(first_output)
            self.assertEqual(first_inventory["ids"].__len__(), 118)
            self.assertEqual(len(first_inventory["aliases"]), 1)
            self.assertEqual(first_inventory["existing"].__len__(), 48)
            self.assertEqual(len(first_inventory["bound"]), 94)
            self.assertEqual(len(first_inventory["unresolved"]), 23)
            self.assertEqual(first_loaded["case_scope"]["canonical_cause_bound_missing_join_count"], 46)
            self.assertEqual(
                len(first_inventory["bound"])
                + len(first_inventory["unresolved"])
                + len(first_inventory["aliases"]),
                118,
            )

            second_terminal = self._derived_terminal_for_case(root, second_id, "second-success")
            second_output = root / "overlay-second-success.json"
            second_result = adapter.build(first_output, second_terminal, second_output, plan, current)
            self.assertEqual(second_result["status"], "VERIFIED_ROOT_TERMINAL_ROLLING_OVERLAY")
            second_loaded, _ = verifier._load_scope_v5(second_output, plan, current)
            second_inventory = verifier._base_inventory(second_output)
            self.assertEqual(len(second_inventory["ids"]), 118)
            self.assertEqual(len(second_inventory["aliases"]), 1)
            self.assertEqual(len(second_inventory["existing"]), 49)
            self.assertEqual(len(second_inventory["bound"]), 95)
            self.assertEqual(len(second_inventory["unresolved"]), 22)
            self.assertEqual(second_loaded["case_scope"]["canonical_cause_bound_missing_join_count"], 46)
            self.assertEqual(second_loaded["case_scope"]["current_bound_count"], 95)
            self.assertEqual(
                len(second_inventory["bound"])
                + len(second_inventory["unresolved"])
                + len(second_inventory["aliases"]),
                118,
            )
            second_doc = json.loads(second_output.read_text(encoding="utf-8"))
            self.assertEqual(second_doc["historical_native_cause_bound_per_fluid_id_cases"], 96)
            self.assertEqual(second_doc["native_cause_bound_per_fluid_id_cases"], 95)
            self.assertEqual(second_doc["cause_not_located_after_completed_scan_cases"], 22)
            proof_paths = [entry["path"] for entry in second_doc["actual_join_proofs"]]
            self.assertEqual(len(proof_paths), len(set(proof_paths)))
            self.assertEqual(second_doc["unresolved_alias_case_ids"], ["F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
