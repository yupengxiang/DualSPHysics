#!/usr/bin/env python3
"""Manufactured HDF5/CLI tests for the bounded scientific field audit."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import h5py  # type: ignore
import numpy as np  # type: ignore


HERE = Path(__file__).resolve().parent
WORKER = HERE / "ds_data02_stage2_scientific_field_h5_audit_v1.py"
VERIFIER = HERE / "ds_data02_stage2_verify_scientific_field_h5_audit_v1.py"
CURRENT_SHA256 = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
UNIT_PROTOCOL = {"position": "m", "velocity": "m/s", "density": "kg/m^3", "mass": "kg", "pressure": "Pa", "time": "s"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_h5(path: Path, units: dict[str, str] | None = None) -> None:
    frames, particles = 3, 4
    units = units or UNIT_PROTOCOL
    time_axis = np.asarray([0.0, 1.0, 2.0], dtype=np.float64)
    ids = np.asarray([10, 11, 12, 13], dtype=np.int64)
    zones = np.asarray([0, 0, 1, 1], dtype=np.int32)
    initial_type = np.asarray([3, 3, 1, 0], dtype=np.int8)
    initial_mass = np.asarray([1.0, 2.0, 3.0, 4.0], dtype=np.float64)
    position = np.arange(frames * particles * 3, dtype=np.float64).reshape(frames, particles, 3)
    velocity = np.ones((frames, particles, 3), dtype=np.float64)
    density = np.full((frames, particles), 1000.0, dtype=np.float64)
    mass = np.ones((frames, particles), dtype=np.float64)
    pressure = np.full((frames, particles), 10.0, dtype=np.float64)
    valid = np.asarray([[1, 1, 1, 1], [1, 1, 0, 1], [1, 0, 0, 1]], dtype=np.int8)
    frame_type = np.asarray([[3, 3, 1, 0], [3, 3, -1, 0], [3, -1, -1, 0]], dtype=np.int8)
    # One active position is non-finite; one inactive row has non-finite fields.
    position[1, 1, :] = np.nan
    velocity[1, 2, :] = np.nan
    density[1, 2] = np.nan
    with h5py.File(path, "w") as h5:
        h5.create_dataset("time", data=time_axis)
        h5.create_dataset("particle_id", data=ids)
        h5.create_dataset("particle_zone", data=zones)
        h5.create_dataset("initial_type", data=initial_type)
        h5.create_dataset("initial_mass", data=initial_mass)
        for name, values in {
            "position": position, "velocity": velocity, "density": density,
            "mass": mass, "pressure": pressure, "valid": valid, "type": frame_type,
        }.items():
            h5.create_dataset(name, data=values)
        h5.attrs["units_json"] = json.dumps(units, sort_keys=True)
        h5.attrs["coordinate_frame"] = "fixture Cartesian"
        h5.attrs["identity_key"] = "(Zone,Idp)"
        h5.attrs["schema"] = "fixture.raw-h5.v1"
        h5.attrs["mass_semantics"] = "per-particle fixture mass"


def write_manifest(directory: Path, h5_path: Path, expected_units: dict[str, str] | None = None) -> Path:
    manifest_path = directory / "manifest.json"
    h5_digest = sha256(h5_path)
    manifest = {
        "schema": "ds02.stage2.scientific-field-h5-audit-manifest.v1",
        "status": "READY_FOR_GUARDED_RAW_H5_FIELD_AUDIT",
        "current_catalog": {"path": "/fixture/CURRENT336.json", "sha256": CURRENT_SHA256, "cases": 336},
        "cases": [{
            "physical_case_id": "FIXTURE_CASE",
            "family_id": "F1",
            "trajectory_h5": {"path": str(h5_path), "known_sha256": h5_digest, "sha256": h5_digest, "deferred_after_reservation": True, "content_read_by_preparer": False},
            "expected_frames": 3,
            "expected_particles": 4,
            "expected_units": expected_units or UNIT_PROTOCOL,
        }],
        "static_source_refs": [],
        "read_policy": {"trajectory_h5_opened_by_preparer": False},
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path


def run_cli(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(script), *args], text=True, capture_output=True, check=False)


class ScientificFieldH5AuditTests(unittest.TestCase):
    def test_real_worker_and_independent_verifier_keep_active_and_inactive_separate(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage2-field-h5-") as raw:
            directory = Path(raw)
            h5_path = directory / "fixture.h5"
            write_h5(h5_path)
            manifest = write_manifest(directory, h5_path)
            report = directory / "report.json"
            result = run_cli(WORKER, "audit", "--manifest", str(manifest), "--output", str(report), "--chunk", "2")
            self.assertEqual(result.returncode, 0, result.stderr)
            document = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(document["counts"], {"requested": 1, "completed": 1, "failed": 0})
            case = document["case_results"][0]
            self.assertGreater(case["field_scan"]["active_nonfinite_total"], 0)
            self.assertGreater(case["field_scan"]["inactive_nonfinite_total"], 0)
            self.assertTrue(case["field_scan"]["inactive_nonfinite_separate"])
            self.assertEqual(case["units"]["comparison"], "DECLARED_MATCHES_PRODUCER_PROTOCOL")
            self.assertEqual(case["material_and_mk"]["semantic_authority"], "UNKNOWN")
            self.assertEqual(case["scientific_qualification"], {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"})
            verified = directory / "verified.json"
            result = run_cli(VERIFIER, "verify", "--manifest", str(manifest), "--report", str(report), "--output", str(verified))
            self.assertEqual(result.returncode, 0, result.stderr)
            verification = json.loads(verified.read_text(encoding="utf-8"))
            self.assertFalse(verification["production_eligible"])
            self.assertEqual(verification["scientific_credit"], 0)

    def test_unit_mismatch_is_reported_without_authority_or_scientific_credit(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage2-field-h5-units-") as raw:
            directory = Path(raw)
            h5_path = directory / "fixture.h5"
            wrong_units = dict(UNIT_PROTOCOL)
            wrong_units["mass"] = "g"
            write_h5(h5_path, wrong_units)
            manifest = write_manifest(directory, h5_path)
            report = directory / "report.json"
            result = run_cli(WORKER, "audit", "--manifest", str(manifest), "--output", str(report))
            self.assertEqual(result.returncode, 0, result.stderr)
            case = json.loads(report.read_text(encoding="utf-8"))["case_results"][0]
            self.assertEqual(case["units"]["comparison"], "DECLARED_DIFFERS_FROM_PRODUCER_PROTOCOL")
            self.assertEqual(case["units"]["authority"], "UNKNOWN_UNVERIFIED")

    def test_verifier_rejects_tampered_reconciliations(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage2-field-h5-tamper-") as raw:
            directory = Path(raw)
            h5_path = directory / "fixture.h5"
            write_h5(h5_path)
            manifest = write_manifest(directory, h5_path)
            report = directory / "report.json"
            self.assertEqual(run_cli(WORKER, "audit", "--manifest", str(manifest), "--output", str(report)).returncode, 0)
            tampered = json.loads(report.read_text(encoding="utf-8"))
            tampered["case_results"][0]["field_scan"]["active_nonfinite_total"] += 1
            tampered_report = directory / "tampered.json"
            tampered_report.write_text(json.dumps(tampered, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            result = run_cli(VERIFIER, "verify", "--manifest", str(manifest), "--report", str(tampered_report), "--output", str(directory / "bad-verification.json"))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("does not reconcile", result.stderr)

    def test_worker_rejects_missing_required_frame_field(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage2-field-h5-missing-") as raw:
            directory = Path(raw)
            h5_path = directory / "fixture.h5"
            write_h5(h5_path)
            with h5py.File(h5_path, "a") as h5:
                del h5["pressure"]
            manifest = write_manifest(directory, h5_path)
            report = directory / "report.json"
            result = run_cli(WORKER, "audit", "--manifest", str(manifest), "--output", str(report))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("FAILED_RAW_H5_FIELD_SCAN", report.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
