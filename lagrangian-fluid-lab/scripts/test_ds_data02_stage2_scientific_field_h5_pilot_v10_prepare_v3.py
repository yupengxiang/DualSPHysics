#!/usr/bin/env python3
"""Executable ABI tests for the additive V3 single-case H5 pilot builder.

The builder fixture is metadata-only.  The second test uses the real primary
V3 worker and V5 verifier on a tiny HDF5, then asks the real V10 closure
validator to validate the resulting request shape.  No production HDF5 or
ledger is opened by this test.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "pilot_v10_prepare_v3",
    HERE / "ds_data02_stage2_scientific_field_h5_pilot_v10_prepare_v3.py",
)
assert SPEC and SPEC.loader
PREP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREP)

PRIMARY_ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
PRIMARY_SCRIPTS = PRIMARY_ROOT / "lagrangian-fluid-lab/scripts"
PRIMARY_VENV = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
PRIMARY_V3_WORKER = PRIMARY_SCRIPTS / "ds_data02_stage2_scientific_field_h5_audit_v3.py"
PRIMARY_V5_VERIFIER = PRIMARY_SCRIPTS / "ds_data02_stage2_verify_scientific_field_h5_audit_v5.py"
PRIMARY_CONFIG = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DsphConfig.xml")

V5_TEST_SPEC = importlib.util.spec_from_file_location(
    "primary_v5_fixture_helpers",
    PRIMARY_SCRIPTS / "test_ds_data02_stage2_verify_scientific_field_h5_audit_v5_cli.py",
)
assert V5_TEST_SPEC and V5_TEST_SPEC.loader
V5_TEST = importlib.util.module_from_spec(V5_TEST_SPEC)
V5_TEST_SPEC.loader.exec_module(V5_TEST)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    return path


def ref(path: Path, role: str) -> dict[str, object]:
    value = path.stat()
    return {
        "role": role,
        "path": str(path.resolve()),
        "bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
        "st_dev": int(value.st_dev),
        "st_ino": int(value.st_ino),
        "sha256": sha256(path),
        "content_read_by_preparer": True,
    }


class PilotV10V3Tests(unittest.TestCase):
    def _builder_fixture(self) -> tuple[Path, object]:
        root = Path(tempfile.mkdtemp(prefix="ds02-pilot-v10-v3-fixture-"))
        scripts = root / "scripts"
        scripts.mkdir()
        names = (
            "worker.py", "verifier.py", "runtime-v10.py", "runtime-v9.py", "runtime-v8.py",
            "runtime-v6.py", "runtime-v2.py", "git-v1.py", "git-v2.py", "git-v3.py",
            "dispatch.py", "strict.py", "config.xml",
        )
        for name in names:
            (scripts / name).write_text("# bounded fixture\n", encoding="utf-8")
        venv = root / ".venv/bin/python"
        venv.parent.mkdir(parents=True)
        venv.write_text("#!/bin/sh\n", encoding="utf-8")
        venv.chmod(0o755)
        shared = write_json(root / "metadata/shared.json", {"schema": "fixture"})
        pilot_cases: list[dict[str, object]] = []
        current_cases: list[dict[str, object]] = []
        for index, family in enumerate(PREP.PILOT_FAMILIES):
            case_id = f"{family}_FIXTURE_CASE"
            h5 = root / "payload" / f"{case_id}.h5"
            h5.parent.mkdir(exist_ok=True)
            h5.write_bytes(b"deferred-h5-stat-only")
            stat = h5.stat()
            h5_ref = {
                "role": f"{case_id} trajectory_h5", "path": str(h5), "bytes": stat.st_size,
                "mtime_ns": stat.st_mtime_ns, "ctime_ns": stat.st_ctime_ns,
                "st_dev": stat.st_dev, "st_ino": stat.st_ino,
                "known_sha256": "a" * 64, "content_read_by_preparer": False,
                "deferred_after_parent_reservation": True,
            }
            fields: dict[str, object] = {}
            for field in ("producer_terminal_proof", "producer_receipt", "typed_summary"):
                source = write_json(root / "metadata" / f"{case_id}-{field}.json", {"case": case_id, "field": field})
                fields[field] = ref(source, f"{case_id} {field}")
            if family != "F2":
                source = write_json(root / "metadata" / f"{case_id}-manifest.json", {"case": case_id})
                fields["case_manifest"] = ref(source, f"{case_id} case_manifest")
            case = {
                "physical_case_id": case_id, "family_id": family,
                "trajectory_h5": h5_ref, "source_content_read_by_preparer": False,
                **fields,
            }
            pilot_cases.append(case)
            current_cases.append({"physical_case_id": case_id, "family_id": family, "current_index": index, "frames": 2, "particles": 3})
        current_cases.extend({"physical_case_id": f"EXTRA_{i:03d}", "family_id": "F1", "current_index": i + 7, "frames": 2, "particles": 3} for i in range(329))
        current = write_json(root / "current.json", {"schema": PREP.CURRENT_SCHEMA, "cases": current_cases})
        master = write_json(root / "master.json", {"schema": "ds02.stage2.scientific-field-h5-batch-source.v1", "status": "SOURCE_PREPARED_335_CANONICAL_METADATA_ONLY", "cases": [{"physical_case_id": row["physical_case_id"], "family_id": row["family_id"]} for row in current_cases[:335]]})
        plan = write_json(root / "plan.json", {"schema": "typed-lifecycle-continuation-plan.v4"})
        registry = write_json(root / "registry.json", {"schema": "typed-lifecycle-evidence-registry.v4"})
        pilot = write_json(root / "pilot.json", {"schema": PREP.MANIFEST_SCHEMA, "static_source_refs": [ref(shared, "fixture shared")], "cases": pilot_cases})
        old_sha = PREP.CURRENT_SHA256
        PREP.CURRENT_SHA256 = sha256(current)
        args = type("Args", (), {
            "pilot_index": pilot, "source_manifest": master, "current": current, "plan": plan, "registry": registry,
            "worker": scripts / "worker.py", "verifier": scripts / "verifier.py", "runtime_v10": scripts / "runtime-v10.py",
            "runtime_v9": scripts / "runtime-v9.py", "runtime_v8": scripts / "runtime-v8.py", "runtime_v6": scripts / "runtime-v6.py", "runtime_v2": scripts / "runtime-v2.py",
            "git_helper_v1": scripts / "git-v1.py", "git_helper_v2": scripts / "git-v2.py", "git_helper_v3": scripts / "git-v3.py",
            "dispatch": scripts / "dispatch.py", "strict_dispatch": scripts / "strict.py", "python": venv,
            "config": scripts / "config.xml", "output_dir": root / "out", "lab_root": root / "lab", "worktree_root": root,
            "source_rebind_from": None, "source_rebind_to": None, "chunk": 2, "max_wall_seconds": 30, "max_memory_bytes": 1024 * 1024,
        })()
        args.lab_root.mkdir()
        args._old_current_sha = old_sha
        return root, args

    def test_prepare_emits_real_manifest_cpu_kind_and_complete_v10_closure(self) -> None:
        root, args = self._builder_fixture()
        try:
            result = PREP.prepare(args)
            document = json.loads(Path(result["index"]).read_text(encoding="utf-8"))
            first = next(row for row in document["requests"] if row["family_id"] == "F1")
            request = json.loads(Path(first["request"]["path"]).read_text(encoding="utf-8"))
            manifest = json.loads(Path(request["manifest_contract"]["path"]).read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema"], "ds02.stage2.scientific-field-h5-audit-manifest.v2")
            self.assertEqual(manifest["status"], "READY_FOR_GUARDED_RAW_H5_FIELD_AUDIT")
            self.assertEqual(request["cpu_task_kind"], "audit")
            self.assertIsInstance(request["estimated_storage_bytes"], int)
            self.assertIsInstance(request["estimated_peak_memory_bytes"], int)
            required = {"runtime_v10_git_bound", "runtime_v9_git_bound", "runtime_v8", "runtime_v6", "runtime_v2", "git_snapshot_v1", "git_snapshot_v2", "git_snapshot_v3"}
            self.assertTrue(required.issubset(request["runtime_binding"]))
            self.assertTrue(all(
                isinstance(binding, dict)
                and binding.get("path") in request["input_files"]
                and request["input_sha256"].get(binding.get("path")) == binding.get("sha256")
                for role, binding in request["runtime_binding"].items()
                if role in required
            ))
            self.assertEqual(request["command"][3], "audit")
        finally:
            PREP.CURRENT_SHA256 = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
            shutil.rmtree(root, ignore_errors=True)

    def test_rebind_preserves_sha_and_rejects_changed_target(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="ds02-pilot-v10-v3-rebind-"))
        try:
            old = root / "old" / "producer.json"
            new = root / "new" / "producer.json"
            old.parent.mkdir(parents=True)
            new.parent.mkdir(parents=True)
            old.write_text('{"case":"C"}\n', encoding="utf-8")
            shutil.copy2(old, new)
            args = type("Args", (), {"source_rebind_from": root / "old", "source_rebind_to": root / "new"})()
            checked = PREP._rebind_source_ref(ref(old, "producer"), "producer", args)
            self.assertEqual(checked["path"], str(new.resolve()))
            self.assertEqual(checked["sha256"], sha256(old))
            new.write_text('{"case":"TAMPERED"}\n', encoding="utf-8")
            with self.assertRaises(PREP.PilotPrepareError):
                PREP._rebind_source_ref(ref(old, "producer"), "producer", args)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_master_case_join_rejects_deferred_sha_mismatch(self) -> None:
        selected = {
            "F1": {
                "physical_case_id": "F1_CASE",
                "trajectory_h5": {"bytes": 10, "known_sha256": "a" * 64},
            },
        }
        source = {
            "cases": [{
                "physical_case_id": "F1_CASE", "family_id": "F1",
                "trajectory_h5": {"bytes": 11, "known_sha256": "a" * 64},
            }],
        }
        with self.assertRaises(PREP.PilotPrepareError):
            PREP._validate_master_case_join(selected, source)

    def test_primary_rebound_index_joins_real_335_group_cases(self) -> None:
        """Use the real seven-ID primary index, never the obsolete F2-H10 pilot."""
        request_root = PRIMARY_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests"
        package = request_root / "scientific-field-h5-335-batch-v3-primary-rebound-v4-root307-001"
        source = request_root / "scientific-field-h5-335-batch-source-prepared-001"
        pilot = package / "scientific-field-h5-primary-rebound-v3-pilot-index.json"
        current = PRIMARY_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/CURRENT336.json"
        plan = PRIMARY_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/CURRENT336_TYPED_LIFECYCLE_AFTER_ROOT307_V4.json"
        registry = request_root / "typed-lifecycle-evidence-registry-v4-after-root307-001.json"
        source_manifest = source / "scientific-field-h5-335-batch-manifest.json"
        required = [pilot, source_manifest, current, plan, registry, PRIMARY_V3_WORKER, PRIMARY_V5_VERIFIER]
        if not all(path.is_file() for path in required):
            self.skipTest("primary rebound metadata package is not mounted")
        with tempfile.TemporaryDirectory(prefix="ds02-pilot-v10-v3-primary-join-") as raw:
            output = Path(raw) / "fresh-output"
            args = type("Args", (), {
                "pilot_index": pilot, "source_manifest": source_manifest, "current": current, "plan": plan, "registry": registry,
                "worker": PRIMARY_V3_WORKER, "verifier": PRIMARY_V5_VERIFIER,
                "runtime_v10": PRIMARY_SCRIPTS / "ds_data02_runtime_v10_git_bound.py",
                "runtime_v9": PRIMARY_SCRIPTS / "ds_data02_runtime_v9_git_bound.py",
                "runtime_v8": PRIMARY_SCRIPTS / "ds_data02_runtime_v8.py",
                "runtime_v6": PRIMARY_SCRIPTS / "ds_data02_runtime_v6.py",
                "runtime_v2": PRIMARY_SCRIPTS / "ds_data02_runtime_v2.py",
                "git_helper_v1": PRIMARY_SCRIPTS / "ds_data02_git_launch_state_v1.py",
                "git_helper_v2": PRIMARY_SCRIPTS / "ds_data02_git_launch_state_v2.py",
                "git_helper_v3": PRIMARY_SCRIPTS / "ds_data02_git_launch_state_v3.py",
                "dispatch": PRIMARY_SCRIPTS / "ds_data02_stage2_dispatch_v9.py",
                "strict_dispatch": PRIMARY_SCRIPTS / "ds_data02_strict_dispatch_v9.py",
                "python": PRIMARY_VENV,
                "config": PRIMARY_CONFIG,
                "output_dir": output, "lab_root": PRIMARY_ROOT / "lagrangian-fluid-lab", "worktree_root": PRIMARY_ROOT,
                "source_rebind_from": None, "source_rebind_to": None, "chunk": 65536,
                "max_wall_seconds": 900, "max_memory_bytes": 4 * 1024**3,
            })()
            result = PREP.prepare(args)
            self.assertEqual(result["requests"], 7)
            index = json.loads(Path(result["index"]).read_text(encoding="utf-8"))
            self.assertEqual([row["physical_case_id"] for row in index["requests"]], [
                "F1_DUAL_HEAD_340_VX_150_FRESH090_V1",
                "F2_STAGE1_FIRST8_OFFSET_OPEN_RIM_RX050_RY014_FILL080",
                "F3_TWOAXIS_PITCH1000_AY0540_STAGE1_FIRST24_NEW",
                "F4_DROP_gap0p24000_xoffm0p08000_yoff0p04000_uz0p60000",
                "F5_COMPACT_RUNUP_RECOVERY_C082S1_M110_T100",
                "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S130_DP025",
                "F7_OBSTACLE_QUINTIC_B08_A036P5",
            ])
            self.assertFalse(index["source_read_cost"]["f2_missing_manifest_isolated_unknown"])
            first_request = json.loads(Path(index["requests"][0]["request"]["path"]).read_text(encoding="utf-8"))
            self.assertEqual(first_request["cpu_task_kind"], "audit")
            self.assertTrue(first_request["manifest_contract"]["path"].endswith("scientific-field-h5-audit-manifest.json"))
            # Exercise the real V10 light/content-binding validator against
            # the generated request.  This is still metadata-only: V10 hashes
            # the declared code/JSON inputs, while the deferred HDF5 remains
            # outside input_files until the parent reservation.
            v10_spec = importlib.util.spec_from_file_location(
                "primary_runtime_v10_primary_join",
                PRIMARY_SCRIPTS / "ds_data02_runtime_v10_git_bound.py",
            )
            self.assertIsNotNone(v10_spec)
            assert v10_spec and v10_spec.loader
            v10 = importlib.util.module_from_spec(v10_spec)
            v10_spec.loader.exec_module(v10)
            bound = v10._validate_with_closure(first_request)
            self.assertIn(str((PRIMARY_SCRIPTS / "ds_data02_runtime_v10_git_bound.py").resolve()), bound)

    def test_real_v3_worker_v5_verifier_and_v10_closure(self) -> None:
        runtime = PRIMARY_SCRIPTS
        with tempfile.TemporaryDirectory(prefix="ds02-pilot-v10-v3-real-") as raw:
            directory = Path(raw)
            h5_path = directory / "fixture.h5"
            V5_TEST.V4_TEST.BASE.write_h5(h5_path)
            manifest = V5_TEST.V4_TEST.write_metadata_chain(directory, h5_path)
            report = directory / "report.json"
            worker = subprocess.run([str(PRIMARY_VENV), "-B", str(PRIMARY_V3_WORKER), "audit", "--manifest", str(manifest), "--output", str(report), "--chunk", "2"], text=True, capture_output=True, check=False)
            self.assertEqual(worker.returncode, 0, worker.stderr)
            verified = directory / "verified.json"
            result = subprocess.run([str(PRIMARY_VENV), "-B", str(PRIMARY_V5_VERIFIER), "verify", "--manifest", str(manifest), "--report", str(report), "--output", str(verified), "--allow-fixture-context"], text=True, capture_output=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(verified.read_text(encoding="utf-8"))["scientific_credit"], 0)

            import sys
            sys.path.insert(0, str(runtime))
            v10_spec = importlib.util.spec_from_file_location("primary_runtime_v10", runtime / "ds_data02_runtime_v10_git_bound.py")
            assert v10_spec and v10_spec.loader
            v10 = importlib.util.module_from_spec(v10_spec)
            v10_spec.loader.exec_module(v10)
            closure = [
                runtime / name for name in (
                    "ds_data02_runtime_v10_git_bound.py", "ds_data02_runtime_v9_git_bound.py", "ds_data02_runtime_v8.py",
                    "ds_data02_runtime_v6.py", "ds_data02_runtime_v2.py", "ds_data02_git_launch_state_v1.py",
                    "ds_data02_git_launch_state_v2.py", "ds_data02_git_launch_state_v3.py",
                )
            ]
            closure += [PRIMARY_V3_WORKER, PRIMARY_V5_VERIFIER, manifest]
            request = {
                "schema": "ds02.request.v1", "family_id": "F1", "case_id": "tiny-audit", "attempt_id": "tiny-audit-001",
                "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 1, "max_wall_seconds": 60,
                "max_memory_bytes": 512 * 1024 * 1024, "estimated_peak_memory_bytes": 512 * 1024 * 1024,
                "estimated_storage_bytes": 4 * 1024 * 1024, "cwd": str(PRIMARY_ROOT / "lagrangian-fluid-lab"), "worktree_root": str(PRIMARY_ROOT),
                "command": [str(PRIMARY_VENV), "-B", str(PRIMARY_V3_WORKER), "audit", "--manifest", str(manifest), "--output", "{attempt_root}/report.json", "--chunk", "2"],
                "input_files": [str(path.resolve()) for path in closure],
                "input_sha256": {str(path.resolve()): sha256(path) for path in closure},
            }
            actual = v10._validate_with_closure(request)
            self.assertEqual(set(actual), {str(path.resolve()) for path in closure})
            missing = dict(request)
            missing["input_files"] = [value for value in request["input_files"] if not value.endswith("ds_data02_git_launch_state_v3.py")]
            with self.assertRaises(ValueError):
                v10._validate_with_closure(missing)


if __name__ == "__main__":
    unittest.main()
