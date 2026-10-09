#!/usr/bin/env python3
"""Source-only tests for the remaining ROOT282--ROOT307 partition."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest


HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "ds_data02_stage2_build_root282_lifecycle_queue.py"
spec = importlib.util.spec_from_file_location("root282_queue", SCRIPT)
if spec is None or spec.loader is None:  # pragma: no cover
    raise RuntimeError(f"cannot import {SCRIPT}")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Root282QueueTest(unittest.TestCase):
    def test_real_cli_self_test(self) -> None:
        result = subprocess.run([sys.executable, str(SCRIPT), "self-test"], check=True, capture_output=True, text=True)
        value = json.loads(result.stdout)
        self.assertEqual(value["status"], "PASS")
        self.assertFalse(value["payload_content_opened"])
        self.assertFalse(value["launch_performed"])

    def test_partition_covers_remaining_exact_rows_without_prepared_cases(self) -> None:
        plan, _, prepared, scope = module._validate_frozen_inputs()
        batches = module._partition(plan, prepared, scope)
        self.assertEqual(len(batches), 26)
        ids = [case_id for batch in batches for case_id in batch["case_ids"]]
        self.assertEqual(len(ids), 202)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(set(ids).isdisjoint(prepared))
        self.assertEqual([batch["namespace"] for batch in batches], [f"ROOT{i}" for i in range(282, 308)])
        self.assertTrue(all(batch["family_id"] in {"F1", "F2", "F3", "F4", "F5", "F7"} for batch in batches))
        self.assertTrue(all(len(batch["case_ids"]) <= module.MAX_CASES for batch in batches))
        self.assertTrue(all(batch["source_bytes"] <= module.MAX_GROUP_BYTES for batch in batches))
        self.assertEqual(sum(len(batch["selected_original118_unlocated_case_ids"]) for batch in batches), 7)
        self.assertEqual(sum(len(batch["selected_historical_original118_case_ids"]) for batch in batches), 29)

    def test_frozen_prepared_selection_manifests_are_not_payload_inputs(self) -> None:
        for path in (module.ROOT280_SELECTION, module.ROOT281_SELECTION):
            value = module._json(path, "prepared selection")
            self.assertEqual(value["status"], "READY_SOURCE_ONLY_NO_LAUNCH")
            self.assertTrue(all(Path(ref["path"]).suffix.lower() not in module.PAYLOAD_SUFFIXES for ref in value["source_refs"]))
            self.assertFalse(value["source_read_policy"]["trajectory_content_opened"])


if __name__ == "__main__":
    unittest.main()
