#!/usr/bin/env python3
"""Source-only tests for the V2 HDF5 read-I/O versus new-storage contract."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("pilot_v10_prepare", HERE / "ds_data02_stage2_scientific_field_h5_pilot_v10_prepare_v2.py")
assert SPEC and SPEC.loader
PREP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREP)
VERIFY_SPEC = importlib.util.spec_from_file_location("pilot_v10_verify", HERE / "ds_data02_stage2_scientific_field_h5_pilot_v10_verify_v6.py")
assert VERIFY_SPEC and VERIFY_SPEC.loader
VERIFY = importlib.util.module_from_spec(VERIFY_SPEC)
VERIFY_SPEC.loader.exec_module(VERIFY)


def write_json(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return path


def ref(path: Path, role: str) -> dict[str, object]:
    stat = path.stat()
    return {
        "role": role, "path": str(path.resolve()), "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns, "ctime_ns": stat.st_ctime_ns,
        "st_dev": stat.st_dev, "st_ino": stat.st_ino,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "content_read_by_preparer": True,
    }


class PilotV10Tests(unittest.TestCase):
    def _fixture(self) -> tuple[Path, object, object]:
        root = Path(tempfile.mkdtemp(prefix="ds02-pilot-v10-fixture-"))
        scripts = root / "scripts"
        scripts.mkdir()
        for name in ("worker.py", "verifier.py", "runtime.py", "dispatch.py", "strict.py", "config.xml"):
            (scripts / name).write_text("# bounded fixture\n", encoding="utf-8")
        venv = root / ".venv/bin/python"
        venv.parent.mkdir(parents=True)
        venv.write_text("#!/bin/sh\n", encoding="utf-8")
        venv.chmod(0o755)
        shared = write_json(root / "metadata/shared.json", {"schema": "fixture"})
        pilot_cases = []
        current_cases = []
        families = ("F1", "F2", "F3", "F4", "F5", "F6", "F7")
        for index, family in enumerate(families):
            case_id = f"{family}_FIXTURE_CASE"
            h5 = root / "payload" / f"{case_id}.h5"
            h5.parent.mkdir(exist_ok=True)
            h5.write_bytes(b"deferred-h5-stat-only")
            hs = h5.stat()
            h5_ref = {
                "role": f"{case_id} trajectory_h5", "path": str(h5), "bytes": hs.st_size,
                "mtime_ns": hs.st_mtime_ns, "ctime_ns": hs.st_ctime_ns, "st_dev": hs.st_dev,
                "st_ino": hs.st_ino, "known_sha256": "a" * 64,
                "content_read_by_preparer": False, "deferred_after_reservation": True,
            }
            case = {
                "physical_case_id": case_id, "family_id": family,
                "trajectory_h5": h5_ref,
                "producer_terminal_proof": ref(write_json(root / "metadata" / f"{case_id}-proof.json", {"case": case_id}), f"{case_id} proof"),
                "producer_receipt": ref(write_json(root / "metadata" / f"{case_id}-receipt.json", {"case": case_id}), f"{case_id} receipt"),
                "typed_summary": ref(write_json(root / "metadata" / f"{case_id}-summary.json", {"case": case_id}), f"{case_id} summary"),
                "source_content_read_by_preparer": False,
            }
            if family != "F2":
                case["case_manifest"] = ref(write_json(root / "metadata" / f"{case_id}-manifest.json", {"case": case_id}), f"{case_id} manifest")
            pilot_cases.append(case)
            current_cases.append({"physical_case_id": case_id, "family_id": family, "current_index": index, "frames": 2, "particles": 3})
        current_cases.extend({"physical_case_id": f"EXTRA_{i:03d}", "family_id": "F1", "current_index": i + 7, "frames": 2, "particles": 3} for i in range(329))
        current = write_json(root / "current.json", {"schema": "ds02.stage2.current336.v1", "cases": current_cases})
        master_cases = [{"physical_case_id": row["physical_case_id"], "family_id": row["family_id"]} for row in current_cases[:335]]
        master = write_json(root / "master.json", {"schema": "ds02.stage2.scientific-field-h5-batch-source.v1", "status": "SOURCE_PREPARED_335_CANONICAL_METADATA_ONLY", "cases": master_cases, "groups": []})
        plan = write_json(root / "plan.json", {"schema": "typed-lifecycle-continuation-plan.v4"})
        registry = write_json(root / "registry.json", {"schema": "typed-lifecycle-evidence-registry.v4"})
        pilot = write_json(root / "pilot.json", {"schema": "ds02.stage2.scientific-field-h5-audit-manifest.v2", "static_source_refs": [ref(shared, "fixture shared")], "cases": pilot_cases})
        PREP.CURRENT_SHA256 = hashlib.sha256(current.read_bytes()).hexdigest()
        VERIFY.CURRENT_SHA256 = PREP.CURRENT_SHA256
        args = type("Args", (), {
            "pilot_index": pilot, "source_manifest": master, "current": current, "plan": plan, "registry": registry,
            "worker": scripts / "worker.py", "verifier": scripts / "verifier.py", "runtime_v10": scripts / "runtime.py",
            "dispatch": scripts / "dispatch.py", "strict_dispatch": scripts / "strict.py", "python": venv,
            "config": scripts / "config.xml", "output_dir": root / "out", "lab_root": root / "lab", "worktree_root": root,
            "source_rebind_from": None, "source_rebind_to": None, "chunk": 64, "max_wall_seconds": 30, "max_memory_bytes": 1024 * 1024,
        })()
        return root, args, current

    def test_prepare_and_independent_verify_seven_single_cases(self) -> None:
        root, args, _ = self._fixture()
        result = PREP.prepare(args)
        index_path = Path(result["index"])
        self.assertEqual(result["requests"], 7)
        document = json.loads(index_path.read_text(encoding="utf-8"))
        self.assertEqual(document["status"], "SOURCE_PREPARED_SEVEN_SINGLE_CASE_V10_NOT_RUN")
        self.assertEqual({row["family_id"] for row in document["requests"]}, set(PREP.PILOT_FAMILIES))
        f2 = next(row for row in document["requests"] if row["family_id"] == "F2")
        self.assertEqual(f2["case_manifest_status"], "UNKNOWN_MISSING_MANIFEST")
        verified = VERIFY.verify(index_path, root / "v6.json")
        self.assertEqual(verified["case_count"], 7)
        self.assertFalse(verified["production_eligible"])
        self.assertEqual(document["source_read_cost"]["estimated_storage_bytes"], document["source_read_cost"]["peak_serial_storage_bytes"])
        self.assertEqual(document["source_read_cost"]["temporary_copy_bytes"], 0)
        self.assertTrue(document["source_read_cost"]["source_h5_bytes_excluded_from_storage"])
        first_cost = document["requests"][0]["source_read_cost"]
        self.assertEqual(first_cost["source_h5_storage_bytes"], 0)
        self.assertEqual(first_cost["estimated_h5_read_bytes"], first_cost["deferred_h5_bytes"] * 3)
        self.assertLess(document["source_read_cost"]["estimated_storage_bytes"], 100 * 1024 * 1024)

    def test_deferred_h5_is_stat_only_and_source_rebind_is_explicit(self) -> None:
        root, _, _ = self._fixture()
        h5 = root / "payload/F1_FIXTURE_CASE.h5"
        record = PREP.deferred_h5({"path": str(h5), "bytes": h5.stat().st_size, "mtime_ns": h5.stat().st_mtime_ns, "ctime_ns": h5.stat().st_ctime_ns, "st_dev": h5.stat().st_dev, "st_ino": h5.stat().st_ino, "known_sha256": "f" * 64}, "fixture")
        self.assertFalse(record["content_read_by_preparer"])
        args = type("Args", (), {"source_rebind_from": Path("/old/root"), "source_rebind_to": Path("/new/root")})()
        rebound, provenance = PREP._rebind_path("/old/root/scripts/worker.py", args)
        self.assertEqual(rebound, "/new/root/scripts/worker.py")
        self.assertEqual(provenance, "/old/root/scripts/worker.py")


if __name__ == "__main__":
    unittest.main()
