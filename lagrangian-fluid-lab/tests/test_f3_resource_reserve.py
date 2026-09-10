import json
from scripts import l1r_continuation_evidence as evidence


def test_inflight_timeout_is_reserved_without_fabricating_elapsed_time(tmp_path,monkeypatch):
    out=tmp_path/'campaigns/l1-resume/continuation';out.mkdir(parents=True)
    monkeypatch.setattr(evidence,'LAB',tmp_path);monkeypatch.setattr(evidence,'OUT',out)
    (out/'HISTORICAL-CPU-RESERVE.json').write_text(json.dumps({'cpu_core_hours_conservative_reserve':1.}))
    (out/'RESOURCE-ACTIVE-WINDOWS.json').write_text('[]')
    (out/'RESOURCE-LIMITS.json').write_text(json.dumps({'limits':{'qualification':56,'gpu_hours':64,'cpu_core_hours':768,'materials':32}}))
    attempt=tmp_path/'campaigns/l1-resume/runs/case/attempt.json';attempt.parent.mkdir(parents=True)
    row={'case_id':'case','attempt_id':'known','status':'running','command':['solver','-gpu:4'],'timeout_seconds':1800}
    attempt.write_text(json.dumps(row));evidence.ledger()
    report=json.loads((out/'RESOURCE-LEDGER.json').read_text())
    assert report['gpu_budget_charge_hours']==.5
    assert report['gpu_solver_hours']==0
    assert report['attempts'][0]['elapsed_seconds'] is None
    assert report['gpu_unbounded_attempts']==0
    assert report['qualification_attempts_remaining']==55
    del row['timeout_seconds'];attempt.write_text(json.dumps(row));evidence.ledger()
    report=json.loads((out/'RESOURCE-LEDGER.json').read_text())
    assert report['gpu_unbounded_attempts']==1


def test_material_calibration_and_incomplete_work_share_budget(tmp_path,monkeypatch):
    import json
    from scripts import l1r_continuation_evidence as evidence
    monkeypatch.setattr(evidence,'OUT',tmp_path)
    for name,status,charge in [('ENGINEERING-s2','completed',1),('AFFINE-CALIBRATION','failed',4),('AFFINE-CALIBRATION-contact-v2','running',4)]:
        (tmp_path/f'F3-MATERIAL-{name}.json').write_text(json.dumps({'status':status,'configuration_charge':charge}))
    (tmp_path/'F3-MATERIAL-COMPARISON.json').write_text(json.dumps({'status':'completed'}))
    assert evidence.material_usage()==9
