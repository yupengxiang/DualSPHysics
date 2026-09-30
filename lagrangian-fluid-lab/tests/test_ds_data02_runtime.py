import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import ds_data02_runtime as runtime


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.ledger = dict(deadline_utc='2026-10-14T07:23:48+00:00',
                           limits=dict(gpu_seconds=100, cpu_core_seconds=200, new_storage_bytes=1000,
                                       qualification_attempts=2, production_attempts=3),
                           charges=[], reservations=[], attempts=[])
        self.request = dict(id='F1/case/a1', kind='qualification', gpu_seconds=20,
                            cpu_core_seconds=40, new_storage_bytes=100, cpu_threads=2)

    def check(self, **kwargs):
        runtime.check_reservation(self.ledger, self.request, 10,
                                  current_time=datetime(2026, 9, 30, tzinfo=timezone.utc), **kwargs)

    def test_reservations_cannot_oversubscribe_parent_budget(self):
        self.ledger['reservations'] = [dict(id='other', gpu_seconds=90)]
        with self.assertRaisesRegex(RuntimeError, 'gpu_seconds'):
            self.check()

    def test_failed_attempts_remain_in_attempt_cap(self):
        self.ledger['attempts'] = [dict(id=str(i), kind='qualification', status='failed') for i in range(2)]
        with self.assertRaisesRegex(RuntimeError, 'attempt cap'):
            self.check()

    def test_production_uses_its_own_attempt_cap_and_full_gpu_reservation(self):
        self.request['kind'] = 'production'
        self.ledger['attempts'] = [dict(id=str(i), kind='qualification', status='failed') for i in range(2)]
        self.check()
        self.ledger['attempts'] = [dict(id=str(i), kind='production', status='completed') for i in range(3)]
        with self.assertRaisesRegex(RuntimeError, 'production'):
            self.check()
        self.ledger['attempts'] = []
        self.ledger['charges'] = [dict(id='existing', gpu_seconds=90)]
        with self.assertRaisesRegex(RuntimeError, 'gpu_seconds'):
            self.check()

    def test_existing_attempt_cannot_be_reused(self):
        self.ledger['attempts'] = [dict(id=self.request['id'], kind='qualification', status='failed')]
        with self.assertRaisesRegex(RuntimeError, 'already registered'):
            self.check()

    def test_expiry_and_disk_reservation_are_hard_limits(self):
        with self.assertRaisesRegex(RuntimeError, 'deadline'):
            runtime.check_reservation(self.ledger, self.request, 10,
                                      current_time=datetime(2026, 10, 15, tzinfo=timezone.utc))
        with self.assertRaisesRegex(RuntimeError, 'storage'):
            runtime.check_reservation(self.ledger, self.request, 950,
                                      current_time=datetime(2026, 9, 30, tzinfo=timezone.utc))

    def test_gpu_uuid_lease_and_foreign_processes_exclude_devices(self):
        devices = [dict(index=i, uuid=f'uuid{i}', total_mib=49000, used_mib=15) for i in range(8)]
        snapshot = dict(devices=devices, processes=[dict(uuid='uuid4', pid=99)])
        chosen = runtime.choose_gpu(snapshot, {'uuid5'}, 1000)
        self.assertEqual(chosen['uuid'], 'uuid6')
        with self.assertRaisesRegex(RuntimeError, 'no eligible'):
            runtime.choose_gpu(snapshot, {f'uuid{i}' for i in range(1, 8)}, 1000)

    def test_large_gpu_peak_and_nonidle_device_are_rejected(self):
        snapshot = dict(devices=[dict(index=5, uuid='five', total_mib=1000, used_mib=15)], processes=[])
        with self.assertRaises(RuntimeError):
            runtime.choose_gpu(snapshot, set(), 1000)
        snapshot['devices'][0].update(total_mib=49000, used_mib=300)
        with self.assertRaises(RuntimeError):
            runtime.choose_gpu(snapshot, set(), 1000)

    def test_leased_uuid_is_the_only_visible_cuda_device(self):
        env = {'CUDA_VISIBLE_DEVICES': '0,1,2,3'}
        command = runtime.bind_gpu_visibility(['solver', '-gpu:5', 'input', 'output'], env,
                                             dict(index=5, uuid='GPU-leased'))
        self.assertEqual(command, ['solver', '-gpu:0', 'input', 'output'])
        self.assertEqual(env['CUDA_VISIBLE_DEVICES'], 'GPU-leased')

    def test_gencase_actual_counts_and_dimensions(self):
        text = 'Data2D=[1]\nFluid....: 12,957,384 id:(1-2)\nTotal particles: 15,027,060 (bound=2)'
        self.assertEqual(runtime.parse_gencase_output(text),
                         dict(total_particles=15027060, fluid_particles=12957384, solver_dimension_from_gencase=2))

    def test_atomic_ledger_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime.atomic_json(root / 'runtime/resource-ledger.json', self.ledger)
            with runtime.ledger_locked(root) as ledger:
                ledger['charges'].append(dict(id='cpu', cpu_core_seconds=3))
            self.assertEqual(json.loads((root / 'runtime/resource-ledger.json').read_text())['charges'][0]['cpu_core_seconds'], 3)

    def test_successful_gencase_with_no_fluid_cannot_launch_solver(self):
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / 'receipt.json'
            request = dict(family_id='F1', case_id='ref', attempt_id='solver-1',
                           kind='qualification', command=[str(runtime.SOLVER)], cwd=directory,
                           worktree_root=directory, max_wall_seconds=30, cpu_threads=1,
                           estimated_storage_bytes=100, estimated_peak_gpu_mib=100,
                           gencase_receipt=str(receipt), input_files=[str(receipt)])
            preflight = dict(returncode=0, total_particles=100, fluid_particles=0,
                             solver_dimension_from_gencase=3)
            receipt.write_text(json.dumps(preflight))
            with self.assertRaisesRegex(ValueError, 'positive actual fluid'):
                runtime.validate_request(request)
            preflight.update(fluid_particles=20, solver_dimension_from_gencase=2)
            receipt.write_text(json.dumps(preflight))
            with self.assertRaisesRegex(ValueError, 'actual 3D'):
                runtime.validate_request(request)
            preflight['solver_dimension_from_gencase'] = 3
            receipt.write_text(json.dumps(preflight))
            self.assertIn(str(receipt), runtime.validate_request(request))
            request['gencase_receipt_sha256'] = 'invalid'
            with self.assertRaisesRegex(ValueError, 'receipt hash'):
                runtime.validate_request(request)


if __name__ == '__main__':
    unittest.main()
