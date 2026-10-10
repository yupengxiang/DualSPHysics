#!/usr/bin/env python3
"""Metadata-only tests for the primary-checkout rebound pilot index."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "ds02_h5_primary_rebound_prepare_v1",
    HERE / "ds_data02_stage2_scientific_field_h5_primary_rebound_prepare_v1.py",
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

PRIMARY = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
STAGE2 = PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
CURRENT = STAGE2 / "CURRENT336.json"
ROOT307 = STAGE2 / "checkpoints/ROOT307_ACTUAL_LIFECYCLE_METADATA_INDEPENDENT_CLOSURE_V1.json"


class PrimaryReboundPilotIndexTests(unittest.TestCase):
    def test_primary_pilot_index_binds_seven_actual_terminal_proofs(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage2-h5-primary-rebound-") as raw:
            result = MODULE.build_pilot_index(PRIMARY, Path(raw), CURRENT, ROOT307)
            output = Path(result["pilot_index"])
            value = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(value["schema"], "ds02.stage2.scientific-field-h5-primary-rebound.v1")
            self.assertEqual(value["status"], "SOURCE_PREPARED_PRIMARY_REBOUND_NOT_RUN")
            self.assertEqual(value["pilot_count"], 7)
            self.assertEqual(value["current"]["sha256"], MODULE.CURRENT_SHA256)
            self.assertEqual(len(value["pilots"]), 7)
            self.assertTrue(all(item["scientific_credit"] == 0 for item in value["pilots"]))
            self.assertTrue(all(item["production_payload_opened"] is False for item in value["pilots"]))

    def test_pilot_index_rejects_tampered_root307_coverage(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage2-h5-primary-rebound-bad-") as raw:
            directory = Path(raw)
            bad_proof = directory / "root307-bad.json"
            proof = json.loads(ROOT307.read_text(encoding="utf-8"))
            proof["coverage"]["actual_saved_mask_cases"] = 334
            bad_proof.write_text(json.dumps(proof), encoding="utf-8")
            with self.assertRaises(MODULE.ReboundError):
                MODULE.build_pilot_index(PRIMARY, directory / "output", CURRENT, bad_proof)


if __name__ == "__main__":
    unittest.main()
