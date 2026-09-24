#!/usr/bin/env python3
"""Coordinator-only, restartable F4 qualification → first 8 → remaining 24.

Workers never call this module. Each tick rebuilds the proposal from actual
qualification and worker evidence. An advisory lock protects concurrent ticks;
the runtime's idempotent transaction protects each submission across crashes.
"""
from __future__ import annotations

import argparse
import fcntl
import json
from pathlib import Path
import sys
import time
from typing import Any, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.core_runtime import Store, atomic_json, digest, freeze_job
from scripts.core_production_runner import (
    VerificationError, build_proposal, inspect_qualification_matrix,
    production_design, load_production_audits, core_cfd,
)


def reference(path):
    return {"path": str(Path(path).resolve()), "sha256": digest(Path(path))}


def _qualification_t1_claim(receipt: Mapping[str, Any]) -> bool:
    """Read the T1 marker only after the versioned qualification schema."""
    if not isinstance(receipt, Mapping):
        raise VerificationError("qualification receipt object required")
    schema = receipt.get("schema")
    if type(schema) is not str or schema != "core.qualification.v1":
        raise VerificationError("qualification receipt schema mismatch")
    return receipt.get("T1_numerical") is True


def collect_audits(jobs, design, output):
    """Collect terminal evidence, retaining infrastructure failures separately."""
    cases = {row['case_id'] for row in design['cases']}
    rows, failures = {}, []
    selected = [j for j in jobs if j['spec'].get('scope_id') == design['scope_id']
                and j['spec'].get('attempt_role') == 'production']
    for job in selected:
        case = job['spec'].get('prepared_case_id')
        if case not in cases:
            raise VerificationError('runtime production case outside registered denominator')
        if job['status'] in ('failed', 'cancelled'):
            failures.append({'job_id': job['job_id'], 'case_id': case, 'status': job['status']})
        if job['status'] != 'succeeded':
            continue
        if case in rows:
            raise VerificationError('multiple completed production jobs for one physical case')
        attempt = Path(job['attempt_dir'])
        execution = attempt / 'result.json'
        if json.loads(execution.read_text()) != job['result']:
            raise VerificationError('worker receipt differs from finalized ledger receipt')
        rows[case] = {'case_id': case, 'execution': reference(execution),
                      **{name: reference(attempt/'product'/filename) for name, filename in (
                          ('prepared', 'prepared.json'), ('audit', 'audit.json'),
                          ('trajectory', 'trajectory.h5'))}}
    atomic_json(output, {'schema': 'core.production_audit_manifest.v1',
                         'family': design['family'], 'scope_id': design['scope_id'],
                         'audits': rows, 'execution_failures': failures})
    # This verifies the execution's artifact bindings and native scientific gates.
    load_production_audits(output, design=design)
    return failures, selected


def submit_batch(proposal, store, lab, runtime_root, state_root):
    """Only submit a freshly rebuilt admissible batch; reuse frozen requests."""
    decision = proposal['batch_decision']
    if decision['status'] not in ('first_8', 'remaining_24'):
        return []
    batch = proposal.get('prepared_batch') or {}
    if batch.get('status') != decision['status'] or set(batch.get('ready', [])) != set(decision['ready']):
        raise VerificationError('prepared batch does not match verified admission')
    if len(batch.get('jobs', [])) != len(decision['ready']):
        raise VerificationError('prepared job denominator differs from admitted cases')
    requests = state_root / 'requests'; requests.mkdir(parents=True, exist_ok=True)
    registered = {j['job_id']: j for j in store.jobs()}
    state_path = state_root / 'source-snapshot.json'
    snapshot = json.loads(state_path.read_text()) if state_path.exists() else None
    qualified_snapshot = proposal.get('execution_source_snapshot')
    if not isinstance(qualified_snapshot, dict):
        raise VerificationError('production needs the qualified execution source snapshot')
    if snapshot is not None and snapshot != qualified_snapshot:
        raise VerificationError('production source differs from qualified execution source')
    snapshot = qualified_snapshot
    if not state_path.exists():
        atomic_json(state_path, snapshot)
    submitted = []
    for row in batch['jobs']:
        proposal_path = Path(row['path'])
        if digest(proposal_path) != row['sha256']:
            raise VerificationError('production job proposal hash changed')
        spec = json.loads(proposal_path.read_text())
        if spec.get('prepared_case_id') not in decision['ready']:
            raise VerificationError('prepared job case is outside admitted batch')
        saved = requests / (spec['job_id'] + '.json')
        if saved.exists():
            frozen = json.loads(saved.read_text())
            if frozen['input_files'] != spec['input_files']:
                raise VerificationError('production inputs changed after submission')
            for field in ('qualification_receipt_sha256', 'production_design_sha256',
                          'scope_id', 'split', 'prepared_case_id'):
                if frozen.get(field) != spec.get(field):
                    raise VerificationError('production registration changed after submission')
        else:
            if spec['job_id'] in registered:
                raise VerificationError('existing production job lacks coordinator request receipt')
            spec['source_snapshot'] = snapshot
            frozen = freeze_job(spec, lab, runtime_root)
            atomic_json(saved, frozen)
        # Revalidate the pinned snapshot even when resuming a prepared request.
        frozen = freeze_job(frozen, lab, runtime_root)
        if store.submit(frozen):
            submitted.append(frozen['job_id'])
    return submitted


def tick(*, lab, runtime_root, matrix_root, qualification_job, state_root):
    state_root = Path(state_root).resolve(); state_root.mkdir(parents=True, exist_ok=True)
    with (state_root/'coordinator.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        store = Store(runtime_root); jobs = store.jobs()
        gate = next((j for j in jobs if j['job_id'] == qualification_job), None)
        status = {'schema': 'core.production_dispatch.v1', 'time': time.time(),
                  'qualification_job': qualification_job, 'submitted': [],
                  'registered_denominator': 32}
        if gate is None or gate['status'] != 'succeeded':
            status.update(status=('qualification_execution_review_required'
                          if gate and gate['status'] in ('failed', 'cancelled')
                          else 'awaiting_qualification_execution'),
                          gate_status=gate['status'] if gate else 'missing')
        else:
            qualification = Path(gate['attempt_dir'])/'qualification.json'
            expected = [x for x in gate['result']['outputs'] if x['path'] == 'qualification.json']
            if len(expected) != 1 or digest(qualification) != expected[0]['sha256']:
                raise VerificationError('qualification execution output is unbound or changed')
            design = production_design(inspect_qualification_matrix(matrix_root))
            production = [j for j in jobs if j['spec'].get('scope_id') == design['scope_id']
                          and j['spec'].get('attempt_role') == 'production']
            case_ids = {j['spec'].get('prepared_case_id') for j in production}
            first = {row['case_id'] for row in design['cases'] if row['first_batch']}
            # Avoid repeatedly hashing already completed multi-GB trajectories
            # while the same fully submitted batch is still executing.
            if (len(production) == len(case_ids) and len(case_ids) in (8, 32)
                    and first <= case_ids
                    and any(j['status'] in ('queued', 'running') for j in production)
                    and not any(j['status'] in ('failed', 'cancelled') for j in production)):
                status.update(status='awaiting_production_execution',
                              submitted_case_count=len(case_ids))
                atomic_json(state_root/'status.json', status)
                return status
            audits_path = state_root/'audits.json'
            failures, _ = collect_audits(jobs, design, audits_path)
            if failures:
                status.update(status='infrastructure_review_required', failures=failures)
            else:
                qualified_source = gate['result'].get('source_snapshot')
                if _qualification_t1_claim(json.loads(qualification.read_text())):
                    if (not qualified_source or
                            digest(Path(qualified_source['path'])/'scripts/core_cfd.py')
                            != digest(Path(core_cfd.__file__))):
                        raise VerificationError('CFD preparation code differs from qualified source')
                    budget_path = state_root/'resource-registration.json'
                    if not budget_path.exists():
                        raise VerificationError('measured production resource registration required')
                    budget = json.loads(budget_path.read_text())
                    measurement = budget.get('measurement', {})
                    if (budget.get('scope_id') != design['scope_id']
                            or budget.get('planned_cases') != 32
                            or not measurement.get('path')
                            or digest(Path(measurement['path'])) != measurement.get('sha256')
                            or not all(budget.get(k) for k in (
                                'estimated_process_gpu_hours', 'archive_space_gib',
                                'estimated_critical_path_hours'))):
                        raise VerificationError('production milestone resource evidence incomplete')
                proposal = build_proposal(matrix_root=matrix_root, lab_root=lab,
                    output=state_root/'proposal.json', qualification_path=qualification,
                    audits_path=audits_path, prepared_root=state_root/'prepared')
                status['status'] = proposal['batch_decision']['status']
                if status['status'] in ('first_8', 'remaining_24'):
                    proposal['execution_source_snapshot'] = qualified_source
                    atomic_json(state_root/'proposal.json', proposal)
                status['submitted'] = submit_batch(proposal, store, lab, runtime_root, state_root)
                status['batch_decision'] = proposal['batch_decision']
        atomic_json(state_root/'status.json', status)
        return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('lab', 'runtime-root', 'matrix-root', 'state-root'):
        parser.add_argument('--'+name, required=True, type=Path)
    parser.add_argument('--qualification-job', required=True)
    parser.add_argument('--watch', action='store_true')
    parser.add_argument('--poll-seconds', type=float, default=30.)
    args = parser.parse_args()
    options = vars(args).copy(); watch = options.pop('watch'); interval = options.pop('poll_seconds')
    if not watch:
        print(json.dumps(tick(**options), indent=2)); return
    if interval < 5:
        parser.error('poll interval must be at least five seconds')
    args.state_root.mkdir(parents=True, exist_ok=True)
    with (args.state_root/'watcher.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        scope = json.loads((args.matrix_root/'design.json').read_text())['scope_id']
        previous = None
        while True:
            store = Store(args.runtime_root)
            relevant = [j for j in store.jobs() if j['job_id'] == args.qualification_job
                        or j['spec'].get('scope_id') == scope]
            store.db.close()
            fingerprint = [(j['job_id'], j['status'], j['attempt_id']) for j in relevant]
            if fingerprint != previous:
                try:
                    result = tick(**options)
                except Exception as exc:
                    atomic_json(args.state_root/'status.json', {
                        'schema': 'core.production_dispatch.v1', 'time': time.time(),
                        'status': 'controller_error', 'submitted': [],
                        'error': repr(exc), 'completion_claim': False,
                        'note': 'ledger retains any submissions preceding this exception'})
                    raise
                print(json.dumps(result), flush=True)
                if result['status'] in ('complete_32', 'scope_review_required',
                                        'infrastructure_review_required',
                                        'qualification_execution_review_required'):
                    return
                previous = fingerprint
            time.sleep(interval)


if __name__ == '__main__':
    main()
