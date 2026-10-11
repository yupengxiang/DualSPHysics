import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import ds_data02_runtime_v2 as base
import ds_data02_runtime_v6 as runner


GIB = 1024 ** 3


class UpstreamRuntimeTests(unittest.TestCase):
    def _f5_calibration_request(self, directory):
        directory = Path(directory)
        output_root = directory / 'gencase-002'
        generated_prefix = output_root / 'CasePistonBeach_REG'
        generated_prefix.mkdir(parents=True)
        receipt_path = output_root / 'execution-receipt.json'
        receipt = {
            'schema': 'ds02.execution-receipt.v1',
            'returncode': 0,
            'total_particles': 20732,
            'fluid_particles': 19456,
            'solver_dimension_from_gencase': 2,
            'output_root': str(output_root),
            'command': ['/usr/bin/python3', 'nas_preflight.py', str(generated_prefix)],
            'request': {
                'family_id': 'F5',
                'case_id': 'UF_F5_PISTON_REG',
                'kind': 'cpu',
                'cpu_task_kind': 'gencase',
                'reference_role': 'calibration_2d',
                'upstream_case_id': 'CasePistonBeach_REG',
                'command': [
                    '/usr/bin/python3',
                    'GenCase_linux64',
                    '{attempt_root}/CasePistonBeach_REG',
                ],
            },
        }
        receipt_path.write_text(json.dumps(receipt))
        return {
            'family_id': 'F5',
            'case_id': 'UF_F5_PISTON_REG',
            'attempt_id': 'solver-001',
            'kind': 'qualification',
            'command': [str(base.SOLVER), '-gpu', str(generated_prefix), '{attempt_root}'],
            'cwd': str(directory),
            'worktree_root': str(directory),
            'max_wall_seconds': 60,
            'cpu_threads': 1,
            'estimated_storage_bytes': 1024,
            'estimated_peak_gpu_mib': 100,
            'input_files': [str(receipt_path)],
            'gencase_receipt': str(receipt_path),
            'gencase_receipt_sha256': base.sha256(receipt_path),
            'reference_role': 'calibration_2d',
            'upstream_case_id': 'CasePistonBeach_REG',
        }

    def test_f5_2d_calibration_is_bound_to_receipt_and_generated_prefix(self):
        with tempfile.TemporaryDirectory() as directory:
            request = self._f5_calibration_request(directory)
            self.assertIn(request['gencase_receipt'], base.validate_request(request))

            for changes, message in [
                ({'kind': 'production'}, '3D'),
                ({'family_id': 'F1'}, '3D'),
                ({'reference_role': 'core'}, '3D'),
                ({'case_id': 'UF_OTHER'}, '3D'),
            ]:
                altered = copy.deepcopy(request)
                altered.update(changes)
                with self.assertRaisesRegex(ValueError, message):
                    base.validate_request(altered)

            altered = copy.deepcopy(request)
            altered['gencase_receipt_sha256'] = '0' * 64
            with self.assertRaisesRegex(ValueError, 'hash'):
                base.validate_request(altered)

            altered = copy.deepcopy(request)
            altered['input_files'] = []
            with self.assertRaisesRegex(ValueError, 'input_files'):
                base.validate_request(altered)

            altered = copy.deepcopy(request)
            altered['command'][2] = str(Path(directory) / 'gencase-002' / 'wrong-prefix')
            with self.assertRaisesRegex(ValueError, 'prefix'):
                base.validate_request(altered)

            altered = copy.deepcopy(request)
            receipt_path = Path(altered['gencase_receipt'])
            receipt = json.loads(receipt_path.read_text())
            receipt['solver_dimension_from_gencase'] = 3
            receipt_path.write_text(json.dumps(receipt))
            altered['gencase_receipt_sha256'] = base.sha256(receipt_path)
            with self.assertRaisesRegex(ValueError, 'actual 2D'):
                base.validate_request(altered)

    def test_nas_absent_fails_without_home_fallback(self):
        request = dict(family_id='F1', case_id='UF_TEST', attempt_id='one', output_storage='upstream_nas')
        with patch.object(Path, 'is_mount', return_value=False):
            with self.assertRaisesRegex(RuntimeError, 'no local fallback'):
                runner._output_path(request, Path('/tmp'))

    def test_concurrent_nas_reservations_reduce_admission_headroom(self):
        request = dict(output_storage='upstream_nas')
        reservation = dict(
            id='infra/UF_CURRENT/new',
            kind='cpu',
            cpu_task_kind='audit',
            cpu_threads=1,
            gpu_seconds=0,
            cpu_core_seconds=1,
            new_storage_bytes=10 * GIB,
            output_storage='upstream_nas',
        )
        ledger = dict(
            charges=[],
            reservations=[{
                'id': 'infra/UF_OLD/running',
                'kind': 'cpu',
                'cpu_task_kind': 'audit',
                'gpu_seconds': 0,
                'cpu_core_seconds': 1,
                'new_storage_bytes': 20 * GIB,
                'output_storage': 'upstream_nas',
            }],
            attempts=[],
        )
        with patch.object(runner, '_nas_available', return_value=31 * GIB):
            with self.assertRaisesRegex(RuntimeError, 'NAS headroom'):
                runner._check_upstream_batch(ledger, reservation, request)

    def test_external_scratch_is_rejected_except_historical_preflight(self):
        historical = {
            'family_id': 'infra',
            'case_id': 'UF_NAS_PREFLIGHT',
            'attempt_id': 'check-001',
            'kind': 'cpu',
            'cpu_task_kind': 'audit',
            'external_scratch': str(runner.HISTORICAL_EXTERNAL_SCRATCH),
        }
        runner._validate_storage_request(historical)

        rejected = dict(historical, attempt_id='future-001')
        with self.assertRaisesRegex(ValueError, 'external_scratch'):
            runner._validate_storage_request(rejected)

    def test_tmpdir_is_created_inside_attempt_root(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'attempt'
            tmpdir = runner._prepare_attempt_tmpdir(output, {'output_storage': 'home'})
            self.assertEqual(tmpdir, output / '.tmp')
            self.assertTrue(tmpdir.is_dir())
            self.assertTrue(tmpdir.is_relative_to(output))

    def test_terminal_measurement_flags_actual_upstream_batch_overrun(self):
        reservation = dict(
            id='infra/UF_CURRENT/new',
            kind='cpu',
            new_storage_bytes=1 * GIB,
        )
        ledger = {
            'charges': [{
                'id': 'infra/UF_OLD/done',
                'gpu_seconds': 0,
                'cpu_core_seconds': 0,
                'new_storage_bytes': 49 * GIB,
            }],
            'reservations': [],
        }
        overrun = runner._terminal_upstream_overrun(
            ledger,
            reservation,
            gpu_seconds=0,
            cpu_core_seconds=0,
            storage_bytes=2 * GIB,
        )
        self.assertEqual(overrun['new_storage_bytes']['used_before'], 49 * GIB)
        self.assertEqual(overrun['new_storage_bytes']['excess'], 1 * GIB)
        receipt = {'bytes': 2 * GIB, 'gpu_seconds': 0, 'status': 'completed'}
        self.assertIsNotNone(
            runner._apply_terminal_upstream_guard(ledger, reservation, receipt, 0)
        )
        self.assertEqual(receipt['status'], 'failed')
        self.assertIn('upstream_batch_overrun', receipt)

    def test_nas_loss_retains_conservative_reservation_and_local_control_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            reservation = {
                'id': 'infra/UF_CURRENT/lost',
                'kind': 'cpu',
                'new_storage_bytes': 2 * GIB,
                'output_storage': 'upstream_nas',
            }
            ledger = {
                'charges': [{
                    'id': 'infra/UF_OLD/done',
                    'new_storage_bytes': 45 * GIB,
                }],
                'reservations': [reservation.copy()],
            }
            conservative = runner._retain_unresolved_nas_reservation(
                ledger, reservation, RuntimeError('mount disappeared')
            )
            self.assertEqual(conservative, 5 * GIB)
            self.assertEqual(ledger['reservations'][0]['new_storage_bytes'], 5 * GIB)
            self.assertTrue(ledger['reservations'][0]['storage_unresolved'])

            output = Path('/data/nas/jade/Simulation/DualSPHysics/upstream-first/runs/infra/UF_CURRENT/lost')
            control_path = runner._write_unresolved_control_receipt(
                Path(directory), reservation['id'], output, reservation,
                RuntimeError('mount disappeared'),
            )
            self.assertTrue(control_path.is_file())
            control = json.loads(control_path.read_text())
            self.assertTrue(control['nas_write_skipped'])
            self.assertTrue(control['storage']['reservation_retained'])
            self.assertEqual(control['storage']['conservative_reservation_bytes'], 5 * GIB)

    def test_batch_guard_counts_old_attempts_and_charges(self):
        request = dict(output_storage='home')
        reservation = dict(id='F1/UF_TEST/new', kind='qualification', cpu_threads=1,
                           gpu_seconds=1, cpu_core_seconds=1, new_storage_bytes=1)
        ledger = dict(charges=[dict(id='F1/UF_TEST/old', gpu_seconds=24 * 3600)],
                      reservations=[], attempts=[])
        with self.assertRaisesRegex(RuntimeError, 'gpu_seconds'):
            runner._check_upstream_batch(ledger, reservation, request)
        ledger['charges'] = []
        ledger['reservations'] = [dict(id='F2/foreign/running', kind='cpu', cpu_task_kind='conversion')]
        with self.assertRaisesRegex(RuntimeError, 'occupied'):
            runner._check_upstream_batch(ledger, reservation, request)
        ledger['reservations'] = []
        ledger['attempts'] = [
            dict(id=f'F1/UF_TEST/failed-{i}', kind='qualification', status='failed')
            for i in range(24)
        ]
        with self.assertRaisesRegex(RuntimeError, 'attempt cap'):
            runner._check_upstream_batch(ledger, reservation, request)


if __name__ == '__main__':
    unittest.main()
