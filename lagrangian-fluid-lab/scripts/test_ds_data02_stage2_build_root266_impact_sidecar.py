from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ds_data02_stage2_build_root266_impact_sidecar as subject


def write_json(path: Path, value: dict) -> Path:
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return path


def summary() -> dict:
    return {
        "role_ledgers": {"fluid": {
            "initial_count": 4,
            "initial_mass_kg": 4.0,
            "units": {"mass": "kg", "time": "s"},
            "active_count_by_frame": [4, 3],
            "active_mass_kg_by_frame": [4.0, 3.0],
        }},
        "timeline": {"time_s": [0.0, 1.0]},
    }


class Root266ImpactSidecarTests(unittest.TestCase):
    def test_self_test_is_payload_free(self) -> None:
        result = subprocess.run(
            [sys.executable, str(subject.SCRIPT), "self-test"],
            check=True,
            capture_output=True,
            text=True,
        )
        value = json.loads(result.stdout)
        self.assertEqual(value["status"], "PASS")
        self.assertFalse(value["payload_opened"])

    def test_real_audit_subprocess_dispatches_audit_function(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            summary_path = write_json(root / "typed-summary.json", summary())
            native_path = write_json(root / "native-report.json", {
                "physical_case_id": "F4_FIXTURE",
                "family_id": "F4",
                "rows": [{
                    "zone": 0,
                    "idp": 2,
                    "first_missing_frame": 1,
                    "first_missing_time_s": 1.0,
                    "bracket_s": [0.5, 1.5],
                    "motive_code": 1,
                    "initial_mass_kg": 1.0,
                }],
            })
            typed_ref = {
                "path": str(summary_path),
                "sha256": subject._digest(summary_path, "fixture typed summary"),
            }
            native_ref = {
                "path": str(native_path),
                "sha256": subject._digest(native_path, "fixture native report"),
            }
            manifest = write_json(root / "manifest.json", {
                "schema": subject.MANIFEST_SCHEMA,
                "status": "READY_SOURCE_ONLY_TYPED_NATIVE_IMPACT_DIAGNOSTIC",
                "claim_boundary": {
                    "physical_mass_flux": "UNKNOWN",
                    "physical_fate": "UNKNOWN",
                    "dynamics": "UNKNOWN",
                    "QI": "UNKNOWN",
                    "QN": "UNKNOWN",
                    "QE": "UNKNOWN",
                },
                "cases": [{
                    "physical_case_id": "F4_FIXTURE",
                    "family_id": "F4",
                    "typed_summary": typed_ref,
                    "native_report": native_ref,
                }],
            })
            output = root / "audit.json"
            result = subprocess.run(
                [sys.executable, str(subject.SCRIPT), "audit", "--manifest", str(manifest), "--output", str(output)],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(json.loads(result.stdout)["failed"], 0)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["counts"], {"completed": 1, "failed": 0, "requested": 1, "typed_only": 0})
            impact = report["case_results"][0]["impact"]
            self.assertEqual(impact["native_exact_initial_mass_kg"], 1.0)
            self.assertEqual(impact["physical_mass_flux"], "UNKNOWN")

    def test_invalid_units_and_saved_frame_mismatch_are_rejected(self) -> None:
        value = summary()
        bad_units = json.loads(json.dumps(value))
        bad_units["role_ledgers"]["fluid"]["units"]["mass"] = "g"
        with self.assertRaises(subject.ImpactError):
            subject._validate_summary(bad_units, "bad-units")
        with self.assertRaises(subject.ImpactError):
            subject._frame_sample(value, [{
                "identity_key": [0, 2],
                "frame": 1,
                "time_s": 0.0,
                "bracket_s": [0.5, 1.5],
                "initial_mass_kg": 1.0,
            }])


if __name__ == "__main__":
    unittest.main()
