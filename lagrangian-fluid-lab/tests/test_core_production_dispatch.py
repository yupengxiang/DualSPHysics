import json
from pathlib import Path

import pytest

from scripts.core_production_dispatch import _qualification_t1_claim, submit_batch, tick
from scripts.core_production_runner import VerificationError
from scripts.core_runtime import Store, atomic_json, digest, snapshot_code


def test_synthetic_qualification_rejected_before_dispatch_t1_claim():
    class SchemaReadProbe(dict):
        reads = []

        def get(self, key, default=None):
            self.reads.append(key)
            if key != 'schema':
                raise AssertionError(f'qualification field read before schema rejection: {key}')
            return super().get(key, default)

    receipt = SchemaReadProbe({
        'schema': 'core.f8.synthetic_diagnostic.v1',
        'T1_numerical': True,
    })
    with pytest.raises(VerificationError, match='qualification receipt schema mismatch'):
        _qualification_t1_claim(receipt)
    assert receipt.reads == ['schema']


def test_dispatch_t1_claim_accepts_only_versioned_qualification():
    assert _qualification_t1_claim({
        'schema': 'core.qualification.v1', 'T1_numerical': True,
    }) is True
    assert _qualification_t1_claim({
        'schema': 'core.qualification.v1', 'T1_numerical': False,
    }) is False


def test_pending_gate_never_prepares_or_submits(tmp_path):
    runtime = tmp_path/'runtime'
    status = tick(lab=tmp_path, runtime_root=runtime, matrix_root=tmp_path/'absent',
                  qualification_job='gate', state_root=tmp_path/'dispatch')
    assert status['status'] == 'awaiting_qualification_execution'
    assert status['submitted'] == []
    assert Store(runtime).jobs() == []


def test_restart_after_partial_submission_reuses_immutable_requests(tmp_path):
    lab = tmp_path/'lab'; (lab/'scripts').mkdir(parents=True)
    script = lab/'scripts/core_fake.py'; script.write_text('print("fixture")\n')
    runtime = tmp_path/'runtime'; store = Store(runtime)
    state = tmp_path/'dispatch'; state.mkdir()
    cases = ['case0', 'case1']; jobs = []
    for index, case in enumerate(cases):
        source = tmp_path/f'input{index}'; source.write_text(case)
        spec = {'job_id': f'production-{index}', 'host': 'ada', 'cwd': str(lab),
                'argv': ['/usr/bin/python3', str(script)],
                'resources': {'cpu_cores': 1, 'ram_mib': 128, 'gpu_peak_mib': 0, 'io_weight': .1},
                'timeout_seconds': 60, 'required_outputs': [], 'depends_on': [],
                'input_files': [{'path': str(source), 'sha256': digest(source)}],
                'prepared_case_id': case, 'scope_id': 'scope', 'split': 'train',
                'qualification_receipt_sha256': 'q', 'production_design_sha256': 'd'}
        path = tmp_path/f'spec{index}.json'; atomic_json(path, spec)
        jobs.append({'job_id': spec['job_id'], 'path': str(path), 'sha256': digest(path)})
    proposal = {'batch_decision': {'status': 'first_8', 'ready': cases},
                'prepared_batch': {'status': 'first_8', 'ready': cases, 'jobs': jobs}}
    snapshot, sha = snapshot_code(lab, runtime)
    proposal['execution_source_snapshot'] = {'path': str(snapshot), 'sha256': sha}
    class InterruptedStore:
        def jobs(self): return store.jobs()
        def submit(self, spec):
            if spec['job_id'] == 'production-1': raise RuntimeError('coordinator interrupted')
            return store.submit(spec)
    with pytest.raises(RuntimeError, match='interrupted'):
        submit_batch(proposal, InterruptedStore(), lab, runtime, state)
    assert len(store.jobs()) == 1
    old_snapshot = store.jobs()[0]['spec']['source_snapshot']
    script.write_text('print("later development must not affect this scope")\n')
    assert submit_batch(proposal, store, lab, runtime, state) == ['production-1']
    assert submit_batch(proposal, store, lab, runtime, state) == []
    assert len(store.jobs()) == 2
    assert all(job['spec']['source_snapshot'] == old_snapshot for job in store.jobs())
    # Reusing a case/job ID with newly registered inputs must fail, not silently
    # accept the old receipt or create another physical-case execution.
    spec = json.loads(Path(jobs[1]['path']).read_text())
    spec['input_files'][0]['sha256'] = '0'*64
    atomic_json(Path(jobs[1]['path']), spec)
    jobs[1]['sha256'] = digest(Path(jobs[1]['path']))
    with pytest.raises(VerificationError, match='inputs changed'):
        submit_batch(proposal, store, lab, runtime, state)


def test_negative_qualification_never_submits_even_with_prepared_jobs(tmp_path):
    store = Store(tmp_path/'runtime')
    result = submit_batch({'batch_decision': {'status': 'scope_review_required'},
                           'prepared_batch': {'jobs': ['must not read']}},
                          store, tmp_path, tmp_path/'runtime', tmp_path)
    assert result == [] and store.jobs() == []
