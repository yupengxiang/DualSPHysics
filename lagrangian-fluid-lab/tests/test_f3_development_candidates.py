import copy
import numpy as np
import pytest
from scripts.f3_development_candidates import candidates,validate,semantic_hash


def rows():
    result=candidates()
    for r in result:
        r['effective_control_sha256']=str(r['index'])
        r['physical_lineage_sha256']='lineage-'+str(r['index'])
    return result


def test_public_roles_and_pilot_cover_interpolation_and_extrapolation():
    records=rows();summary=validate(records)
    assert summary['physical_cases']==32 and summary['pilot_cases']==8
    pilot=[r for r in records if r['pilot']]
    assert {r['split'] for r in pilot}=={'train','validation','test'}
    assert summary['train_amplitude_support']==pytest.approx([.940625,1.059375])


def test_duplicate_control_cannot_be_relabelled_as_new_case():
    records=rows();records[0]['effective_control_sha256']=records[6]['effective_control_sha256']
    with pytest.raises(ValueError,match='duplicate effective control'):validate(records)


def test_role_counts_alone_do_not_prove_extrapolation():
    records=rows();records[0]['split']='validation';records[8]['split']='test'
    with pytest.raises(ValueError):validate(records)


def test_control_identity_uses_values_not_text_or_signed_zero():
    a=np.zeros((2,7));a[1,0]=.1;a[:,3]=-9.81
    b=a.copy();b[:,1]=-0.
    assert semantic_hash(a)==semantic_hash(b)
    b[1,1]=.01
    assert semantic_hash(a)!=semantic_hash(b)
