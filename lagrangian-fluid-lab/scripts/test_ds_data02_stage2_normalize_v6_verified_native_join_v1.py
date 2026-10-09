"""Tiny worker -> V6 -> root-row normalizer -> V5 integration tests."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import ds_data02_stage2_build_native_overlay_adapter_v5 as v5
import ds_data02_stage2_normalize_v6_verified_native_join_v1 as normalizer

_spec = importlib.util.spec_from_file_location(
    "root312_v6_fixture_for_normalizer",
    SCRIPT_DIR / "test_ds_data02_stage2_verify_generic_native_join_v6_root312.py",
)
assert _spec and _spec.loader
fixture = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = fixture
_spec.loader.exec_module(fixture)

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


class V6RowNormalizerTests(unittest.TestCase):
    def _real_terminal(self) -> dict[str, object]:
        return json.loads(REAL_NATIVE_PROOF.read_text(encoding="utf-8"))

    def _base_overlay(self, root: Path, case_ids: list[str]) -> Path:
        """Make a tiny previous overlay: one existing plus V6 unresolved rows."""
        real = self._real_terminal()
        existing_id = "TINY_EXISTING_NATIVE_CASE"
        row = copy.deepcopy(real["case_verifications"][0])
        row["physical_case_id"] = existing_id
        existing_proof = copy.deepcopy(real)
        existing_proof["case_verifications"] = [row]
        existing_proof["counts"] = {"cases_requested": 1, "completed": 1, "failed": 0}
        existing_proof["actual_completed_physical_cases"] = 1
        existing_proof["failed_physical_cases"] = 0
        existing_path = root / "existing-root-proof.json"
        _write(existing_path, existing_proof)
        scope = {
            "schema": v5.v6.SCOPE_SCHEMA,
            "scope": {"unresolved_alias_case_ids": []},
            "case_rows": ([{"physical_case_id": existing_id, "classification": "NATIVE_CAUSE_BOUND_PER_FLUID_ID"}]
                          + [{"physical_case_id": case_id, "classification": "CAUSE_NOT_LOCATED_AFTER_COMPLETED_SCAN"} for case_id in case_ids]),
        }
        scope_path = root / "base-scope.json"
        _write(scope_path, scope)
        base = {
            "schema": v5.OVERLAY_SCHEMA,
            "status": "VERIFIED_ROOT_TERMINAL_ROLLING_OVERLAY",
            "base_scope": _ref(scope_path),
            "actual_join_proofs": [_ref(existing_path)],
            "physical_case_count": len(case_ids) + 1,
            "native_cause_bound_per_fluid_id_cases": 1,
            "historical_native_cause_bound_per_fluid_id_cases": 1,
            "cause_not_located_after_completed_scan_cases": len(case_ids),
            "actual_typed_native_saved_frame_join_physical_cases": 1,
            "newly_bound_cases": [],
            "remaining_cause_not_located_case_ids": list(case_ids),
            "claim_boundary": {"physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        }
        base_path = root / "base-overlay.json"
        _write(base_path, base)
        return base_path

    def test_real_root312_worker_to_v6_to_normalized_rows_to_v5(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, report, request = fixture._prepare_direct_root312_run(root)
            v6_result = fixture.verifier.verify(fixture.OVERLAY, manifest, request, report, fixture.PLAN, fixture.CURRENT)
            v6_path = root / "v6-verification.json"
            _write(v6_path, v6_result)
            case_ids = [row["physical_case_id"] for row in v6_result["case_verifications"]]
            normalized_path = root / "normalized-root-proof.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_DIR / "ds_data02_stage2_normalize_v6_verified_native_join_v1.py"),
                    "--v6-result", str(v6_path),
                    "--terminal-identity", str(REAL_NATIVE_PROOF),
                    "--output", str(normalized_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            normalized = json.loads(completed.stdout)
            self.assertEqual(normalized["status"], "NORMALIZED_V6_VERIFIED_CASE_ROWS")
            proof = json.loads(normalized_path.read_text(encoding="utf-8"))
            self.assertEqual(proof["schema"], normalizer.SCHEMA)
            self.assertEqual(proof["actual_completed_physical_cases"], len(case_ids))
            self.assertEqual([row["physical_case_id"] for row in proof["case_verifications"]], case_ids)
            self.assertTrue(all("report" in row and "report_sha256" in row for row in proof["case_verifications"]))
            self.assertTrue(all("native_csv_evidence" in row and "exact_join_rows" in row for row in proof["case_verifications"]))

            # Wrap the normalized proof in a root terminal with the same
            # ROOT264 producer identity.  V5 then checks the normalized top
            # refs/fee closure and the exact row IDs; no producer aggregate is
            # used for admission.
            terminal = self._real_terminal()
            terminal["actual_join_proof"] = _ref(normalized_path)
            terminal["selected_case_ids"] = case_ids
            terminal_path = root / "terminal-for-normalized-proof.json"
            _write(terminal_path, terminal)
            base_path = self._base_overlay(root, case_ids)
            output_path = root / "v5-overlay.json"
            result = v5.build(base_path, terminal_path, output_path, allow_fixture_context=True)
            self.assertEqual(result["status"], "VERIFIED_ROOT_TERMINAL_ROLLING_OVERLAY")
            self.assertEqual(result["new_join_count"], len(case_ids))
            self.assertEqual(result["new_native_cause_count"], len(case_ids))
            output = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(output["actual_typed_native_saved_frame_join_physical_cases"], len(case_ids) + 1)
            self.assertEqual(output["native_cause_bound_per_fluid_id_cases"], len(case_ids) + 1)

    def test_normalizer_rejects_a_failed_v6_case_before_root_shape_conversion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, report, request = fixture._prepare_direct_root312_run(root, fail_first_decoder=True)
            v6_result = fixture.verifier.verify(fixture.OVERLAY, manifest, request, report, fixture.PLAN, fixture.CURRENT)
            v6_path = root / "v6-failed-verification.json"
            _write(v6_path, v6_result)
            with self.assertRaises(normalizer.NormalizationError):
                normalizer.normalize(v6_path, REAL_NATIVE_PROOF, root / "should-not-exist.json")


if __name__ == "__main__":
    unittest.main(verbosity=2)
