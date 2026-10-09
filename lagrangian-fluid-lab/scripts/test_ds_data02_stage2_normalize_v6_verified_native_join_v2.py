"""Tiny same-chain tests for the strict V2 normalizer."""
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

import ds_data02_stage2_normalize_v6_verified_native_join_v2 as normalizer

_spec = importlib.util.spec_from_file_location(
    "root312_v6_fixture_for_normalizer_v2",
    SCRIPT_DIR / "test_ds_data02_stage2_verify_generic_native_join_v6_root312.py",
)
assert _spec and _spec.loader
fixture = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = fixture
_spec.loader.exec_module(fixture)

ROOT = SCRIPT_DIR.parents[0] / "campaigns/ds-data-02/stage2"
REAL_TERMINAL = ROOT / "checkpoints/GENERIC_NATIVE_EXTRACT_F4_V2_ACTUAL_ROOT_VERIFICATION_264.json"


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
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
        "st_dev": int(stat.st_dev),
        "st_ino": int(stat.st_ino),
        "sha256": _sha(path),
    }


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _make_same_chain_terminal(root: Path, request: Path, manifest: Path, report: Path) -> Path:
    """Create an explicit test terminal whose four refs are the V6 refs."""
    terminal = json.loads(REAL_TERMINAL.read_text(encoding="utf-8"))
    request_doc = json.loads(request.read_text(encoding="utf-8"))
    if request_doc.get("attempt_id") != "tiny-root312-normalizer-v2":
        raise AssertionError("test request must be rebound before V6 verification")
    request_ref = _ref(request)
    manifest_ref = _ref(manifest)
    report_ref = _ref(report)
    receipt = {
        "schema": "ds02.execution-receipt.v1",
        "status": "completed",
        "returncode": 0,
        "output_root": str(root.resolve()),
        "request_sha256": request_ref["sha256"],
        "request": {"attempt_id": request_doc["attempt_id"]},
    }
    receipt_path = root / "tiny-execution-receipt.json"
    _write(receipt_path, receipt)
    receipt_ref = _ref(receipt_path)
    terminal.update(
        {
            "schema": "ds02.stage2.root-actual-verification.v1",
            "fixture_context": "EXPLICIT_TEST_ONLY",
            "request": request_ref["path"],
            "request_sha256": request_ref["sha256"],
            "manifest": manifest_ref["path"],
            "manifest_sha256": manifest_ref["sha256"],
            "report": report_ref["path"],
            "report_sha256": report_ref["sha256"],
            "receipt": receipt_ref["path"],
            "receipt_sha256": receipt_ref["sha256"],
            "parent_charge": {
                "id": f"tiny/{root.name}",
                "status": "completed",
                "finished_at_utc": "2026-01-01T00:00:00Z",
            },
            "guarded_receipt_status": "completed",
            "outer_unit_result": "success",
            "parent_reservation_released": True,
            "repeat_fee_idempotent": True,
        }
    )
    # The old ROOT264 proof's selected proof is deliberately removed.  V2's
    # output is itself a normalized row proof; it must not inherit another
    # producer's actual_join_proof identity.
    for key in ("actual_join_proof", "native_join_proof", "join_proof", "selected_case_ids"):
        terminal.pop(key, None)
    terminal_path = root / "tiny-same-chain-terminal.json"
    _write(terminal_path, terminal)
    return terminal_path


class StrictV2NormalizerTests(unittest.TestCase):
    def _run_v6(self, root: Path) -> tuple[Path, Path, Path, dict[str, object]]:
        manifest, report, request = fixture._prepare_direct_root312_run(root)
        terminal_request = json.loads(request.read_text(encoding="utf-8"))
        terminal_request["attempt_id"] = "tiny-root312-normalizer-v2"
        request.write_text(json.dumps(terminal_request, sort_keys=True) + "\n", encoding="utf-8")
        result = fixture.verifier.verify(fixture.OVERLAY, manifest, request, report, fixture.PLAN, fixture.CURRENT)
        result_path = root / "v6-result.json"
        _write(result_path, result)
        return manifest, report, request, result

    def test_same_chain_terminal_is_strictly_normalized_and_fixture_is_nonproduction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, report, request, result = self._run_v6(root)
            terminal = _make_same_chain_terminal(root, request, manifest, report)
            result_path = root / "v6-result.json"
            output = root / "normalized-v2.json"
            value = normalizer.normalize(result_path, terminal, output, allow_fixture_context=True)
            self.assertEqual(value["status"], "NORMALIZED_V6_VERIFIED_CASE_ROWS_STRICT_TERMINAL_BOUND")
            self.assertFalse(value["production_eligible"])
            proof = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(proof["v6_producer_identity"]["request"]["path"], str(request.resolve()))
            self.assertEqual(proof["v6_producer_identity"]["manifest"]["path"], str(manifest.resolve()))
            self.assertEqual(proof["v6_producer_identity"]["report"]["path"], str(report.resolve()))
            self.assertEqual(proof["actual_completed_physical_cases"], len(result["case_verifications"]))
            self.assertEqual(proof["new_original118_cause_bound_physical_cases"], 0)

    def test_fixture_marker_is_rejected_without_explicit_flag(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, report, request, _ = self._run_v6(root)
            terminal = _make_same_chain_terminal(root, request, manifest, report)
            with self.assertRaises(normalizer.NormalizationError):
                normalizer.normalize(root / "v6-result.json", terminal, root / "reject.json")

    def test_production_cli_rejects_fixture_without_explicit_flag(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, report, request, _ = self._run_v6(root)
            terminal = _make_same_chain_terminal(root, request, manifest, report)
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_DIR / "ds_data02_stage2_normalize_v6_verified_native_join_v2.py"),
                    "--v6-result", str(root / "v6-result.json"),
                    "--terminal-identity", str(terminal),
                    "--output", str(root / "reject-cli.json"),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
            self.assertIn("fixture terminal identity", completed.stdout)

    def test_terminal_identity_mismatch_is_rejected_even_when_both_documents_are_valid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, report, request, _ = self._run_v6(root)
            terminal = _make_same_chain_terminal(root, request, manifest, report)
            doc = json.loads(terminal.read_text(encoding="utf-8"))
            wrong = root / "wrong-request.json"
            wrong.write_text(json.dumps(json.loads(request.read_text(encoding="utf-8")), sort_keys=True) + "\n", encoding="utf-8")
            wrong_doc = json.loads(wrong.read_text(encoding="utf-8"))
            wrong_doc["attempt_id"] = "different-terminal-attempt"
            _write(wrong, wrong_doc)
            wrong_ref = _ref(wrong)
            receipt_path = Path(doc["receipt"])
            receipt_doc = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt_doc["request_sha256"] = wrong_ref["sha256"]
            _write(receipt_path, receipt_doc)
            receipt_ref = _ref(receipt_path)
            doc["request"] = wrong_ref["path"]
            doc["request_sha256"] = wrong_ref["sha256"]
            doc["receipt_sha256"] = receipt_ref["sha256"]
            terminal.write_text(json.dumps(doc, sort_keys=True) + "\n", encoding="utf-8")
            with self.assertRaises(normalizer.NormalizationError):
                normalizer.normalize(root / "v6-result.json", terminal, root / "reject.json", allow_fixture_context=True)

    def test_case_output_outside_terminal_receipt_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, report, request, result = self._run_v6(root)
            terminal = _make_same_chain_terminal(root, request, manifest, report)
            first = result["case_verifications"][0]
            outside = root.parent / f"{root.name}-outside-case.json"
            outside.write_bytes(Path(first["case_output"]["path"]).read_bytes())
            altered = copy.deepcopy(result)
            altered["case_verifications"][0]["case_output"] = _ref(outside)
            altered_path = root / "v6-outside-case.json"
            _write(altered_path, altered)
            with self.assertRaises(normalizer.NormalizationError):
                normalizer.normalize(altered_path, terminal, root / "reject.json", allow_fixture_context=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
