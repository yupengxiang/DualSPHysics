from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace

import h5py
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ds_data02_stage2_typed_lifecycle_sidecar_v4 as subject

CASE_ID = "F3_GENERIC_TYPED_LIFECYCLE_CASE"


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
            "family_id": "F3", "physical_case_id": CASE_ID, "frames": frames, "particles": particles,
            "trajectory": {"path": str(h5_path), "producer_declared_sha256": h5_sha, "bytes": h5_path.stat().st_size},
        }],
    }
    current_sha = write_json(current_path, current)
    scan_path = root / "scientific-scan.json"
    scan_sha = write_json(scan_path, {
        "schema": "ds02.stage2.scientific-scan.v1", "physical_case_id": CASE_ID,
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
            "family_id": "F3", "physical_case_id": CASE_ID, "trajectory": str(h5_path), "trajectory_verified_sha256": h5_sha,
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
    (root / "runtime-config.xml").write_text("<config fixture=\"true\"/>\n", encoding="utf-8")
    return SimpleNamespace(
        current=source["current"], audit_verification=source["audit"], scan=source["scan"], receipt=source["receipt"],
        case_id=CASE_ID, family_id="F3", expected_current_sha256=source["current_sha"], runtime_config=root / "runtime-config.xml", output_dir=output_dir, worker=worker, python=python,
        runtime_v2=paths["runtime-v2"], runtime_v6=paths["runtime-v6"], runtime_v8=paths["runtime-v8"],
        dispatch_v8=paths["dispatch-v8"], strict_v8=paths["strict-v8"], cwd=root, worktree_root=root,
    )


def rewrite_with_inactive_type_sentinels(source: dict[str, Path | str]) -> None:
    """Rewrite only the tiny fixture, then rebind its JSON source edges.

    The production pilot H5 is never touched by this test.  This fixture uses
    ``-1`` and NaN for known inactive rows, one active NaN type, and one
    invalid mask value so the CLI path exercises each V4 branch.
    """
    with h5py.File(source["h5"], "r+") as handle:
        valid = np.asarray(handle["valid"][:], dtype=np.int8)
        values = np.broadcast_to(np.asarray([3, 0, 3, 1], dtype=np.float32), valid.shape).copy()
        values[valid == 0] = -1.0
        values[1, 2] = np.nan  # same active identity, first unknown frame
        values[2, 2] = np.nan  # active mask with invalid type: unknown active diagnostic
        valid[1, 3] = 2  # invalid mask: state is unknown, not inactive
        del handle["type"]
        handle.create_dataset("type", data=values)
        del handle["valid"]
        handle.create_dataset("valid", data=valid)
    h5_sha = sha(Path(source["h5"]))
    current = json.loads(Path(source["current"]).read_text())
    current["cases"][0]["trajectory"]["producer_declared_sha256"] = h5_sha
    current["cases"][0]["trajectory"]["bytes"] = Path(source["h5"]).stat().st_size
    current_sha = write_json(Path(source["current"]), current)
    scan = json.loads(Path(source["scan"]).read_text())
    scan["source_bytes"] = Path(source["h5"]).stat().st_size
    scan_sha = write_json(Path(source["scan"]), scan)
    audit = json.loads(Path(source["audit"]).read_text())
    audit["current_catalog"]["sha256"] = current_sha
    audit["verified_cases"][0]["trajectory_verified_sha256"] = h5_sha
    audit["verified_cases"][0]["scan_sha256"] = scan_sha
    audit_sha = write_json(Path(source["audit"]), audit)
    source["current_sha"] = current_sha
    source["h5_sha"] = h5_sha
    source["audit_sha"] = audit_sha


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
            result = subject.prepare(prepare_args(root, source, output))
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
            self.assertIn(str(Path(result["manifest"]).resolve()), request["input_files"])
            self.assertEqual(request["manifest_contract"]["sha256"], sha(Path(result["manifest"])))
            self.assertEqual(request["interpreter_binding"]["literal_path"], str(root / "python"))
            self.assertEqual(request["runtime_binding"]["runtime_config"]["literal_path"], str(root / "runtime-config.xml"))
            self.assertEqual(manifest["audit_lifecycle_exposure"]["status"], "NOT_EXPOSED_IN_THIS_AUDIT_ROW")

    def test_units_identity_and_real_time_contracts_have_no_defaults_or_complex_ordering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = write_fixture(root)
            with h5py.File(source["h5"], "r+") as handle:
                del handle.attrs["units_json"]
            metadata, _ = subject._lifecycle_records(Path(source["h5"]), expected_frames=4, chunk=2)
            self.assertEqual(metadata["metadata"]["units_status"], "NOT_DECLARED")
            self.assertEqual(metadata["metadata"]["units"], {})
            self.assertEqual(metadata["metadata"]["identity_key_status"], "EXPLICIT_MATCH")
            with h5py.File(source["h5"], "r+") as handle:
                del handle.attrs["identity_key"]
                del handle.attrs["coordinate_frame"]
            metadata, _ = subject._lifecycle_records(Path(source["h5"]), expected_frames=4, chunk=2)
            self.assertEqual(metadata["metadata"]["identity_key_status"], "NOT_DECLARED")
            self.assertEqual(metadata["metadata"]["coordinate_frame_status"], "NOT_DECLARED")
            with h5py.File(source["h5"], "r+") as handle:
                handle.attrs["units_json"] = json.dumps({**subject.FIELD_UNITS_DEFAULT, "mass": "g"})
            with self.assertRaises(subject.LifecycleError):
                subject._lifecycle_records(Path(source["h5"]), expected_frames=4, chunk=2)

    def test_real_subprocess_audit_cli_enters_worker_and_writes_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = write_fixture(root)
            prepared = subject.prepare(prepare_args(root, source, root / "prepared"))
            summary = root / "cli-summary.json"
            records = root / "cli-records.jsonl"
            completed = subprocess.run(
                [
                    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python",
                    str(subject.SCRIPT), "audit",
                    "--manifest", str(prepared["manifest"]),
                    "--summary", str(summary), "--records", str(records), "--chunk", "2",
                ],
                cwd=root, capture_output=True, text=True, check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
            result = json.loads(completed.stdout)
            self.assertEqual(result["status"], "COMPLETED_TYPED_LIFECYCLE_NO_PHYSICAL_CREDIT")
            self.assertTrue(summary.is_file())
            self.assertTrue(records.is_file())
            with h5py.File(source["h5"], "r+") as handle:
                handle.attrs["units_json"] = json.dumps(subject.FIELD_UNITS_DEFAULT)
                del handle["time"]
                handle.create_dataset("time", data=np.array([0 + 0j, 0.1 + 0j, 0.2 + 0j, 0.3 + 0j], dtype=np.complex128))
            with self.assertRaises(subject.LifecycleError):
                subject._lifecycle_records(Path(source["h5"]), expected_frames=4, chunk=2)

    def test_stream_emits_lifecycle_and_unknown_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = write_fixture(root)
            output = root / "prepared"
            prepared = subject.prepare(prepare_args(root, source, output))
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

    def test_real_cli_preserves_inactive_type_sentinels_and_counts_active_unknown_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = write_fixture(root)
            rewrite_with_inactive_type_sentinels(source)
            prepared = subject.prepare(prepare_args(root, source, root / "prepared"))
            summary = root / "sentinel-summary.json"
            records = root / "sentinel-records.jsonl"
            completed = subprocess.run(
                [
                    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python",
                    str(subject.SCRIPT), "audit", "--manifest", str(prepared["manifest"]),
                    "--summary", str(summary), "--records", str(records), "--chunk", "2",
                ],
                cwd=root, capture_output=True, text=True, check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
            rows = {json.loads(line)["idp"]: json.loads(line) for line in records.read_text().splitlines()[1:]}
            # Idp 10 is active, inactive(-1/NaN), then active again.  The
            # sentinel does not erase its saved-frame disappearance/reentry.
            self.assertEqual(rows[10]["first_disappeared_frame"], 2)
            self.assertEqual(rows[10]["reappearance_count"], 1)
            self.assertEqual(rows[10]["unknown"]["active_type_unknown_frame_count"], 0)
            self.assertGreater(rows[10]["unknown"]["inactive_type_sentinel_frame_count"], 0)
            self.assertFalse(rows[10]["missing_at_final"])
            # Idp 12 has one active frame with NaN type and remains an
            # explicitly unknown active observation.
            self.assertEqual(rows[12]["unknown"]["active_type_unknown_frame_count"], 2)
            self.assertGreater(rows[12]["unknown"]["active_nonfinite_field_counts"]["position"], 0)
            # Idp 13 is inactive throughout; its inactive sentinel is not an
            # unknown active identity.  The deliberately invalid mask is a
            # separate unknown-state count.
            self.assertEqual(rows[13]["unknown"]["active_type_unknown_frame_count"], 0)
            self.assertEqual(rows[13]["first_active_frame"], None)
            self.assertGreater(rows[13]["unknown"]["valid_mask_unknown_frame_count"], 0)
            report = json.loads(summary.read_text())
            self.assertEqual(report["role_ledgers"]["fluid"]["unknown_active_id_count"], 1)
            self.assertTrue(report["lifecycle_semantics"]["inactive_mask_state"].startswith("valid == 0"))
            self.assertTrue(report["lifecycle_semantics"]["inactive_type_sentinel"].startswith("inactive type"))

    def test_worker_rejects_wrong_known_h5_sha(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = write_fixture(root)
            output = root / "prepared"
            prepared = subject.prepare(prepare_args(root, source, output))
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
            with self.assertRaises(subject.LifecycleError):
                subject.prepare(prepare_args(root, source, output))


if __name__ == "__main__":
    unittest.main()
