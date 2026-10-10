#!/usr/bin/env python3
"""Bounded metadata tests for the remaining 335-case V4 builder."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "scientific_field_h5_remaining_v4",
    HERE / "ds_data02_stage2_scientific_field_h5_prepare_remaining_v4.py",
)
assert SPEC and SPEC.loader
PREP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREP)

PRIMARY_ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
PRIMARY_SCRIPTS = PRIMARY_ROOT / "lagrangian-fluid-lab/scripts"
PRIMARY_REQUESTS = PRIMARY_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests"
PRIMARY_CURRENT = PRIMARY_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/CURRENT336.json"
PRIMARY_VENV = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
SOURCE_MANIFEST = PRIMARY_REQUESTS / "scientific-field-h5-335-batch-source-prepared-001/scientific-field-h5-335-batch-manifest.json"
PILOT_INDEX = PRIMARY_REQUESTS / "scientific-field-h5-seven-pilots-v10-v3-root-primary-001/scientific-field-h5-pilot-v10-request-index.json"
PLAN = PRIMARY_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/CURRENT336_TYPED_LIFECYCLE_AFTER_ROOT307_V4.json"
REGISTRY = PRIMARY_REQUESTS / "typed-lifecycle-evidence-registry-v4-after-root307-001.json"
CONFIG = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DsphConfig.xml")


def _available() -> bool:
    return all(path.is_file() for path in (PRIMARY_CURRENT, SOURCE_MANIFEST, PILOT_INDEX, PLAN, REGISTRY, CONFIG, PRIMARY_VENV))


def _args(output: Path):
    return type("Args", (), {
        "pilot_index": PILOT_INDEX, "source_manifest": SOURCE_MANIFEST,
        "current": PRIMARY_CURRENT, "plan": PLAN, "registry": REGISTRY,
        "worker": PRIMARY_SCRIPTS / "ds_data02_stage2_scientific_field_h5_audit_v3.py",
        "verifier": PRIMARY_SCRIPTS / "ds_data02_stage2_verify_scientific_field_h5_audit_v5.py",
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
        "python": PRIMARY_VENV, "config": CONFIG, "output_dir": output,
        "lab_root": PRIMARY_ROOT / "lagrangian-fluid-lab", "worktree_root": PRIMARY_ROOT,
        "source_rebind_from": None, "source_rebind_to": None,
        "chunk": 65536, "max_wall_seconds": 900, "max_memory_bytes": 4 * 1024**3,
    })()


@unittest.skipUnless(_available(), "primary 335 metadata package is not mounted")
class RemainingV4PrimaryTests(unittest.TestCase):
    def test_exact_327_plus_one_split_and_alias_exclusion(self) -> None:
        source = json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))
        pilot = json.loads(PILOT_INDEX.read_text(encoding="utf-8"))
        self.assertEqual(source["schema"], PREP.SOURCE_MANIFEST_SCHEMA)
        self.assertEqual(len(source["cases"]), 335)
        selected = {row["physical_case_id"] for row in pilot["requests"]}
        self.assertEqual(len(selected), 7)
        remaining = [row for row in source["cases"] if row["physical_case_id"] not in selected]
        self.assertEqual(len(remaining), 328)
        missing = [row for row in remaining if row["typed_lifecycle_evidence"].get("case_manifest") is None]
        self.assertEqual([row["physical_case_id"] for row in missing], ["F2H10V2_OFFSET_V1"])
        self.assertEqual({row["family_id"] for row in remaining}, set(PREP.PILOT_FAMILIES))

    def test_real_primary_build_and_independent_v7_validation(self) -> None:
        # The builder reads only bounded JSON/stat metadata.  In particular,
        # the deferred HDF5 paths are never opened or hashed by this test.
        with tempfile.TemporaryDirectory(prefix="ds02-remaining-v4-primary-") as raw:
            result = PREP.prepare(_args(Path(raw) / "remaining"))
            self.assertEqual(result["executable_cases"], 327)
            self.assertEqual(result["unknown_cases"], 1)
            self.assertFalse(result["payload_read"])
            checked = PREP.validate(Path(result["index"]))
            self.assertEqual(checked["verified_requests"], 327)
            self.assertEqual(checked["unknown_cases"], ["F2H10V2_OFFSET_V1"])
            self.assertEqual(checked["peak_serial_storage_bytes"], 48_234_496)
            index = json.loads(Path(result["index"]).read_text(encoding="utf-8"))
            unknown = next(row for row in index["requests"] if row["physical_case_id"] == "F2H10V2_OFFSET_V1")
            self.assertIsNone(unknown["request"])
            self.assertEqual(unknown["case_manifest_status"], "UNKNOWN_MISSING_MANIFEST")


if __name__ == "__main__":
    unittest.main()
