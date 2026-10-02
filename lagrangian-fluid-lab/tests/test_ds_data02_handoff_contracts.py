import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from ds_data02_handoff_contracts import UNITS, validate_closed_evidence


class FiniteCohortMetadataTests(unittest.TestCase):
    def evidence(self):
        return {'lifecycle': dict(full_timeline_checked=True, missing_at_any_later_frame_count=0,
                                  introduced_after_initial_count=0, revived_identity_count=0,
                                  type_changed_identity_count=0), 'structural_failures': [],
                'solver_log': {'counts': {'excluded_particles': 0}}}

    def test_native_missing_ids_cannot_be_hidden_by_closed_metadata(self):
        r = self.evidence()
        r['lifecycle']['missing_at_any_later_frame_count'] = 3433
        with self.assertRaisesRegex(ValueError, 'exclusion ledger'):
            validate_closed_evidence(r, {'units': UNITS})

    def test_missing_solver_exclusion_count_is_not_assumed_zero(self):
        r = self.evidence()
        r['solver_log']['counts'].clear()
        with self.assertRaisesRegex(ValueError, 'exclusions'):
            validate_closed_evidence(r, {'units': UNITS})

    def test_units_must_have_explicit_si_evidence(self):
        with self.assertRaisesRegex(ValueError, 'SI'):
            validate_closed_evidence(self.evidence(), {'units': {}})

    def test_zero_loss_full_timeline_can_receive_source_contract(self):
        validate_closed_evidence(self.evidence(), {'units': UNITS})
