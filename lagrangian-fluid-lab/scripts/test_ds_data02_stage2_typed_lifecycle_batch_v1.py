from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
import tempfile
import unittest

import h5py
import numpy as np

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ds_data02_stage2_typed_lifecycle_batch_request_v1 as request_builder
import ds_data02_stage2_typed_lifecycle_batch_worker_v1 as worker


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> str:
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return sha(path)


def write_h5(path: Path) -> None:
    valid = np.array([[1, 0], [0, 0]], dtype=np.int8)
    position = np.zeros((2, 2, 3), dtype=np.float32)
    velocity = np.zeros((2, 2, 3), dtype=np.float32)
    density = np.full((2, 2), 1000.0, dtype=np.float32)
    mass = np.full((2, 2), 0.001, dtype=np.float32)
    pressure = np.zeros((2, 2), dtype=np.float32)
    for field in (position, velocity, density, mass, pressure):
        field[valid == 0] = np.nan
    with h5py.File(path, "w") as h:
        h.create_dataset("time", data=np.array([0.0, 0.1], dtype=np.float64))
        h.create_dataset("particle_id", data=np.array([10, 11], dtype=np.uint32))
        h.create_dataset("particle_zone", data=np.array([1, 1], dtype=np.int16))
        h.create_dataset("initial_type", data=np.array([3, 0], dtype=np.int8))
        h.create_dataset("initial_mass", data=np.array([0.001, 0.002], dtype=np.float32))
        h.create_dataset("position", data=position)
        h.create_dataset("velocity", data=velocity)
        h.create_dataset("density", data=density)
        h.create_dataset("mass", data=mass)
        h.create_dataset("pressure", data=pressure)
        h.create_dataset("valid", data=valid)
        h.create_dataset("type", data=np.array([[3, -1], [3, -1]], dtype=np.int8))
        h.attrs["units_json"] = json.dumps(request_builder.lifecycle.FIELD_UNITS_DEFAULT)
        h.attrs["coordinate_frame"] = "fixture Cartesian"
        h.attrs["identity_key"] = "(Zone, Idp)"


def make_source(root: Path) -> tuple[Path, Path, str, str, list[Path]]:
    rows: list[dict[str, object]] = []
    audits: list[dict[str, object]] = []
    selected_ids = ["F2_BATCH_CASE_000", "F2_BATCH_CASE_001"]
    alias = request_builder.ALIAS_CASE
    all_ids = selected_ids + [alias] + [f"F3_BATCH_CASE_{index:03d}" for index in range(333)]
    scan_dir = root / "scans"
    scan_dir.mkdir()
    h5_paths: list[Path] = []
    for index, case_id in enumerate(all_ids):
        family = "F2" if case_id.startswith("F2_") else "F3"
        case_dir = root / "trajectories" / family
        case_dir.mkdir(parents=True, exist_ok=True)
        path = case_dir / f"{case_id}.h5"
        if case_id in selected_ids:
            write_h5(path)
            h5_paths.append(path)
            frames, particles = 2, 2
        else:
            path.write_bytes(b"stat-only placeholder\n")
            frames, particles = 2, 2
        trajectory_sha = sha(path)
        scan = scan_dir / f"{index:03d}-scan.json"
        receipt = scan_dir / f"{index:03d}-receipt.json"
        scan_sha = write_json(scan, {"schema": "ds02.stage2.scientific-scan.v1", "physical_case_id": case_id, "trajectory": str(path.resolve()), "source_bytes": path.stat().st_size, "frames": frames, "scan_status": "SCANNED"})
        receipt_sha = write_json(receipt, {"status": "completed", "returncode": 0, "request": {"case_id": "STAGE2_BATCH_TEST"}})
        rows.append({"family_id": family, "physical_case_id": case_id, "runtime_case_alias": case_id, "frames": frames, "particles": particles, "trajectory": {"path": str(path.resolve()), "producer_declared_sha256": trajectory_sha, "bytes": path.stat().st_size}})
        audits.append({"family_id": family, "physical_case_id": case_id, "trajectory": str(path.resolve()), "trajectory_verified_sha256": trajectory_sha, "scan": str(scan.resolve()), "scan_sha256": scan_sha, "receipt": str(receipt.resolve()), "receipt_sha256": receipt_sha, "scan_status": "SCANNED", "field_failures": [], "exact_CURRENT_path_and_declared_sha_match": True})
    current = root / "CURRENT336.json"
    current_sha = write_json(current, {"schema": request_builder.CURRENT_SCHEMA, "cases": rows})
    audit = root / "SCIENTIFIC_AUDIT_VERIFICATION_023.json"
    audit_sha = write_json(audit, {"schema": request_builder.AUDIT_SCHEMA, "current_catalog": {"path": str(current.resolve()), "sha256": current_sha}, "verified_cases": audits})
    return current, audit, current_sha, audit_sha, h5_paths


def args_for(root: Path, source: tuple[Path, Path, str, str, list[Path]], output: Path) -> SimpleNamespace:
    current, audit, current_sha, audit_sha, _h5 = source
    files: dict[str, Path] = {}
    for name in ("runtime-v2", "runtime-v6", "runtime-v8", "dispatch-v8", "strict-v8"):
        path = root / f"{name}.py"
        path.write_text(name, encoding="utf-8")
        files[name] = path
    config = root / "DsphConfig.xml"
    config.write_text("<config fixture='true'/>\n", encoding="utf-8")
    return SimpleNamespace(
        current=current, audit_verification=audit, expected_current_sha256=current_sha,
        expected_audit_sha256=audit_sha, family="F2", case_id=["F2_BATCH_CASE_000", "F2_BATCH_CASE_001"], exclude_case=[], max_cases=8, max_group_bytes=20 * 1024 * 1024 * 1024,
        output_dir=output, v4_worker=Path(request_builder.lifecycle.SCRIPT), batch_worker=Path(worker.SCRIPT),
        python=Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python"), runtime_config=config,
        runtime_v2=files["runtime-v2"], runtime_v6=files["runtime-v6"], runtime_v8=files["runtime-v8"],
        dispatch_v8=files["dispatch-v8"], strict_v8=files["strict-v8"], cwd=root, worktree_root=root,
    )


def prepare_cli(args: SimpleNamespace, *, output: Path, current_sha: str | None = None, case_ids: list[str] | None = None) -> list[str]:
    command = [
        "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python",
        str(request_builder.SCRIPT), "prepare",
        "--current", str(args.current), "--audit-verification", str(args.audit_verification),
        "--expected-current-sha256", current_sha or str(args.expected_current_sha256),
        "--expected-audit-sha256", str(args.expected_audit_sha256), "--family", str(args.family),
        "--max-cases", str(args.max_cases), "--max-group-bytes", str(args.max_group_bytes),
        "--output-dir", str(output), "--v4-worker", str(args.v4_worker), "--batch-worker", str(args.batch_worker),
        "--python", str(args.python), "--runtime-config", str(args.runtime_config),
    ]
    for flag, value in (("--runtime-v2", args.runtime_v2), ("--runtime-v6", args.runtime_v6), ("--runtime-v8", args.runtime_v8), ("--dispatch-v8", args.dispatch_v8), ("--strict-v8", args.strict_v8), ("--cwd", args.cwd), ("--worktree-root", args.worktree_root)):
        command.extend([flag, str(value)])
    for case_id in args.exclude_case or []:
        command.extend(["--exclude-case", str(case_id)])
    for case_id in case_ids if case_ids is not None else args.case_id or []:
        command.extend(["--case-id", str(case_id)])
    return command


class BatchTests(unittest.TestCase):
    def test_self_tests(self) -> None:
        self.assertEqual(request_builder.self_test()["status"], "PASS")
        self.assertEqual(worker.self_test()["status"], "PASS")

    def test_prepare_is_exact_source_closed_and_defers_h5(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = make_source(root)
            result = request_builder.prepare(args_for(root, source, root / "prepared"))
            self.assertEqual(result["case_count"], 2)
            self.assertEqual(result["exact_join_count"], 335)
            self.assertEqual(result["historical_alias_count"], 1)
            self.assertFalse(result["trajectory_content_opened"])
            self.assertFalse(result["trajectory_content_hashed"])
            manifest = json.loads(Path(result["manifest"]).read_text())
            self.assertEqual(manifest["source_read_policy"]["trajectory_content_opened_at_prepare"], False)
            self.assertEqual(len(manifest["deferred_trajectory_h5"]), 2)
            input_paths = {ref["path"] for ref in manifest["input_refs"]}
            self.assertTrue(all(str(path.resolve()) not in input_paths for path in source[4]))
            request = json.loads(Path(result["request"]).read_text())
            self.assertEqual(request["cpu_threads"], 1)
            self.assertEqual(request["max_wall_seconds"], 3600)
            self.assertEqual(request["estimated_deferred_read_passes"], 3)
            self.assertEqual(len(request["deferred_input_files"]), 2)
            self.assertEqual(request["launch_owner"], "root")

    def test_real_cli_runs_sequentially_and_preserves_later_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = make_source(root)
            result = request_builder.prepare(args_for(root, source, root / "prepared"))
            # Mutate only the second synthetic H5 after prepare.  The first
            # case must complete; V4 must reject the changed second source and
            # the batch must retain a failure receipt without a partial case
            # summary/records claim.
            with source[4][1].open("ab") as changed:
                changed.write(b"changed-after-prepare")
            output_root = root / "run-output"
            completed = subprocess.run(
                [
                    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python",
                    str(worker.SCRIPT), "run", "--manifest", result["manifest"], "--output-root", str(output_root), "--chunk", "1",
                ], cwd=root, capture_output=True, text=True, check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
            summary = json.loads((output_root / "batch-summary.json").read_text())
            self.assertEqual(summary["counts"], {"cases_requested": 2, "completed": 1, "failed": 1})
            first = output_root / "cases" / "F2_BATCH_CASE_000"
            second = output_root / "cases" / "F2_BATCH_CASE_001"
            self.assertTrue((first / "case-execution-receipt.json").is_file())
            self.assertTrue((first / "typed-lifecycle-v4-summary.json").is_file())
            self.assertTrue((first / "typed-lifecycle-v4-records.jsonl").is_file())
            failure = json.loads((second / "case-execution-receipt.json").read_text())
            self.assertEqual(failure["status"], "FAILED")
            self.assertIn("stat", failure["error_message"].lower())
            self.assertFalse((second / "typed-lifecycle-v4-summary.json").exists())
            self.assertFalse((second / "typed-lifecycle-v4-records.jsonl").exists())

    def test_real_prepare_cli_success_alias_rejection_and_current_sha_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = make_source(root)
            args = args_for(root, source, root / "unused")
            success = subprocess.run(
                prepare_cli(args, output=root / "cli-success"),
                cwd=root, capture_output=True, text=True, check=False,
            )
            self.assertEqual(success.returncode, 0, success.stderr or success.stdout)
            result = json.loads(success.stdout)
            self.assertEqual(result["exact_join_count"], 335)
            self.assertEqual(result["historical_alias_count"], 1)
            self.assertTrue(Path(result["manifest"]).is_file())
            alias = request_builder.ALIAS_CASE
            alias_result = subprocess.run(
                prepare_cli(args, output=root / "cli-alias", case_ids=[alias]),
                cwd=root, capture_output=True, text=True, check=False,
            )
            self.assertNotEqual(alias_result.returncode, 0)
            self.assertIn("exact eligible", alias_result.stderr)
            bad_sha_result = subprocess.run(
                prepare_cli(args, output=root / "cli-bad-sha", current_sha="0" * 64),
                cwd=root, capture_output=True, text=True, check=False,
            )
            self.assertNotEqual(bad_sha_result.returncode, 0)
            self.assertIn("CURRENT SHA differs", bad_sha_result.stderr)


if __name__ == "__main__":
    unittest.main()
