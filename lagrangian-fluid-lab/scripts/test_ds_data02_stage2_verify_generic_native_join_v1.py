#!/usr/bin/env python3
"""Focused tests for the additive six-proof native/typed join verifier."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parent / "ds_data02_stage2_verify_generic_native_join_v1.py"
spec = importlib.util.spec_from_file_location("stage2_generic_join_verifier_v1", SCRIPT)
assert spec is not None and spec.loader is not None
MODULE = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = MODULE
spec.loader.exec_module(MODULE)

ROOT = SCRIPT.parents[2]
STAGE2 = ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
JOIN_SOURCE = STAGE2 / "requests/native-typed-native-join-source-root315-prepared-002/native-typed-native-join-source-v1.json"
INVENTORY = STAGE2 / "checkpoints/HISTORICAL118_NATIVE_TYPED_SOURCE_INVENTORY_AFTER_ROOT193_V1.json"
CURRENT = STAGE2 / "CURRENT336.json"
OVERLAY = STAGE2 / "checkpoints/ORIGINAL118_NATIVE_CAUSE_AFTER_ROOT268_ACTUAL_OVERLAY_V10.json"
MANIFESTS = [
    STAGE2 / "requests/generic-native-extract-v2-root315-f2-missing-join-prepared-003/generic-native-extract-v2-manifest.json",
    STAGE2 / "requests/generic-native-extract-v3-root317-f2-root198-missing-join-prepared-002/generic-native-extract-v3-manifest.json",
    STAGE2 / "requests/generic-native-extract-v3-root318-f2-root206-missing-join-prepared-001/generic-native-extract-v3-manifest.json",
    STAGE2 / "requests/generic-native-extract-v3-root319-f2-root287-missing-join-prepared-001/generic-native-extract-v3-manifest.json",
    STAGE2 / "requests/generic-native-extract-v3-root320-f2-root288-missing-join-prepared-001/generic-native-extract-v3-manifest.json",
    STAGE2 / "requests/generic-native-extract-v3-root321-f2-root289-missing-join-prepared-001/generic-native-extract-v3-manifest.json",
]


def ref(path: Path) -> dict[str, object]:
    raw = path.read_bytes()
    stat = path.stat()
    return {
        "path": str(path),
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "ctime_ns": stat.st_ctime_ns,
        "st_dev": stat.st_dev,
        "st_ino": stat.st_ino,
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def make_spec(directory: Path, *, join_path: Path = JOIN_SOURCE, overrides: dict[str, list[str]] | None = None) -> Path:
    entries = []
    for manifest in MANIFESTS:
        document = json.loads(manifest.read_text(encoding="utf-8"))
        producer = document["typed_proof_bundles"][0]["producer_id"]
        entry = ref(manifest)
        if overrides and producer in overrides:
            entry["selected_case_ids"] = overrides[producer]
        entries.append(entry)
    value = {
        "schema": MODULE.SOURCE_SCHEMA,
        "alias_case": MODULE.ALIAS_CASE,
        "producer_manifests": entries,
        "historical_inventory": ref(INVENTORY),
        "current_catalog": ref(CURRENT),
        "existing_join_source": ref(join_path),
        "cause_overlay": ref(OVERLAY),
    }
    path = directory / "source-spec.json"
    write_json(path, value)
    return path


class GenericNativeJoinVerifierTests(unittest.TestCase):
    def prepare_scope(self, directory: Path) -> tuple[Path, dict[str, object]]:
        spec_path = make_spec(directory)
        scope = MODULE._source_scope_from_spec(spec_path)
        manifest_path = directory / "join-manifest.json"
        MODULE._atomic_json(manifest_path, scope)
        return manifest_path, scope

    def test_prepare_adapts_six_old_proof_manifests_and_accounting(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            scope = MODULE._source_scope_from_spec(make_spec(Path(td)))
        self.assertEqual(scope["case_scope"]["original_case_count"], 118)
        self.assertEqual(scope["case_scope"]["existing_exact_join_count"], 47)
        self.assertEqual(scope["case_scope"]["cause_not_located_count"], 24)
        self.assertEqual(scope["case_scope"]["cause_bound_missing_join_count"], 47)
        self.assertEqual(scope["case_scope"]["selected_canonical_count"], 46)
        self.assertEqual(scope["case_scope"]["remaining_cause_bound_missing_case_ids"], [MODULE.ALIAS_CASE])
        self.assertEqual({x["producer_id"] for x in scope["producer_proof_bundles"]}, {"ROOT193", "ROOT198", "ROOT206", "ROOT287", "ROOT288", "ROOT289"})
        self.assertFalse(scope["claim_boundary"]["synthetic_proof_merge"])
        self.assertTrue(scope["claim_boundary"]["alias_is_not_substituted"])

    def test_prepare_rejects_alias_and_duplicate_cross_producer_selection(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td)
            first = json.loads(MANIFESTS[0].read_text(encoding="utf-8"))["typed_proof_bundles"][0]["full_case_ids"][0]
            with self.assertRaises(MODULE.JoinVerificationError):
                MODULE._source_scope_from_spec(make_spec(directory, overrides={"ROOT193": [MODULE.ALIAS_CASE]}))
            # An ID from ROOT193 cannot be selected for ROOT198 because each
            # selected subset must remain inside its own complete proof.
            with self.assertRaises(MODULE.JoinVerificationError):
                MODULE._source_scope_from_spec(make_spec(directory, overrides={"ROOT198": [first]}))

    def test_prepare_accepts_selected_subset_while_retaining_complete_proof_edges(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td)
            overrides = {}
            for manifest in MANIFESTS:
                document = json.loads(manifest.read_text(encoding="utf-8"))
                bundle = document["typed_proof_bundles"][0]
                overrides[bundle["producer_id"]] = [bundle["full_case_ids"][0]]
            scope = MODULE._source_scope_from_spec(make_spec(directory, overrides=overrides))
        self.assertEqual(scope["case_scope"]["selected_canonical_count"], 6)
        self.assertEqual(len(scope["case_source_edges"]), 6)
        self.assertEqual(scope["producer_proof_bundles"][0]["full_case_count"], 8)
        self.assertEqual(scope["producer_proof_bundles"][-1]["full_case_count"], 6)
        self.assertIn(MODULE.ALIAS_CASE, scope["case_scope"]["remaining_cause_bound_missing_case_ids"])

    def _write_result_fixture(self, directory: Path, manifest_path: Path, scope: dict[str, object], *, duplicate_row: bool = False) -> Path:
        selected = list(scope["case_scope"]["selected_case_ids"])
        case_ids = selected[:2]
        case_results = []
        for index, case_id in enumerate(case_ids, start=1):
            producer = scope["producer_case_index"][case_id]
            summary_path = directory / f"summary-{index}.json"
            native_path = directory / f"native-{index}.csv"
            runparts_path = directory / f"runparts-{index}.csv"
            write_json(summary_path, {
                "schema": "ds02.stage2.typed-lifecycle-v4-summary.v1",
                "physical_case_id": case_id,
                "first_missing_rows": [{
                    "zone": 0,
                    "idp": index,
                    "role": "fluid",
                    "type": 3,
                    "first_missing_frame": 3,
                    "first_missing_time_s": 0.3,
                    "saved_bracket_time_s": [0.2, 0.3],
                }],
            })
            native_path.write_text("Idp,Motive,PartOut\n%d,1,1\n" % index, encoding="utf-8")
            runparts_path.write_text(
                "Part,TimeStep [s],Steps,NpOut\n0,0.2,1,0\n1,0.3,2,1\n",
                encoding="utf-8",
            )
            joined = {
                "zone": 0,
                "idp": index,
                "native_motive_code": 1,
                "typed_first_missing_frame": 3,
                "typed_first_missing_time_s": 0.3,
            }
            joined_rows = [joined, dict(joined)] if duplicate_row else [joined]
            case_results.append({
                "physical_case_id": case_id,
                "producer_id": producer,
                "status": "COMPLETED_SOURCE_BOUND_JOIN_DIAGNOSTIC_ONLY",
                "typed_summary": ref(summary_path),
                "native_csv": ref(native_path),
                "runparts_csv": ref(runparts_path),
                "joined_rows": joined_rows,
            })
        result_path = directory / "result.json"
        write_json(result_path, {
            "schema": MODULE.RESULT_SCHEMA,
            "manifest": ref(manifest_path),
            "requested_case_ids": case_ids,
            "case_results": case_results,
            "counts": {"requested_cases": 2, "completed_cases": 2, "failed_cases": 0},
            "new_native_cause_credit": 0,
            "physical_fate": "UNKNOWN",
            "legal_flux": "UNKNOWN",
            "dynamics": "UNKNOWN",
        })
        return result_path

    def test_verify_cli_accepts_small_csv_runparts_summary_and_reports_join_only(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td)
            manifest_path, scope = self.prepare_scope(directory)
            result_path = self._write_result_fixture(directory, manifest_path, scope)
            report_path = directory / "report.json"
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "verify", "--manifest", str(manifest_path), "--result", str(result_path), "--output", str(report_path)],
                text=True,
                capture_output=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["counts"]["new_typed_native_join_credit"], 2)
            self.assertEqual(report["counts"]["new_native_cause_credit"], 0)
            self.assertEqual(report["claim_boundary"]["physical_fate"], "UNKNOWN")

    def test_verify_rejects_duplicate_identity_and_already_joined_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td)
            manifest_path, scope = self.prepare_scope(directory)
            duplicate_result = self._write_result_fixture(directory, manifest_path, scope, duplicate_row=True)
            with self.assertRaises(MODULE.JoinVerificationError):
                MODULE._verify_result(manifest_path, duplicate_result)

            tampered = json.loads(manifest_path.read_text(encoding="utf-8"))
            tampered["case_scope"]["existing_join_case_ids"].append(tampered["case_scope"]["selected_case_ids"][0])
            tampered_path = directory / "tampered-manifest.json"
            write_json(tampered_path, tampered)
            valid_result = self._write_result_fixture(directory, manifest_path, scope)
            with self.assertRaises(MODULE.JoinVerificationError):
                MODULE._verify_result(tampered_path, valid_result)


if __name__ == "__main__":
    unittest.main()
