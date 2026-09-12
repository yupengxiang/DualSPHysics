import json
from pathlib import Path
import pytest
from scripts import l1r_continuation_evidence as evidence
from scripts import f3_training_runner as training


def test_training_failed_and_running_reserves_apply_to_cfd_budget(tmp_path,monkeypatch):
    out=tmp_path/'campaigns/l1-resume/continuation';out.mkdir(parents=True)
    monkeypatch.setattr(evidence,'LAB',tmp_path);monkeypatch.setattr(evidence,'OUT',out)
    limits=dict(qualification=72,development=40,training=12,gpu_hours=2,cpu_core_hours=768,materials=32,storage_gib=512)
    (out/'RESOURCE-LIMITS.json').write_text(json.dumps({'limits':limits}))
    (out/'HISTORICAL-CPU-RESERVE.json').write_text(json.dumps({'cpu_core_hours_conservative_reserve':10.}))
    (out/'RESOURCE-ACTIVE-WINDOWS.json').write_text('[]')
    for index,status in enumerate(('completed','failed','running')):
        execution=f'execution{index}';suffix='partial' if status=='running' else ('complete' if status=='completed' else 'failed')
        p=tmp_path/'campaigns/l1-resume/training-attempts/model'/f'{execution}.{suffix}'/'attempt.json'
        p.parent.mkdir(parents=True)
        record=dict(schema=training.ATTEMPT_SCHEMA,resource_category='training',logical_run_id='model',execution_attempt_id=execution,
                    timeout_seconds=3600,cpu_cores=1,gpu_index=4,gpu_uuid='GPU-test',status=status,
                    elapsed_seconds=None if status=='running' else 1800,**training._reservation(3600,1))
        p.write_text(json.dumps(record))
    evidence.ledger();actual=json.loads((out/'RESOURCE-LEDGER.json').read_text())
    assert actual['qualification_attempts_used']==actual['development_attempts_used']==0
    assert actual['training_attempts_used']==3 and actual['training_attempts_remaining']==9
    assert actual['gpu_solver_hours']==actual['gpu_solver_budget_charge_hours']==0
    assert actual['gpu_budget_charge_hours']==pytest.approx(1+3605/3600)
    assert actual['cpu_base_core_hours_upper_bound']==10
    assert actual['cpu_core_hours_upper_bound']==pytest.approx(10+(3600+3605)*2.2/3600)
    assert actual['shared_training_accounting_version']==training.ACCOUNTING_VERSION
    with pytest.raises(RuntimeError,match='budget'):
        evidence.check_budget(category='qualification')
    with pytest.raises(RuntimeError,match='budget'):
        evidence.check_budget(category='development')
