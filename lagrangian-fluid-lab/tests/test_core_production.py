from collections import Counter
import pytest
from scripts.core_production import register_scope,next_batch


def test_eight_then_twenty_four_requires_full_audits_and_keeps_failed_denominator():
    design=register_scope('F4','drop-x','q',0,1,[0,.25,.5,.75,1])
    assert Counter(r['split'] for r in design['cases'])=={'train':16,'validation':4,'id_test':6,'ood_test':6}
    qualification={'family':'F4','scope_id':'drop-x','T1_numerical':True,'matrix_complete':True}
    first=next_batch(design,qualification,{})['ready'];assert len(first)==8
    audits={key:{'schema':'core.case_audit.v1','case_id':key,'hard_integrity_pass':True,'full_temporal_scan':True,'full_particle_axis':True} for key in first}
    assert len(next_batch(design,qualification,audits)['ready'])==24
    audits[first[0]]['hard_integrity_pass']=False
    failed=next_batch(design,qualification,audits)
    assert failed['status']=='scope_review_required' and not failed['ready'] and len(failed['missing'])==24


def test_qualification_collision_and_wrong_scope_cannot_enter_training():
    with pytest.raises(ValueError,match='collision'):
        register_scope('F1','obstacle','q',0,1,[.5/32])
    design=register_scope('F1','obstacle','q',0,1,[0,1])
    assert next_batch(design,{'family':'F1','scope_id':'obstacle'}, {})['status']=='awaiting_T1'
    with pytest.raises(ValueError,match='another scope'):
        next_batch(design,{'family':'F3','scope_id':'obstacle','T1_numerical':True},{})
