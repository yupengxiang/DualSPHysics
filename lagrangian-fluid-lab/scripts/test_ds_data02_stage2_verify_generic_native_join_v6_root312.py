"""Genuine ROOT312 production-schema fixture for the additive V6 verifier.

The fixture invokes ROOT312 V4 ``audit`` itself.  It does not hand-write a
case report or alter the resulting report schema; V6 must accept the exact
``ds02.stage2.root312-f4-native-extract-report.v2`` emitted by that worker.
All payloads are tiny test-owned files.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import ds_data02_stage2_verify_generic_native_join_v6 as verifier

# Reuse only the test-owned fixture constructor; the production ROOT312 audit
# is invoked directly below and creates the batch report itself.
_spec = importlib.util.spec_from_file_location(
    "stage2_tiny_v5_fixture_for_v6",
    SCRIPT_DIR / "test_ds_data02_stage2_tiny_production_worker_to_v5.py",
)
assert _spec and _spec.loader
fixture = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = fixture
_spec.loader.exec_module(fixture)

OVERLAY = fixture.OVERLAY
PLAN = fixture.PLAN
CURRENT = fixture.CURRENT


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


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


def _prepare_direct_root312_run(root: Path, *, fail_first_decoder: bool = False) -> tuple[Path, Path, Path]:
    """Run frozen ROOT312 V4 audit and return its manifest/report/request.

    The returned report is always produced by the real ROOT312 ``audit``
    entrypoint.  ``fail_first_decoder`` uses a test-owned decoder that fails
    exactly one invocation, exercising ROOT312's mixed completed/failed batch
    output without manufacturing that output in the test.
    """
    manifest_path, report_path = fixture._make_direct_root312_fixture(root)
    # The direct helper intentionally starts from one tiny source.  Give each
    # selected case its own producer-bound summary/records edge so V6 exercises
    # the real per-case identity check rather than a repeated summary fixture.
    manifest_value = json.loads(manifest_path.read_text(encoding="utf-8"))
    for contract_edge in manifest_value["contracts"]:
        case_id = contract_edge["physical_case_id"]
        contract_path = Path(contract_edge["path"])
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        base_summary = Path(contract["typed_deferred"]["summary"]["path"])
        base_records = Path(contract["typed_deferred"]["records"]["path"])
        summary_path = root / "case-metadata" / f"{case_id}.summary.json"
        records_path = root / "case-metadata" / f"{case_id}.records.jsonl"
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary = json.loads(base_summary.read_text(encoding="utf-8"))
        summary["physical_case_id"] = case_id
        summary_path.write_text(json.dumps(summary, sort_keys=True) + "\n", encoding="utf-8")
        records_path.write_bytes(base_records.read_bytes())
        summary_ref = _ref(summary_path)
        records_ref = {**_ref(records_path), "rows": 1, "deferred": True, "content_opened_by_preparer": False, "read_after_parent_reservation": True}
        contract["typed_deferred"]["summary"] = summary_ref
        contract["typed_deferred"]["records"] = records_ref
        contract_path.write_text(json.dumps(contract, sort_keys=True) + "\n", encoding="utf-8")
        contract_edge.update(_ref(contract_path))

    # Rebind both complete producer proof bundles to those exact edges.
    for bundle in manifest_value["proof_bundles"]:
        proof_path = Path(bundle["producer_proof"]["path"])
        proof = json.loads(proof_path.read_text(encoding="utf-8"))
        for row in proof["case_verifications"]:
            case_id = row["physical_case_id"]
            summary_path = root / "case-metadata" / f"{case_id}.summary.json"
            records_path = root / "case-metadata" / f"{case_id}.records.jsonl"
            if not summary_path.exists():
                # Diagnostic-only rows remain in each complete 8/8 proof but
                # are outside the selected contracts.
                summary_path = root / "base/typed-summary.json"
                records_path = root / "base/typed-records.jsonl"
            summary_ref = _ref(summary_path)
            records_ref = {**_ref(records_path), "rows": 1, "deferred": True, "content_opened_by_preparer": False, "read_after_parent_reservation": True}
            row["summary"] = str(summary_path.resolve())
            row["summary_sha256"] = summary_ref["sha256"]
            row["records_stat_only"] = records_ref
        proof_path.write_text(json.dumps(proof, sort_keys=True) + "\n", encoding="utf-8")
        bundle["producer_proof"] = _ref(proof_path)

    if fail_first_decoder:
        decoder = root / "base/tiny-partvtkout.sh"
        state = (root / "decoder-first-failure.state").resolve()
        original = decoder.read_text(encoding="utf-8")
        marker = "set -eu\n"
        injected = (
            marker
            + f"first_failure_state={state!s}\n"
            + "if [ ! -e \"$first_failure_state\" ]; then\n"
            + "  : > \"$first_failure_state\"\n"
            + "  exit 71\n"
            + "fi\n"
        )
        if marker not in original:
            raise AssertionError("tiny decoder fixture lacks its shell strict-mode marker")
        decoder.write_text(original.replace(marker, injected, 1), encoding="utf-8")
        manifest_value["official_sources"]["partvtkout"] = _ref(decoder)

    manifest_path.write_text(json.dumps(manifest_value, sort_keys=True) + "\n", encoding="utf-8")
    worker = fixture._load_root312_worker()
    worker_result = worker.audit(type("Args", (), {"manifest": manifest_path, "output": report_path})())
    expected_status = "COMPLETED_WITH_CASE_FAILURES" if fail_first_decoder else "COMPLETED_SELECTED_ORIGINAL118_NATIVE_DIAGNOSTIC_ONLY"
    if worker_result["status"] != expected_status:
        raise AssertionError(f"unexpected ROOT312 fixture status: {worker_result}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    static_paths: list[Path] = [manifest_path]
    for contract in manifest["contracts"]:
        static_paths.append(Path(contract["path"]))
    for bundle in manifest["proof_bundles"]:
        static_paths.append(Path(bundle["producer_proof"]["path"]))
    static_paths.extend([
        root / "base/typed-summary.json",
        root / "base/case-manifest.json",
        root / "base/case-receipt.json",
        root / "base/tiny-partvtkout.sh",
        SCRIPT_DIR / "ds_data02_stage2_build_root312_f4_native_extract_v4.py",
        SCRIPT_DIR / "ds_data02_stage2_build_generic_native_extract_v1.py",
    ])
    unique: list[Path] = []
    seen: set[str] = set()
    for path in static_paths:
        resolved = str(path.resolve())
        if resolved not in seen:
            seen.add(resolved)
            unique.append(path)
    request = {
        "schema": verifier.REQUEST_SCHEMA,
        "family_id": "F4",
        "physical_case_ids": manifest["physical_case_ids"],
        "manifest_contract": _ref(manifest_path),
        "command": [sys.executable, str(SCRIPT_DIR / "ds_data02_stage2_build_root312_f4_native_extract_v4.py"), "audit", "--manifest", str(manifest_path.resolve()), "--output", str(report_path.resolve())],
        "input_files": [str(path.resolve()) for path in unique],
        "input_sha256": {str(path.resolve()): _sha(path) for path in unique},
        "deferred_input_files": [str((root / "base/typed-records.jsonl").resolve()), str((root / "base/native-data/PartOut_000.obi4").resolve()), str((root / "base/RunPARTs.csv").resolve())],
        "official_sources": manifest["official_sources"],
    }
    request_path = root / "root312-request.json"
    request_path.write_text(json.dumps(request, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path, report_path, request_path


class Root312V6ProductionSchemaTests(unittest.TestCase):
    def test_real_root312_v4_report_schema_is_consumed_without_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path, report_path, request_path = _prepare_direct_root312_run(root)
            report_before = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report_before["schema"], verifier.ROOT312_PRODUCTION_REPORT_SCHEMA)
            before_bytes = report_path.read_bytes()
            output = verifier.verify(OVERLAY, manifest_path, request_path, report_path, PLAN, CURRENT)
            self.assertEqual(output["status"], "VERIFIED_GENERIC_OR_ROOT312_WORKER_OUTPUT_ALL_CASES")
            self.assertEqual(output["counts"]["worker_completed"], 7)
            self.assertEqual(report_path.read_bytes(), before_bytes)

    def test_v6_rejects_unknown_root312_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path, report_path, request_path = _prepare_direct_root312_run(root)
            invalid = json.loads(report_path.read_text(encoding="utf-8"))
            invalid["schema"] = "ds02.stage2.root312-f4-native-extract-report.unknown"
            invalid_path = root / "invalid-schema-report.json"
            invalid_path.write_text(json.dumps(invalid, sort_keys=True) + "\n", encoding="utf-8")
            with self.assertRaises(verifier.GenericJoinV5Error):
                verifier.verify(OVERLAY, manifest_path, request_path, invalid_path, PLAN, CURRENT)

    def test_v6_rejects_unknown_case_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path, report_path, request_path = _prepare_direct_root312_run(root)
            invalid = json.loads(report_path.read_text(encoding="utf-8"))
            invalid["case_results"][0]["status"] = "PENDING"
            invalid_path = root / "invalid-case-status-report.json"
            invalid_path.write_text(json.dumps(invalid, sort_keys=True) + "\n", encoding="utf-8")
            with self.assertRaises(verifier.GenericJoinV5Error):
                verifier.verify(OVERLAY, manifest_path, request_path, invalid_path, PLAN, CURRENT)

    def test_real_root312_mixed_decoder_failure_is_preserved_without_join(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path, report_path, request_path = _prepare_direct_root312_run(root, fail_first_decoder=True)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["schema"], verifier.ROOT312_PRODUCTION_REPORT_SCHEMA)
            self.assertEqual(report["status"], "COMPLETED_WITH_CASE_FAILURES")
            self.assertEqual(report["counts"], {"requested": 7, "completed": 6, "failed": 1})
            self.assertEqual(sum(row["status"] == "FAILED" for row in report["case_results"]), 1)
            before_bytes = report_path.read_bytes()
            output = verifier.verify(OVERLAY, manifest_path, request_path, report_path, PLAN, CURRENT)
            self.assertEqual(output["status"], "VERIFIED_GENERIC_OR_ROOT312_WORKER_OUTPUT_WITH_CASE_FAILURES")
            self.assertEqual(output["counts"]["worker_completed"], 6)
            self.assertEqual(output["counts"]["worker_failed"], 1)
            self.assertEqual(len(output["failures"]), 1)
            failed_id = output["failures"][0]["physical_case_id"]
            self.assertNotIn(failed_id, {row["physical_case_id"] for row in output["case_verifications"]})
            self.assertEqual(report_path.read_bytes(), before_bytes)

    def test_v6_enforces_ten_mebibyte_partout_cap_before_legacy_reader(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path, report_path, request_path = _prepare_direct_root312_run(root)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            original_case_output = Path(report["case_results"][0]["output"])
            oversized_case = root / "oversized-case-output.json"
            case_output = json.loads(original_case_output.read_text(encoding="utf-8"))
            case_output["native"]["partout_csv"]["pre_stat"]["bytes"] = verifier.MAX_CSV + 1
            oversized_case.write_text(json.dumps(case_output, sort_keys=True) + "\n", encoding="utf-8")
            report["case_results"][0]["output"] = str(oversized_case.resolve())
            oversized_report = root / "oversized-report.json"
            oversized_report.write_text(json.dumps(report, sort_keys=True) + "\n", encoding="utf-8")
            with self.assertRaises(verifier.GenericJoinV5Error):
                verifier.verify(OVERLAY, manifest_path, request_path, oversized_report, PLAN, CURRENT)


if __name__ == "__main__":
    unittest.main(verbosity=2)
