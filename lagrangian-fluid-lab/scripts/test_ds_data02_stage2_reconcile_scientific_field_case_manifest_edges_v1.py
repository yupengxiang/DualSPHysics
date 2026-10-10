#!/usr/bin/env python3
"""Read-only reconciliation test against the frozen primary metadata chain."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "ds_data02_stage2_reconcile_scientific_field_case_manifest_edges_v1.py"
PRIMARY = Path(os.environ.get("DS02_PRIMARY_ROOT", "/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics"))
STAGE2 = PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
CURRENT = STAGE2 / "CURRENT336.json"
SOURCE = STAGE2 / "requests/scientific-field-h5-335-batch-source-prepared-001/scientific-field-h5-335-batch-manifest.json"
PLAN = STAGE2 / "checkpoints/CURRENT336_TYPED_LIFECYCLE_AFTER_ROOT307_V4.json"
REGISTRY = STAGE2 / "requests/typed-lifecycle-evidence-registry-v4-after-root307-001.json"
ROOT307 = STAGE2 / "checkpoints/ROOT307_ACTUAL_LIFECYCLE_METADATA_INDEPENDENT_CLOSURE_V1.json"


class ReconcileCaseManifestEdgesTests(unittest.TestCase):
    def test_primary_metadata_reports_single_missing_created_manifest_edge(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage2-case-edge-reconcile-") as raw:
            output = Path(raw) / "reconciliation.json"
            result = subprocess.run(
                [
                    "python3", "-B", str(SCRIPT),
                    "--current", str(CURRENT),
                    "--source-manifest", str(SOURCE),
                    "--plan", str(PLAN),
                    "--registry", str(REGISTRY),
                    "--root307-proof", str(ROOT307),
                    "--output", str(output),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            value = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(value["schema"], "ds02.stage2.scientific-field-case-manifest-edge-reconciliation.v1")
            self.assertEqual(value["scope"]["current_cases"], 336)
            self.assertEqual(value["scope"]["canonical_source_cases"], 335)
            self.assertEqual(value["scope"]["canonical_case_manifest_edges"], 334)
            self.assertEqual(value["scope"]["missing_case_manifest_edges"], 1)
            self.assertEqual(value["scope"]["historical_alias_id"], "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090")
            gap = value["current_manifest_edge_gaps"]
            self.assertEqual(len(gap), 1)
            self.assertEqual(gap[0]["physical_case_id"], "F2H10V2_OFFSET_V1")
            self.assertEqual(gap[0]["edge_status"], "MISSING_CREATED_CASE_MANIFEST")
            self.assertTrue(gap[0]["metadata_recovery_possible"])
            self.assertFalse(gap[0]["production_eligible"])
            self.assertFalse(gap[0]["deferred_trajectory"]["content_read_by_sidecar"])
            self.assertFalse(value["source_read_policy"]["trajectory_h5_content_read"])
            self.assertFalse(value["conclusion"]["canonical_production_admission"])


if __name__ == "__main__":
    unittest.main()
