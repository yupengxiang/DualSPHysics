#!/usr/bin/env python3
"""Synthetic bounded tests for the additive V3 HDF5 audit worker.

Only temporary synthetic HDF5 files are opened here.  No production HDF5,
BI4, trajectory, or native payload is read.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

try:
    import h5py  # type: ignore
    import numpy as np  # type: ignore
except ImportError:  # pragma: no cover - environment dependent
    h5py = None
    np = None


SCRIPT = Path(__file__).with_name("ds_data02_stage2_scientific_field_h5_audit_v3.py")
SPEC = importlib.util.spec_from_file_location("scientific_field_h5_audit_v3", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


@unittest.skipUnless(h5py is not None and np is not None, "numpy/h5py are required for synthetic HDF5 tests")
class ScientificFieldH5AuditV3Tests(unittest.TestCase):
    def _write_case(self, root: Path, *, include_initial_type: bool = True) -> tuple[dict, Path]:
        path = root / ("tiny-with-type.h5" if include_initial_type else "tiny-without-type.h5")
        frames, particles = 3, 4
        with h5py.File(path, "w") as h5:
            h5.create_dataset("time", data=np.array([0.0, 1.0, 2.0]))
            h5.create_dataset("particle_id", data=np.array([10, 11, 12, 13], dtype=np.int64))
            h5.create_dataset("particle_zone", data=np.zeros(particles, dtype=np.int64))
            if include_initial_type:
                h5.create_dataset("initial_type", data=np.array([0, 1, 3, 3], dtype=np.int8))
            h5.create_dataset("initial_mass", data=np.array([1.0, 2.0, 3.0, 4.0]))
            h5.create_dataset("position", data=np.arange(frames * particles * 3, dtype=np.float64).reshape(frames, particles, 3))
            h5.create_dataset("velocity", data=np.ones((frames, particles, 3), dtype=np.float64))
            h5.create_dataset("density", data=np.full((frames, particles), 1000.0))
            mass = np.array([[1.0, 2.0, 3.0, 4.0], [1.1, 2.0, 3.0, 4.0], [1.2, 2.0, 3.0, 4.0]])
            h5.create_dataset("mass", data=mass)
            h5.create_dataset("pressure", data=np.array([[101325.0, -2.0, 3.0, 4.0]] * frames))
            valid = np.ones((frames, particles), dtype=np.int8)
            valid[1, 1] = 0
            h5.create_dataset("valid", data=valid)
            frame_type = np.array([[0, 1, 3, 3]] * frames, dtype=np.int8)
            h5.create_dataset("type", data=frame_type)
            h5.attrs["units_json"] = json.dumps(MODULE.UNIT_PROTOCOL, sort_keys=True)
            h5.attrs["coordinate_frame"] = "synthetic-frame"
        h5_stat = MODULE.stat_ref(path, "trajectory_h5")
        case = {
            "physical_case_id": "TINY_V3_CASE",
            "family_id": "F1",
            "trajectory_h5": {**h5_stat, "known_sha256": MODULE.sha256_file(path)},
            "expected_frames": frames,
            "expected_particles": particles,
            "expected_units": dict(MODULE.UNIT_PROTOCOL),
        }
        for index, field in enumerate(("producer_terminal_proof", "case_manifest", "producer_receipt", "typed_summary")):
            ref_path = root / f"{field}.json"
            ref_path.write_text(json.dumps({"field": field}), encoding="utf-8")
            case[field] = MODULE.static_ref(ref_path, field)
        return case, path

    def test_vectorized_role_reductions_and_postread_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            case, _ = self._write_case(Path(directory))
            result = MODULE.scan_case(case, chunk=2, binding={"manifest_sha256": "b" * 64})
            self.assertEqual(result["worker_version"], "v3_vectorized_postread_guard")
            self.assertTrue(result["field_scan"]["vectorized_chunk_reductions"])
            self.assertTrue(result["source_binding"]["trajectory_h5"]["post_capture_after_all_dataset_and_attribute_reads"])
            self.assertEqual(result["initial_type"]["status"], "PRESENT_VALID_CODES")
            self.assertEqual(result["initial_type"]["role_counts"]["fluid"], 2)
            self.assertEqual(result["field_scan"]["roles"]["fluid"]["observed_active_count"], 6)
            self.assertAlmostEqual(result["physical_ranges"]["per_role_mass_extrema_and_drift"]["fixed"]["drift_abs_max_kg"], 0.1)
            self.assertEqual(result["field_scan"]["observations"]["pressure"]["active_negative"], 2)
            self.assertEqual(result["field_scan"]["observations"]["mass"]["inactive_nonfinite"], 0)

    def test_missing_initial_type_is_explicit_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            case, _ = self._write_case(Path(directory), include_initial_type=False)
            result = MODULE.scan_case(case, chunk=3, binding={"manifest_sha256": "c" * 64})
            self.assertEqual(result["initial_type"]["status"], "NOT_EXPOSED")
            self.assertTrue(result["initial_type"]["unknown_is_explicit"])
            self.assertEqual(result["initial_type"]["role_counts"]["unknown_initial_type"], 4)
            self.assertEqual(result["field_scan"]["active_finite_status"], "INITIAL_TYPE_UNKNOWN")

    def test_guarded_audit_entry_accepts_v2_manifest_and_writes_v3_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case, _ = self._write_case(root)
            current_ref = MODULE.static_ref(MODULE.CURRENT_DEFAULT, "fixture CURRENT")
            manifest = {
                "schema": MODULE.MANIFEST_SCHEMA,
                "status": "READY_FOR_GUARDED_RAW_H5_FIELD_AUDIT",
                "current_catalog": {"path": str(MODULE.CURRENT_DEFAULT), "sha256": MODULE.CURRENT_SHA256, "cases": 336},
                "static_source_refs": [current_ref, case["producer_terminal_proof"], case["case_manifest"], case["producer_receipt"], case["typed_summary"]],
                "cases": [case],
            }
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            output_path = root / "report.json"
            result = MODULE.audit(manifest_path, output_path, chunk=2)
            self.assertEqual(result["completed"], 1)
            report = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(report["schema"], "ds02.stage2.scientific-field-h5-audit.v3")
            self.assertTrue(report["case_results"][0]["source_binding"]["trajectory_h5"]["post_capture_after_all_dataset_and_attribute_reads"])

    def test_source_does_not_reintroduce_particle_mass_loop(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("for local_index in np.flatnonzero", source)
        self.assertIn('"vectorized_chunk_reductions": True', source)


if __name__ == "__main__":
    unittest.main()
