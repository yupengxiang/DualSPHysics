"""Additive V5 rolling-overlay success -> V6 -> success coverage.

This test is intentionally separate from the consumed V5 test module.  It
uses the ROOT264 terminal shape only to exercise rolling identity accounting
with test-owned case keys; it never opens H5/BI4/OBI4/native payloads.
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


class TerminalOverlayV5IncrementalTests(unittest.TestCase):
    def _real(self) -> dict[str, object]:
        return json.loads(REAL_NATIVE_PROOF.read_text(encoding="utf-8"))

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
