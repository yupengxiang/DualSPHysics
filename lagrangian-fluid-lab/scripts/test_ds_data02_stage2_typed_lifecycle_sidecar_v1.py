from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace

import h5py
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ds_data02_stage2_typed_lifecycle_sidecar_v1 as subject


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> str:
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return sha(path)


def write_fixture(root: Path) -> dict[str, Path | str]:
    h5_path = root / "pilot-trajectory.h5"
    frames, particles = 4, 4
    valid = np.array([[1, 0, 1, 0], [1, 1, 1, 0], [0, 0, 1, 0], [1, 0, 1, 0]], dtype=np.bool_)
    nan = np.nan
    position = np.zeros((frames, particles, 3), dtype=np.float32)
    velocity = np.zeros((frames, particles, 3), dtype=np.float32)
    density = np.full((frames, particles), 1000.0, dtype=np.float32)
    mass = np.full((frames, particles), 0.001, dtype=np.float32)
    pressure = np.zeros((frames, particles), dtype=np.float32)
    # Inactive values may be NaN and must not become active-field failures.
    for field in (position, velocity):
        field[~valid] = nan
    for field in (density, mass, pressure):
        field[~valid] = nan
    # An active non-finite position is an UNKNOWN field observation.
    position[2, 2, 0] = nan
    with h5py.File(h5_path, "w") as h:
        h.create_dataset("time", data=np.array([0.0, 0.1, 0.2, 0.3], dtype=np.float64))
        h.create_dataset("particle_id", data=np.array([10, 11, 12, 13], dtype=np.uint32))
        h.create_dataset("particle_zone", data=np.array([1, 1, 1, 1], dtype=np.int16))
        h.create_dataset("initial_type", data=np.array([3, 0, 3, 1], dtype=np.int8))
        h.create_dataset("initial_mass", data=np.array([0.001, 0.002, 0.003, 0.004], dtype=np.float32))
        h.create_dataset("position", data=position)
        h.create_dataset("velocity", data=velocity)
        h.create_dataset("density", data=density)
        h.create_dataset("mass", data=mass)
        h.create_dataset("pressure", data=pressure)
        h.create_dataset("valid", data=valid)
        h.create_dataset("type", data=np.broadcast_to(np.array([3, 0, 3, 1], dtype=np.int8), (frames, particles)))
        h.attrs["units_json"] = json.dumps(subject.FIELD_UNITS_DEFAULT)
        h.attrs["coordinate_frame"] = "fixture Cartesian"
        h.attrs["identity_key"] = "(Zone, Idp)"
    h5_sha = sha(h5_path)
    current_path = root / "CURRENT336.json"
    current = {
        "schema": "ds02.stage2.current336.v1",
        "cases": [{
            "family_id": "F2", "physical_case_id": subject.PILOT_CASE_ID, "frames": frames, "particles": particles,
            "trajectory": {"path": str(h5_path), "producer_declared_sha256": h5_sha, "bytes": h5_path.stat().st_size},
        }],
    }
    current_sha = write_json(current_path, current)
    scan_path = root / "scientific-scan.json"
    scan_sha = write_json(scan_path, {
        "schema": "ds02.stage2.scientific-scan.v1", "physical_case_id": subject.PILOT_CASE_ID,
        "trajectory": str(h5_path), "source_bytes": h5_path.stat().st_size, "frames": frames, "scan_status": "SCANNED",
    })
    receipt_path = root / "execution-receipt.json"
    # The producer receipt's case_id names the scan batch, not this physical
    # CURRENT row.  A physical_case_id is optional and is tested separately.
    receipt_sha = write_json(receipt_path, {
        "status": "completed", "returncode": 0,
        "request": {"case_id": "STAGE2_CURRENT336_SCIENCE"},
    })
    audit_path = root / "SCIENTIFIC_AUDIT_VERIFICATION_023.json"
    write_json(audit_path, {
        "schema": "ds02.stage2.scientific-audit-independent-verification.v23",
        "current_catalog": {"path": str(current_path), "sha256": current_sha},
        "verified_cases": [{
            "family_id": "F2", "physical_case_id": subject.PILOT_CASE_ID, "trajectory": str(h5_path), "trajectory_verified_sha256": h5_sha,
            "scan": str(scan_path), "scan_sha256": scan_sha, "receipt": str(receipt_path), "receipt_sha256": receipt_sha,
            "scan_status": "SCANNED", "frames": frames, "field_failures": [], "exact_CURRENT_path_and_declared_sha_match": True,
        }],
    })
    return {"h5": h5_path, "current": current_path, "audit": audit_path, "scan": scan_path, "receipt": receipt_path, "current_sha": current_sha, "h5_sha": h5_sha}


def prepare_args(root: Path, source: dict[str, Path | str], output_dir: Path) -> SimpleNamespace:
    worker = Path(subject.SCRIPT)
    python = root / "python"
    python.write_text("fixture interpreter\n", encoding="utf-8")
    paths = {}
    for name in ("runtime-v2", "runtime-v6", "runtime-v8", "dispatch-v8", "strict-v8"):
        path = root / f"{name}.py"
        path.write_text(f"{name}\n", encoding="utf-8")
        paths[name] = path
    return SimpleNamespace(
        current=source["current"], audit_verification=source["audit"], scan=source["scan"], receipt=source["receipt"],
        case_id=subject.PILOT_CASE_ID, output_dir=output_dir, worker=worker, python=python,
        runtime_v2=paths["runtime-v2"], runtime_v6=paths["runtime-v6"], runtime_v8=paths["runtime-v8"],
        dispatch_v8=paths["dispatch-v8"], strict_v8=paths["strict-v8"], cwd=root, worktree_root=root,
    )


class TypedLifecycleTests(unittest.TestCase):
    def test_self_test_and_identity_negative(self) -> None:
        self.assertEqual(subject.self_test()["status"], "PASS")
        with self.assertRaises(subject.LifecycleError):
            subject._identity_keys(np, np.array([1, 1], dtype=np.int16), np.array([7, 7], dtype=np.uint32))

    def test_prepare_is_h5_stat_only_and_exact_case_bound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = write_fixture(root)
            output = root / "prepared"
            old_current_sha = subject.EXPECTED_CURRENT_SHA256
            subject.EXPECTED_CURRENT_SHA256 = str(source["current_sha"])
            try:
                result = subject.prepare(prepare_args(root, source, output))
            finally:
                subject.EXPECTED_CURRENT_SHA256 = old_current_sha
            manifest = json.loads(Path(result["manifest"]).read_text())
            trajectory = next(ref for ref in manifest["source_refs"] if ref["role"] == "trajectory_h5")
            self.assertTrue(trajectory["content_read_by_preparer"] is False)
            self.assertTrue(trajectory["read_after_reservation"] is True)
            self.assertEqual(trajectory["sha256"], source["h5_sha"])
            self.assertEqual(result["h5_content_opened_by_preparer"], False)
            request = json.loads(Path(result["request"]).read_text())
            self.assertIn(str(source["h5"]), request["deferred_input_files"])
            self.assertNotIn(str(source["h5"]), request["input_files"])
            self.assertEqual(request["estimated_deferred_read_passes"], 3)

    def test_stream_emits_lifecycle_and_unknown_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = write_fixture(root)
            output = root / "prepared"
            old_current_sha = subject.EXPECTED_CURRENT_SHA256
            subject.EXPECTED_CURRENT_SHA256 = str(source["current_sha"])
            try:
                prepared = subject.prepare(prepare_args(root, source, output))
            finally:
                subject.EXPECTED_CURRENT_SHA256 = old_current_sha
            summary = output / "summary.json"
            records = output / "records.jsonl"
            result = subject.audit(Path(prepared["manifest"]), summary, records, chunk=2)
            self.assertTrue(result["h5_pre_post_sha256_equal"])
            lines = records.read_text().splitlines()
            self.assertEqual(len(lines), 5)
            rows = {json.loads(line)["idp"]: json.loads(line) for line in lines[1:]}
            ten = rows[10]
            self.assertEqual(ten["first_disappeared_frame"], 2)
            self.assertEqual(ten["reappearance_count"], 1)
            self.assertEqual(ten["first_reappearance_frame"], 3)
            self.assertFalse(ten["missing_at_final"])
            eleven = rows[11]
            self.assertTrue(eleven["new_id"])
            self.assertEqual(eleven["first_active_frame"], 1)
            self.assertEqual(eleven["first_disappeared_frame"], 2)
            self.assertTrue(eleven["missing_at_final"])
            twelve = rows[12]
            self.assertGreater(twelve["unknown"]["active_nonfinite_field_counts"]["position"], 0)
            thirteen = rows[13]
            self.assertEqual(thirteen["censoring"], "NO_ACTIVE_OBSERVATION")
            self.assertEqual(sum(row["unknown"]["active_nonfinite_field_counts"]["position"] for row in rows.values() if row["idp"] == 13), 0)
            report = json.loads(summary.read_text())
            self.assertEqual(report["scientific_qualification"]["QI"], "UNKNOWN")
            self.assertEqual(report["lifecycle_semantics"]["physical_fate"], "UNKNOWN")
            self.assertEqual(report["read_policy"]["h5_opened_by_worker_after_reservation"], True)
            self.assertEqual(report["role_ledgers"]["fluid"]["activity_mask_field"], "valid")
            self.assertEqual(report["role_ledgers"]["fluid"]["units"]["position"], "m")

    def test_worker_rejects_wrong_known_h5_sha(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = write_fixture(root)
            output = root / "prepared"
            old_current_sha = subject.EXPECTED_CURRENT_SHA256
            subject.EXPECTED_CURRENT_SHA256 = str(source["current_sha"])
            try:
                prepared = subject.prepare(prepare_args(root, source, output))
            finally:
                subject.EXPECTED_CURRENT_SHA256 = old_current_sha
            manifest_path = Path(prepared["manifest"])
            manifest = json.loads(manifest_path.read_text())
            for ref in manifest["source_refs"]:
                if ref["role"] == "trajectory_h5":
                    ref["sha256"] = "0" * 64
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(subject.LifecycleError):
                subject.audit(manifest_path, output / "bad-summary.json", output / "bad-records.jsonl", chunk=2)

    def test_receipt_batch_case_is_allowed_but_explicit_physical_case_mismatch_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = write_fixture(root)
            receipt = json.loads(Path(source["receipt"]).read_text())
            receipt["request"]["physical_case_id"] = "F2_DIFFERENT_CURRENT_CASE"
            receipt_sha = write_json(Path(source["receipt"]), receipt)
            audit = json.loads(Path(source["audit"]).read_text())
            audit["verified_cases"][0]["receipt_sha256"] = receipt_sha
            write_json(Path(source["audit"]), audit)
            output = root / "prepared"
            old_current_sha = subject.EXPECTED_CURRENT_SHA256
            subject.EXPECTED_CURRENT_SHA256 = str(source["current_sha"])
            try:
                with self.assertRaises(subject.LifecycleError):
                    subject.prepare(prepare_args(root, source, output))
            finally:
                subject.EXPECTED_CURRENT_SHA256 = old_current_sha


if __name__ == "__main__":
    unittest.main()
