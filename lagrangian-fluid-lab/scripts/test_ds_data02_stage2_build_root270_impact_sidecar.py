from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ds_data02_stage2_build_root270_impact_sidecar as subject


def write_json(path: Path, value: dict) -> Path:
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return path


def typed_summary() -> dict:
    return {
        "role_ledgers": {
            "fluid": {
                "initial_count": 4,
                "initial_mass_kg": 4.0,
                "units": {"mass": "kg", "time": "s"},
                "active_count_by_frame": [4, 3],
                "active_mass_kg_by_frame": [4.0, 3.0],
            }
        },
        "timeline": {"time_s": [0.0, 1.0]},
    }


def manifest_case(summary_path: Path, *, native_path: Path | None = None, case_id: str = "FIXTURE_CASE") -> dict:
    binding = {
        "status": "BOUND_ACTUAL_NATIVE_REPORT" if native_path else "UNKNOWN_NO_NATIVE_BINDING",
        "source": "FIXTURE_NATIVE" if native_path else "UNKNOWN_NO_NATIVE_BINDING",
        "native_target_count": 1 if native_path else None,
        "native_exact_initial_mass_kg": None,
        "native_exact_mass_rows": None,
        "native_initial_mass_source": "NO_PER_ROW_INITIAL_MASS_FIELD" if native_path else "UNKNOWN",
        "role_average_proxy_mass_kg": 1.0 if native_path else None,
        "proxy_uniformity": "UNVERIFIED_ROLE_AVERAGE_PROXY_ONLY" if native_path else "UNKNOWN_NO_NATIVE_BINDING",
        "native_saved_frame_join": "EXACT_ID_AND_SAVED_BRACKET_INPUT_REPORT" if native_path else "UNKNOWN",
    }
    if native_path:
        binding["report"] = {"path": str(native_path), "sha256": subject._digest(native_path, "fixture native")}
    return {
        "physical_case_id": case_id,
        "family_id": "F6",
        "typed_summary": {"path": str(summary_path), "sha256": subject._digest(summary_path, "fixture summary")},
        "source_v1": {"status": "TYPED_ONLY_NO_NATIVE_JOIN", "native_join": "NOT_AVAILABLE"},
        "semantic_v2": {"native_binding": binding},
    }


class Root270ImpactSidecarTests(unittest.TestCase):
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

    def test_typed_only_native_fields_are_null_not_zero(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            summary = write_json(root / "summary.json", typed_summary())
            manifest = write_json(root / "manifest.json", {
                "schema": subject.MANIFEST_SCHEMA,
                "status": "READY_SOURCE_ONLY_ROOT270_ADDITIVE_NATIVE_REBIND_IMPACT_DIAGNOSTIC",
                "claim_boundary": {"physical_mass_flux": "UNKNOWN", "physical_fate": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
                "source_refs": [],
                "cases": [manifest_case(summary, case_id=f"FIXTURE_CASE_{index}") for index in range(19)],
            })
            output = root / "audit.json"
            result = subprocess.run([sys.executable, str(subject.SCRIPT), "audit", "--manifest", str(manifest), "--output", str(output)], check=True, capture_output=True, text=True)
            value = json.loads(result.stdout)
            self.assertEqual(value["typed_only_native_binding_unknown"], 19)
            row = json.loads(output.read_text(encoding="utf-8"))["case_results"][0]
            binding = row["semantic_v2"]["native_binding"]
            self.assertIsNone(binding["native_target_count"])
            self.assertIsNone(binding["native_exact_initial_mass_kg"])
            self.assertIsNone(binding["native_exact_mass_rows"])
            self.assertIsNone(binding["role_average_proxy_mass_kg"])

    def test_native_report_without_row_mass_uses_unverified_proxy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            summary = write_json(root / "summary.json", typed_summary())
            native = write_json(root / "native.json", {
                "physical_case_id": "FIXTURE_CASE",
                "family_id": "F6",
                "rows": [{
                    "zone": 0,
                    "idp": 2,
                    "first_missing_frame": 1,
                    "first_missing_time_s": 1.0,
                    "bracket_s": [0.5, 1.5],
                    "motive_code": 1,
                }],
            })
            manifest = write_json(root / "manifest.json", {
                "schema": subject.MANIFEST_SCHEMA,
                "status": "READY_SOURCE_ONLY_ROOT270_ADDITIVE_NATIVE_REBIND_IMPACT_DIAGNOSTIC",
                "claim_boundary": {"physical_mass_flux": "UNKNOWN", "physical_fate": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
                "source_refs": [],
                "cases": [manifest_case(summary, native_path=native)] + [manifest_case(summary, case_id=f"FIXTURE_CASE_{index}") for index in range(1, 19)],
            })
            output = root / "audit.json"
            subprocess.run([sys.executable, str(subject.SCRIPT), "audit", "--manifest", str(manifest), "--output", str(output)], check=True, capture_output=True, text=True)
            row = json.loads(output.read_text(encoding="utf-8"))["case_results"][0]
            binding = row["semantic_v2"]["native_binding"]
            self.assertEqual(binding["native_target_count"], 1)
            self.assertIsNone(binding["native_exact_initial_mass_kg"])
            self.assertIsNone(binding["native_exact_mass_rows"])
            self.assertEqual(binding["role_average_proxy_mass_kg"], 1.0)
            self.assertEqual(binding["proxy_uniformity"], "UNVERIFIED_ROLE_AVERAGE_PROXY_ONLY")
            self.assertEqual(row["semantic_v2"]["sample_mass_impact"]["physical_mass_flux"], "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
