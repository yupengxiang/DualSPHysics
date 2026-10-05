from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
VALIDATION = HERE / 'metadata' / 'static-validation.json'


class Fresh067SourceContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = json.loads(VALIDATION.read_text(encoding='utf-8'))

    def test_source_only_and_disabled(self) -> None:
        self.assertTrue(self.data['source_only'])
        self.assertFalse(self.data['launch_allowed'])
        self.assertFalse(self.data['execution_allowed'])
        self.assertFalse(self.data['gencase_launched'])
        self.assertFalse(self.data['solver_launched'])
        self.assertFalse(self.data['native_frame0_audit_launched'])
        self.assertFalse(self.data['raw_arrays_read'])
        self.assertFalse(self.data['raw_arrays_hashed'])
        self.assertEqual(self.data['independent_case_count_increment'], 0)

    def test_corner_coverage_and_distinct_hashes(self) -> None:
        self.assertEqual(self.data['selected_case_count'], 8)
        self.assertEqual({row['parent_case_id'] for row in self.data['cases']}, {
            'F1_STAGE1_ECC_H110_DP010', 'F1_STAGE1_ECC_H190_DP010',
            'F1_STAGE1_DUAL_H220_DP020', 'F1_STAGE1_DUAL_H340_DP020',
        })
        self.assertEqual({tuple(row['velocity_m_per_s']) for row in self.data['cases']}, {(0.1, 0.0, 0.0), (0.2, 0.0, 0.0)})
        self.assertEqual(len({row['physical_condition_sha256'] for row in self.data['cases']}), 8)
        for row in self.data['cases']:
            self.assertNotEqual(row['physical_condition_sha256'], row['source_plan_condition_sha256'])
            self.assertIsNone(row['future_receipt_sha256'])
            self.assertIsNone(row['future_native_frame0_audit_sha256'])

    def test_validator_repeats_without_mutating(self) -> None:
        completed = subprocess.run([sys.executable, str(HERE / 'validate_source_contract.py')], check=False, capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == '__main__':
    unittest.main()
