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


class UpstreamRuntimeTests(unittest.TestCase):
    def test_2d_calibration_does_not_admit_2d_production_or_other_cases(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'preflight.json'
            path.write_text(json.dumps(dict(returncode=0, total_particles=100,
                fluid_particles=80, solver_dimension_from_gencase=2)))
            request = dict(family_id='F5', case_id='UF_F5_PISTON_REG', attempt_id='solver-001',
                kind='qualification', reference_role='calibration_2d', upstream_case_id='CasePistonBeach_REG',
                command=[str(base.SOLVER)], cwd=directory, worktree_root=directory,
                max_wall_seconds=60, cpu_threads=1, estimated_storage_bytes=1024,
                estimated_peak_gpu_mib=100, input_files=[str(path)], gencase_receipt=str(path))
            self.assertIn(str(path), base.validate_request(request))
            self.assertEqual(json.loads(path.read_text())['solver_dimension_from_gencase'], 2)
            for changes in [dict(kind='production'), dict(family_id='F1'),
                            dict(reference_role='core'), dict(case_id='other')]:
                altered = copy.deepcopy(request); altered.update(changes)
                with self.assertRaisesRegex(ValueError, '3D'):
                    base.validate_request(altered)

    def test_nas_absent_fails_without_home_fallback(self):
        request = dict(family_id='F1',case_id='UF_TEST',attempt_id='one',output_storage='upstream_nas')
        with patch.object(Path, 'is_mount', return_value=False):
            with self.assertRaisesRegex(RuntimeError, 'no local fallback'):
                runner._output_path(request, Path('/tmp'))

    def test_batch_guard_counts_old_attempts_and_charges(self):
        request = dict(output_storage='home')
        reservation = dict(id='F1/UF_TEST/new',kind='qualification',cpu_threads=1,
                           gpu_seconds=1,cpu_core_seconds=1,new_storage_bytes=1)
        ledger = dict(charges=[dict(id='F1/UF_TEST/old',gpu_seconds=24*3600)],
                      reservations=[], attempts=[])
        with self.assertRaisesRegex(RuntimeError, 'gpu_seconds'):
            runner._check_upstream_batch(ledger,reservation,request)
        ledger['charges']=[]
        ledger['reservations']=[dict(id='F2/foreign/running',kind='cpu',cpu_task_kind='conversion')]
        with self.assertRaisesRegex(RuntimeError, 'occupied'):
            runner._check_upstream_batch(ledger,reservation,request)
        ledger['reservations']=[]
        ledger['attempts']=[dict(id=f'F1/UF_TEST/failed-{i}',kind='qualification',status='failed') for i in range(24)]
        with self.assertRaisesRegex(RuntimeError, 'attempt cap'):
            runner._check_upstream_batch(ledger,reservation,request)


if __name__ == '__main__':
    unittest.main()
