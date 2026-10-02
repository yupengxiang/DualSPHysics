import json
import tempfile
import unittest
from pathlib import Path

from .. import f2_rv4eq_source_binding_reconciliation as reconcile


class F2RV4EqSourceBindingReconciliationTests(unittest.TestCase):
    def test_actual_mismatch_is_reported_without_rewriting_consumed_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            result = reconcile.build(Path(directory) / "reconciliation.json")
        self.assertTrue(result["all_reconciliation_checks_pass"])
        self.assertTrue(result["checks"]["original_label_declared_hash_mismatch"])
        self.assertTrue(result["checks"]["source_h5_hash_matches_conversion_report"])
        self.assertTrue(result["checks"]["medium_hash_matches_coarse_authoritative_hash"])
        self.assertTrue(result["resolution"]["original_report_rewritten"] is False)
        self.assertTrue(result["resolution"]["original_labels_rewritten"] is False)
        self.assertAlmostEqual(result["stale_declared_lineage"]["old_fluid_volume_m3"], 0.018876)
        self.assertAlmostEqual(result["authoritative_source_lineage"]["fluid_volume_m3"], 0.024576)
        self.assertEqual(result["resolution"]["q_n_status"], "pending; coarse/medium macro differences exceed budget")


if __name__ == "__main__":
    unittest.main()
