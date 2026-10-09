"""Fixture and source-only contract tests for the scientific field-gap audit."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SCRIPT_DIR = Path(__file__).resolve().parent
MODULE_PATH = SCRIPT_DIR / "ds_data02_stage2_scientific_field_gap_audit_v1.py"
spec = importlib.util.spec_from_file_location("scientific_field_gap_audit_v1", MODULE_PATH)
assert spec and spec.loader
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _row(*, idp: int = 7, mass: float = 0.25) -> dict[str, object]:
    return {
        "zone": 0,
        "idp": idp,
        "initial_type_code": 3,
        "initial_role": "fluid",
        "initial_mass_kg": mass,
        "initially_active": True,
        "new_id": False,
        "first_active_frame": 0,
        "first_active_time_s": 0.0,
        "last_active_frame": 2,
        "last_active_time_s": 0.2,
        "first_disappeared_frame": 2,
        "first_disappeared_time_s": 0.2,
        "first_disappeared_bracket_s": [0.1, 0.2],
        "reappearance_count": 0,
        "first_reappearance_frame": None,
        "first_reappearance_time_s": None,
        "last_reappearance_frame": None,
        "last_reappearance_time_s": None,
        "missing_at_final": True,
        "censoring": "OBSERVED_DISAPPEARANCE",
        "unknown": {
            "valid_mask_unknown_frame_count": 0,
            "active_type_unknown_frame_count": 0,
            "inactive_type_sentinel_frame_count": 0,
            "active_nonfinite_field_counts": {field: 0 for field in ("position", "velocity", "density", "mass", "pressure")},
            "type_changed_active_frame_count": 0,
        },
        "native_exit_cause": "UNKNOWN",
        "physical_fate": "UNKNOWN",
        "legal_flux": "UNKNOWN",
        "dynamical_impact": "UNKNOWN",
    }


class ScientificFieldGapAuditTests(unittest.TestCase):
    def test_prepare_binds_root304_without_payload_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "prepared"
            report = root / "gap-report.json"
            result = audit.prepare(
                type("Args", (), {
                    "current": audit.CURRENT_DEFAULT,
                    "closure": audit.CLOSURE_DEFAULT,
                    "terminal_proof": audit.PROOF_DEFAULT,
                    "case_id": "F7_OBSTACLE_QUINTIC_B08_A036P5",
                    "worker": MODULE_PATH,
                    "runtime": audit.RUNTIME_DEFAULT,
                    "dispatch": audit.DISPATCH_DEFAULT,
                    "strict": audit.STRICT_DEFAULT,
                    "config": audit.CONFIG_DEFAULT,
                    "python": audit.VENV_DEFAULT,
                    "output_dir": output,
                    "gap_report": report,
                })(),
            )
            self.assertEqual(result["status"], "prepared")
            request = json.loads(Path(result["request"]).read_text(encoding="utf-8"))
            self.assertEqual(request["claim_boundary"]["unit_authority"], "UNKNOWN_UNVERIFIED")
            self.assertEqual(request["read_policy"]["trajectory_h5_opened"], False)
            self.assertEqual(request["read_policy"]["records_jsonl_opened_after_reservation"], True)
            self.assertIn("records_jsonl", {ref["role"] for ref in request["deferred_input_records"]})
            self.assertEqual(json.loads(report.read_text(encoding="utf-8"))["goal_complete"], False)

    def test_tiny_audit_checks_record_scalars_but_keeps_science_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            records = root / "records.jsonl"
            header = {
                "schema": "ds02.stage2.typed-lifecycle-records.v4",
                "record_fields": "one row per static (Zone, Idp); saved-frame lifecycle only",
            }
            records.write_text(json.dumps(header) + "\n" + json.dumps(_row()) + "\n", encoding="utf-8")
            ref = audit.stat_ref(records, "records")
            ref["sha256"] = audit.sha256_file(records)
            manifest = root / "manifest.json"
            _write(manifest, {
                "schema": audit.MANIFEST_SCHEMA,
                "status": "READY_FOR_GUARDED_TYPED_RECORD_FIELD_AUDIT",
                "physical_case_id": "TINY_F7",
                "family_id": "F7",
                "records_contract": {**ref, "known_sha256": ref["sha256"]},
            })
            output = root / "audit.json"
            result = audit.audit(manifest, output)
            self.assertEqual(result["status"], "COMPLETED_RECORD_FIELD_AUDIT_NO_SCIENTIFIC_CREDIT")
            value = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(value["records"]["unique_identity_rows"], 1)
            self.assertEqual(value["checks"]["raw_frame_value_finiteness"], "NOT_EXPOSED_BY_RECORDS")
            self.assertEqual(value["scientific_qualification"]["QI"], "UNKNOWN")

    def test_tiny_audit_rejects_duplicate_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            records = root / "records.jsonl"
            header = {"schema": "ds02.stage2.typed-lifecycle-records.v4"}
            records.write_text(json.dumps(header) + "\n" + json.dumps(_row()) + "\n" + json.dumps(_row()) + "\n", encoding="utf-8")
            ref = audit.stat_ref(records, "records")
            ref["sha256"] = audit.sha256_file(records)
            manifest = root / "manifest.json"
            _write(manifest, {
                "schema": audit.MANIFEST_SCHEMA,
                "status": "READY_FOR_GUARDED_TYPED_RECORD_FIELD_AUDIT",
                "physical_case_id": "TINY_F7",
                "family_id": "F7",
                "records_contract": {**ref, "known_sha256": ref["sha256"]},
            })
            output = root / "audit.json"
            result = audit.audit(manifest, output)
            self.assertEqual(result["status"], "COMPLETED_RECORD_FIELD_AUDIT_WITH_SCHEMA_FAILURES")
            value = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(value["invalid_row_count"], 1)
            self.assertIn("duplicate_identity", value["sample_errors"][0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
