from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ds_data02_stage2_build_native_typed_mass_impact_v6 as worker
import ds_data02_stage2_verify_native_typed_mass_impact_v6 as subject


def _load_legacy_fixture():
    path = Path(__file__).with_name("test_ds_data02_stage2_verify_native_typed_mass_impact_v5.py")
    spec = importlib.util.spec_from_file_location("legacy_mass_v5_tests", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


LEGACY = _load_legacy_fixture()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ref(path: Path) -> dict[str, object]:
    raw = path.read_bytes()
    st = path.stat()
    return {"path": str(path.resolve()), "bytes": st.st_size, "mtime_ns": st.st_mtime_ns, "ctime_ns": st.st_ctime_ns, "st_dev": st.st_dev, "st_ino": st.st_ino, "sha256": hashlib.sha256(raw).hexdigest()}


def _prepare_v6_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    manifest, _old_result, typed = LEGACY._make_fixture(tmp_path)
    root = tmp_path
    case_id = "F4_FIXTURE_MASS_V4"
    # This is the exact V4 producer JSONL header/row contract.  It is a tiny
    # fixture only; no production payload is opened by the verifier.
    typed.write_text(
        json.dumps({"schema": "ds02.stage2.typed-lifecycle-records.v4", "status": "COMPLETED_TYPED_LIFECYCLE_RECORDS_NO_PHYSICAL_CREDIT", "family_id": "F4", "physical_case_id": case_id, "record_fields": "one row per static (Zone, Idp); saved-frame lifecycle only"})
        + "\n"
        + json.dumps({"zone": 0, "idp": 10, "initial_role": "fluid", "initial_type_code": 3, "initial_mass_kg": 0.125})
        + "\n"
        + json.dumps({"zone": 0, "idp": 11, "initial_role": "fluid", "initial_type_code": 3})
        + "\n",
        encoding="utf-8",
    )
    typed_ref = {**_ref(typed), "rows": 2, "deferred": True, "content_opened_by_preparer": False, "read_after_parent_reservation": True}
    value = json.loads(manifest.read_text(encoding="utf-8"))
    proof_path = root / "proof.json"
    proof = {"schema": subject.ROOT_PROOF_SCHEMA, "status": "VERIFIED_ACTUAL_OLD_SINGLE_CASE_NO_PHYSICAL_CREDIT", "physical_case_id": case_id}
    proof_path.write_text(json.dumps(proof, sort_keys=True) + "\n", encoding="utf-8")
    proof_ref = _ref(proof_path)
    case = value["cases"][0]
    case["producer_proof"] = proof_ref
    case["typed_records_deferred"] = typed_ref
    value["schema"] = "ds02.stage2.native-typed-mass-impact.v6-manifest"
    value["status"] = "READY_SOURCE_ONLY_NATIVE_TYPED_MASS_IMPACT_V6"
    value["producer_proof_merge"] = {"created": False, "meaning": "single producer proof remains independent"}
    value["proof_bundles"] = [{"bundle_id": "ROOT_SINGLE", "producer_proof": proof_ref, "full_case_ids": [case_id], "selected_case_ids": [case_id], "producer_proof_preserved": True}]
    value["source_refs"] = [proof_ref, case["native_report"]]
    value["claim_boundary"] = {"physical_mass_flux": "UNKNOWN", "physical_fate": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
    manifest.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")

    output = root / "worker-report.json"
    worker.audit(argparse.Namespace(manifest=manifest, output=output))
    return manifest, output, typed


class NativeTypedMassImpactV6Tests(unittest.TestCase):
    def test_tiny_worker_then_independent_verifier_exact_and_null_mass_old_single_proof(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            manifest, result, deferred = _prepare_v6_fixture(Path(td))
            output = Path(td) / "verification.json"
            value = subject.verify(argparse.Namespace(manifest=manifest, result=result, output=output))
            self.assertEqual(value["status"], "PASS_SOURCE_IDENTITY_STAT_ONLY")
            checked = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(checked["counts"]["completed"], 1)
            self.assertFalse(checked["read_policy"]["deferred_jsonl_content_opened"])
            rows = json.loads(result.read_text(encoding="utf-8"))["case_results"][0]["selected_native_ids"]
            self.assertEqual(rows[0]["typed_mass_status"], "EXACT_TYPED_JSONL_INITIAL_MASS")
            self.assertEqual(rows[1]["typed_mass_status"], "UNKNOWN_MISSING_TYPED_INITIAL_MASS")
            self.assertEqual(deferred.read_bytes().count(b"initial_mass_kg"), 1)

    def test_partial_failed_worker_result_has_no_mass_credit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            manifest, result, _ = _prepare_v6_fixture(Path(td))
            value = json.loads(result.read_text(encoding="utf-8"))
            value["status"] = "COMPLETED_WITH_CASE_FAILURES"
            value["counts"] = {"requested": 1, "completed": 0, "failed": 1, "selected_native_ids": 0}
            value["case_results"] = [{"physical_case_id": "F4_FIXTURE_MASS_V4", "status": "FAILED", "error_type": "ControlledFixtureFailure", "error_message": "synthetic", "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}}]
            result.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
            output = Path(td) / "verification-failed.json"
            checked = subject.verify(argparse.Namespace(manifest=manifest, result=result, output=output))
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["counts"]["failed"], 1)
            self.assertEqual(report["case_verifications"][0]["status"], "FAILED_NO_MASS_CREDIT")

    def test_v6_rejects_result_manifest_binding_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            manifest, result, _ = _prepare_v6_fixture(Path(td))
            value = json.loads(result.read_text(encoding="utf-8"))
            value["source_manifest"]["sha256"] = "0" * 64
            result.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
            with self.assertRaises(subject.VerificationError, msg="result must bind exact V6 manifest"):
                subject.verify(argparse.Namespace(manifest=manifest, result=result, output=Path(td) / "bad.json"))


if __name__ == "__main__":
    unittest.main()
