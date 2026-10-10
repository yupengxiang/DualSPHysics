#!/usr/bin/env python3
"""Metadata-only tests for the ROOT307 335-case field-audit index."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


HERE = Path(__file__).resolve().parent
MODULE_PATH = HERE / "ds_data02_stage2_scientific_field_h5_batch_prepare_v1.py"
SPEC = importlib.util.spec_from_file_location("scientific_field_h5_batch_prepare_v1", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ScientificFieldH5BatchPrepareV1Tests(unittest.TestCase):
    def _paths(self) -> tuple[Path, Path, Path]:
        return MODULE.CURRENT_DEFAULT, MODULE.PLAN_DEFAULT, MODULE.REGISTRY_DEFAULT

    def test_actual_root307_shape_excludes_one_alias_and_builds_bounded_groups(self) -> None:
        current_path, plan_path, registry_path = self._paths()
        current, _current_stat, current_sha = MODULE._read_json(current_path, "CURRENT")
        plan, _plan_stat, plan_sha = MODULE._read_json(plan_path, "plan")
        registry, _registry_stat, registry_sha = MODULE._read_json(registry_path, "registry")
        self.assertEqual(current_sha, MODULE.CURRENT_SHA256)
        self.assertEqual(plan_sha, MODULE.PLAN_SHA256)
        self.assertEqual(registry_sha, MODULE.REGISTRY_SHA256)
        canonical, _ = MODULE._case_shape(plan)
        selected = MODULE._registry_shape(registry, {row["physical_case_id"] for row in canonical})
        self.assertEqual(len(current["cases"]), 336)
        self.assertEqual(len(canonical), 335)
        self.assertEqual(len(selected), 335)
        self.assertEqual(sum(row.get("historical_alias") != "NONE" for row in plan["case_records"]), 1)

    def test_actual_build_stats_h5_without_hashing_or_opening_content(self) -> None:
        current_path, plan_path, registry_path = self._paths()
        original = MODULE._sha256_file

        def no_h5_hash(path: Path) -> str:
            self.assertNotIn(path.suffix.lower(), {".h5", ".hdf5"}, f"unexpected H5 hash: {path}")
            return original(path)

        with tempfile.TemporaryDirectory(prefix="stage2-field-h5-batch-") as raw:
            with mock.patch.object(MODULE, "_sha256_file", side_effect=no_h5_hash):
                result = MODULE.build_metadata(
                    current_path,
                    plan_path,
                    registry_path,
                    Path(raw) / "manifest",
                    Path(raw) / "report.json",
                )
            self.assertEqual(result["canonical_cases"], 335)
            self.assertEqual(result["historical_alias_excluded"], 1)
            self.assertFalse(result["trajectory_content_opened"])
            self.assertFalse(result["trajectory_content_hashed"])
            manifest = json.loads((Path(raw) / "manifest" / "scientific-field-h5-335-batch-manifest.json").read_text())
            self.assertEqual(len(manifest["cases"]), 335)
            self.assertEqual(len(manifest["groups"]), 43)
            self.assertTrue(all(group["case_count"] <= 8 for group in manifest["groups"]))
            self.assertTrue(all(group["declared_source_bytes"] <= MODULE.MAX_GROUP_BYTES for group in manifest["groups"]))
            self.assertFalse(manifest["execution"]["launch_allowed_by_this_index"])

    def test_duplicate_current_index_is_rejected(self) -> None:
        _current_path, plan_path, _registry_path = self._paths()
        plan, _stat, _sha = MODULE._read_json(plan_path, "plan")
        broken = copy.deepcopy(plan)
        broken["case_records"][1]["current_index"] = broken["case_records"][0]["current_index"]
        with self.assertRaises(MODULE.BatchPrepareError):
            MODULE._case_shape(broken)

    def test_real_prepare_cli_has_no_parser_shadow_and_writes_metadata_only(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage2-field-h5-batch-cli-") as raw:
            raw_path = Path(raw)
            result = subprocess.run(
                [
                    sys.executable,
                    str(MODULE_PATH),
                    "prepare",
                    "--current",
                    str(MODULE.CURRENT_DEFAULT),
                    "--plan",
                    str(MODULE.PLAN_DEFAULT),
                    "--registry",
                    str(MODULE.REGISTRY_DEFAULT),
                    "--output-dir",
                    str(raw_path / "manifest"),
                    "--report",
                    str(raw_path / "report.json"),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads(result.stdout)
            self.assertEqual(summary["canonical_cases"], 335)
            self.assertFalse(summary["trajectory_content_opened"])
            self.assertFalse(summary["trajectory_content_hashed"])


if __name__ == "__main__":
    unittest.main()
