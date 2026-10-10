#!/usr/bin/env python3
"""Manufactured H5 tests for the additive V2 scientific field audit."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import h5py  # type: ignore
import numpy as np  # type: ignore


HERE = Path(__file__).resolve().parent
WORKER = HERE / "ds_data02_stage2_scientific_field_h5_audit_v2.py"
VERIFIER = HERE / "ds_data02_stage2_verify_scientific_field_h5_audit_v2.py"
CURRENT = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/stage2/CURRENT336.json")
CURRENT_SHA = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
UNITS = {"position": "m", "velocity": "m/s", "density": "kg/m^3", "mass": "kg", "pressure": "Pa", "time": "s"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stat(path: Path) -> dict[str, object]:
    value = path.stat()
    return {"path": str(path.resolve()), "bytes": int(value.st_size), "mtime_ns": int(value.st_mtime_ns), "ctime_ns": int(value.st_ctime_ns), "st_dev": int(value.st_dev), "st_ino": int(value.st_ino)}


def write_h5(path: Path, *, missing_mass: bool = False, missing_frame: str | None = None, invalid_initial_type: bool = False, invalid_ranges: bool = False, type_transition: bool = False, units: dict[str, str] | None = None) -> None:
    frames, particles = 3, 4
    units = units or UNITS
    ids = np.asarray([10, 11, 12, 13], dtype=np.int64)
    zones = np.asarray([0, 0, 1, 1], dtype=np.int32)
    initial_type = np.asarray([3, 3, 1, 0], dtype=np.int8)
    if invalid_initial_type:
        initial_type[1] = 99
    initial_mass = np.asarray([1.0, 2.0, 3.0, 4.0], dtype=np.float64)
    position = np.arange(frames * particles * 3, dtype=np.float64).reshape(frames, particles, 3)
    velocity = np.ones((frames, particles, 3), dtype=np.float64)
    density = np.full((frames, particles), 1000.0, dtype=np.float64)
    mass = np.ones((frames, particles), dtype=np.float64)
    pressure = np.full((frames, particles), 10.0, dtype=np.float64)
    valid = np.asarray([[1, 1, 1, 1], [1, 1, 0, 1], [1, 0, 0, 1]], dtype=np.int8)
    frame_type = np.asarray([[3, 3, 1, 0], [3, 3, -1, 0], [3, -1, -1, 0]], dtype=np.int8)
    position[1, 1, :] = np.nan
    velocity[1, 2, :] = np.nan
    density[1, 2] = np.nan
    if invalid_ranges:
        density[0, 0] = 0.0
        mass[0, 1] = -2.0
        pressure[0, 2] = -4.0
    if type_transition:
        frame_type[1, 0] = 1
    with h5py.File(path, "w") as h5:
        h5.create_dataset("time", data=np.asarray([0.0, 1.0, 2.0], dtype=np.float64))
        h5.create_dataset("particle_id", data=ids)
        h5.create_dataset("particle_zone", data=zones)
        h5.create_dataset("initial_type", data=initial_type)
        if not missing_mass:
            h5.create_dataset("initial_mass", data=initial_mass)
        data = {"position": position, "velocity": velocity, "density": density, "mass": mass, "pressure": pressure, "valid": valid, "type": frame_type}
        for name, values in data.items():
            if name != missing_frame:
                h5.create_dataset(name, data=values)
        h5.attrs["units_json"] = json.dumps(units, sort_keys=True)
        h5.attrs["coordinate_frame"] = "fixture Cartesian"
        h5.attrs["identity_key"] = "(Zone,Idp)"
        h5.attrs["schema"] = "fixture.raw-h5.v2"
        h5.attrs["mass_semantics"] = "fixture per-particle mass"


def write_manifest(directory: Path, h5_path: Path, *, expected_units: dict[str, str] | None = None) -> Path:
    case_id = "FIXTURE_CASE"
    static_refs = []
    case_refs = {}
    for field in ("producer_terminal_proof", "case_manifest", "producer_receipt", "typed_summary"):
        path = directory / f"{field}.json"
        path.write_text(json.dumps({"case": case_id, "field": field}, sort_keys=True) + "\n", encoding="utf-8")
        reference = {**stat(path), "role": field, "sha256": sha256(path), "content_read_by_preparer": True}
        case_refs[field] = reference
        static_refs.append(reference)
    current_ref = {**stat(CURRENT), "role": "current336", "sha256": CURRENT_SHA, "content_read_by_preparer": True}
    static_refs.insert(0, current_ref)
    h5_ref = {**stat(h5_path), "role": "trajectory_h5", "sha256": sha256(h5_path), "known_sha256": sha256(h5_path), "deferred_after_reservation": True, "content_read_by_preparer": False}
    manifest = {
        "schema": "ds02.stage2.scientific-field-h5-audit-manifest.v2",
        "status": "READY_FOR_GUARDED_RAW_H5_FIELD_AUDIT",
        "current_catalog": {"path": str(CURRENT), "sha256": CURRENT_SHA, "cases": 336},
        "static_source_refs": static_refs,
        "cases": [{"physical_case_id": case_id, "family_id": "F1", **case_refs, "trajectory_h5": h5_ref, "expected_frames": 3, "expected_particles": 4, "expected_units": expected_units or UNITS}],
        "worker_contract": {"missing_field_policy": "per-field NOT_EXPOSED/UNKNOWN", "physical_range_policy": "diagnostic only"},
    }
    path = directory / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def run(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(script), *args], text=True, capture_output=True, check=False)


class ScientificFieldH5AuditV2Tests(unittest.TestCase):
    def audit_fixture(self, directory: Path, **kwargs: object) -> tuple[Path, Path, dict]:
        h5_path = directory / "fixture.h5"
        write_h5(h5_path, **kwargs)
        manifest = write_manifest(directory, h5_path)
        report = directory / "report.json"
        result = run(WORKER, "audit", "--manifest", str(manifest), "--output", str(report), "--chunk", "2")
        self.assertEqual(result.returncode, 0, result.stderr)
        return manifest, report, json.loads(report.read_text(encoding="utf-8"))

    def verify_fixture(self, directory: Path, manifest: Path, report: Path) -> None:
        output = directory / "verified.json"
        result = run(VERIFIER, "verify", "--manifest", str(manifest), "--report", str(report), "--output", str(output))
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(output.read_text(encoding="utf-8"))
        self.assertFalse(value["production_eligible"])
        self.assertEqual(value["scientific_credit"], 0)

    def test_missing_initial_mass_and_frame_field_are_explicit_unknown_and_still_scanned(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage2-field-v2-missing-") as raw:
            directory = Path(raw)
            manifest, report, document = self.audit_fixture(directory, missing_mass=True, missing_frame="pressure")
            case = document["case_results"][0]
            self.assertEqual(case["initial_mass"]["status"], "NOT_EXPOSED")
            self.assertIsNone(case["initial_mass"]["total_kg"])
            self.assertEqual(case["field_scan"]["field_status"]["pressure"], "NOT_EXPOSED")
            self.assertTrue(case["field_scan"]["frames_full_scan"])
            self.assertEqual(case["field_scan"]["active_finite_status"], "REQUIRED_FIELD_NOT_EXPOSED")
            self.verify_fixture(directory, manifest, report)

    def test_invalid_initial_type_and_transition_are_reported_without_all_finite_claim(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage2-field-v2-type-") as raw:
            directory = Path(raw)
            manifest, report, document = self.audit_fixture(directory, invalid_initial_type=True, type_transition=True)
            case = document["case_results"][0]
            self.assertEqual(case["initial_type"]["status"], "PRESENT_UNKNOWN_CODES")
            self.assertEqual(case["initial_type"]["invalid_code_count"], 1)
            self.assertIn("fluid->moving", case["field_scan"]["frame_type_transitions"])
            self.assertNotEqual(case["field_scan"]["active_finite_status"], "ALL_ACTIVE_REQUIRED_FIELDS_FINITE")
            self.verify_fixture(directory, manifest, report)

    def test_physical_ranges_are_diagnostics_and_pressure_negative_is_not_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage2-field-v2-range-") as raw:
            directory = Path(raw)
            manifest, report, document = self.audit_fixture(directory, invalid_ranges=True)
            case = document["case_results"][0]
            ranges = case["physical_ranges"]
            self.assertEqual(ranges["status"], "DIAGNOSTIC_ONLY_NO_GATE")
            self.assertGreater(ranges["density_mass_active_nonpositive"]["density"], 0)
            self.assertGreater(ranges["density_mass_active_nonpositive"]["mass"], 0)
            self.assertGreater(ranges["pressure_active_negative"], 0)
            self.verify_fixture(directory, manifest, report)

    def test_same_content_stat_change_fails_deferred_manifest_binding(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage2-field-v2-stat-") as raw:
            directory = Path(raw)
            h5_path = directory / "fixture.h5"
            write_h5(h5_path)
            manifest = write_manifest(directory, h5_path)
            original = h5_path.stat()
            os.utime(h5_path, ns=(original.st_atime_ns, original.st_mtime_ns + 1_000_000))
            report = directory / "report.json"
            result = run(WORKER, "audit", "--manifest", str(manifest), "--output", str(report))
            self.assertNotEqual(result.returncode, 0)
            document = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(document["counts"]["failed"], 1)
            self.assertIn("deferred manifest", document["failed_cases"][0]["error"])

    def test_tampered_source_binding_is_rejected_without_h5_hashing(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage2-field-v2-tamper-") as raw:
            directory = Path(raw)
            manifest, report, document = self.audit_fixture(directory)
            tampered = json.loads(report.read_text(encoding="utf-8"))
            tampered["case_results"][0]["source_binding"]["trajectory_h5"]["pre_stat"]["mtime_ns"] += 1
            tampered_path = directory / "tampered.json"
            tampered_path.write_text(json.dumps(tampered, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            result = run(VERIFIER, "verify", "--manifest", str(manifest), "--report", str(tampered_path), "--output", str(directory / "bad.json"))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("differs", result.stderr)


if __name__ == "__main__":
    unittest.main()
