import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('runtime_v2', Path(__file__).resolve().parents[1] / 'scripts/ds_data02_runtime_v2.py')
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


class LiveStoragePolicyTests(unittest.TestCase):
    def setUp(self):
        self.ledger = dict(deadline_utc='2099-01-01T00:00:00+00:00', attempts=[], charges=[],
                           reservations=[dict(id='other', kind='cpu', new_storage_bytes=100,
                                              cpu_threads=1, cpu_core_seconds=0, gpu_seconds=0)],
                           limits=dict(gpu_seconds=1000, cpu_core_seconds=1000, new_storage_bytes=1,
                                       storage_policy='home_free_floor', home_min_free_bytes=500))
        self.reservation = dict(id='new', kind='cpu', cpu_threads=1, new_storage_bytes=200,
                                gpu_seconds=0, cpu_core_seconds=10)

    def test_current_availability_accounts_for_other_reservations(self):
        with self.assertRaisesRegex(RuntimeError, 'floor'):
            runtime.check_reservation(self.ledger, self.reservation, 999999, available_bytes=799)
        runtime.check_reservation(self.ledger, self.reservation, 999999, available_bytes=800)

    def test_missing_live_availability_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, 'availability'):
            runtime.check_reservation(self.ledger, self.reservation, 0)

    def test_cpu_budget_remains_enforced(self):
        self.reservation['cpu_core_seconds'] = 1001
        with self.assertRaisesRegex(RuntimeError, 'cpu_core_seconds'):
            runtime.check_reservation(self.ledger, self.reservation, 0, available_bytes=999999)

    def test_old_namespace_policy_remains_supported(self):
        self.ledger['limits'].pop('storage_policy')
        with self.assertRaisesRegex(RuntimeError, 'storage budget'):
            runtime.check_reservation(self.ledger, self.reservation, 2, available_bytes=999999)
