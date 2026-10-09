#!/usr/bin/env python3
"""Small source-only tests for the ROOT280/281 lifecycle selector.

These tests exercise the real frozen plan/inventory/overlay join and the CLI
namespace guard.  They do not invoke the generic request builder and therefore
do not inspect trajectory, JSONL, native, or solver payloads.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest


HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "ds_data02_stage2_build_root280_lifecycle_batch.py"
spec = importlib.util.spec_from_file_location("root280_selector", SCRIPT)
if spec is None or spec.loader is None:  # pragma: no cover - import setup
    raise RuntimeError(f"cannot import {SCRIPT}")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Root280SelectorTest(unittest.TestCase):
    def test_real_cli_self_test_and_namespace_bounds(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "self-test"],
            check=True,
            capture_output=True,
            text=True,
        )
        result = json.loads(completed.stdout)
        self.assertEqual(result["status"], "PASS")
        self.assertFalse(result["payload_content_opened"])
        self.assertFalse(result["launch_performed"])
        with self.assertRaises(module.RootLifecycleError):
            module._namespace("ROOT279")
        with self.assertRaises(module.RootLifecycleError):
            module._namespace("ROOT310")

    def test_f4_first_group_selects_only_original118_unlocated_cases(self) -> None:
        _, refs, selected, details = module._load_scope(
            module.PLAN,
            module.INVENTORY,
            module.OVERLAY,
            "F4",
            "F4-typed-lifecycle-continuation-000",
        )
        self.assertEqual(set(refs), {"plan", "inventory", "overlay"})
        self.assertEqual(
            selected,
            [
                "F4_DROP_gap0p24000_xoffm0p08000_yoff0p04000_uz0p60000",
                "F4_DROP_gap0p22000_xoffm0p08000_yoffm0p04000_uz0p60000",
                "F4_DROP_gap0p20000_xoff0p08000_yoffm0p04000_uz0p40000",
                "F4_DROP_gap0p20000_xoff0p08000_yoff0p04000_uz0p60000",
            ],
        )
        self.assertEqual(len(details["diagnostic_excluded"]), 4)
        self.assertFalse(set(selected) & set(details["actual"]))
        self.assertFalse(set(selected) & set(details["aliases"]))

    def test_f6_first_group_is_bounded_and_single_family(self) -> None:
        _, _, selected, details = module._load_scope(
            module.PLAN,
            module.INVENTORY,
            module.OVERLAY,
            "F6",
            "F6-typed-lifecycle-continuation-000",
        )
        self.assertEqual(len(selected), 6)
        self.assertEqual(len(set(selected)), 6)
        self.assertLessEqual(len(selected), module.MAX_CASES)
        self.assertLess(details["selected_declared_source_bytes"], module.MAX_GROUP_BYTES)
        self.assertTrue(all(item.startswith("F6_") for item in selected))
        self.assertTrue(all(item in details["historical"] for item in selected))
        self.assertTrue(all(item in details["unlocated"] for item in selected))


if __name__ == "__main__":
    unittest.main()
