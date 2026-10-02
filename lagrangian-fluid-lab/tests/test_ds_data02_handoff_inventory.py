import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from ds_data02_handoff_inventory import integrity_status


class HandoffAcceptanceTests(unittest.TestCase):
    def report(self):
        return dict(q_i_status='Q-I-structure-pass', missing_requirements=[],
                    structural_failures=[], solver_log_consistency={'status': 'pass'})

    def test_solver_count_pass_does_not_accept_missing_contract(self):
        r = self.report()
        r.update(q_i_status='Q-I-incomplete', missing_requirements=['geometry'])
        self.assertEqual(integrity_status(r), 'incomplete_contract')

    def test_structural_error_rejects_even_matching_solver_counts(self):
        r = self.report()
        r['structural_failures'] = ['nonfinite_active_position']
        self.assertEqual(integrity_status(r), 'structural_failure')

    def test_missing_checks_are_not_defaulted_to_success(self):
        self.assertEqual(integrity_status({'solver_log_consistency': {'status': 'pass'}}),
                         'incomplete_report')

    def test_family_physics_failure_is_retained(self):
        r = self.report()
        r['f6_physics_status'] = 'fail'
        self.assertEqual(integrity_status(r), 'family_physics_failure')

    def test_matching_complete_integrity_report_remains_integrity_only(self):
        self.assertEqual(integrity_status(self.report()), 'existing_report_structure_pass')

    def test_absent_report_is_not_audited(self):
        self.assertEqual(integrity_status(None), 'not_audited')
