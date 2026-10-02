import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from ds_data02_handoff_exclusions import bind_exclusions


def data():
    return dict(ids=[7,8,9], zones=[0,0,0], types=[0,3,3], first_missing=[-1,2,-1],
                frames=4, records=[dict(idp=8,part_out=2,motive_code=1,motive='position',
                                       position_m=[1,2,-1],density_kg_m3=999)],
                totals=dict(NpOut=1,NpOutPos=1,NpOutRho=0,NpOutMov=0))


def test_native_exclusion_retains_unknown_physical_fate():
    ledger=bind_exclusions(**data())
    assert ledger['excluded_particles'][0]['first_missing_frame']==2
    assert 'physical fate unknown' in ledger['interpretation']


@pytest.mark.parametrize('change', ['wrong_id','wrong_frame','duplicate','wrong_motive_count','missing'])
def test_reject_unbound_or_inconsistent_native_exclusion(change):
    d=data()
    if change=='wrong_id':d['records'][0]['idp']=7
    if change=='wrong_frame':d['records'][0]['part_out']=3
    if change=='duplicate':d['records'].append(d['records'][0].copy())
    if change=='wrong_motive_count':d['totals']['NpOutRho']=1
    if change=='missing':d['records']=[]
    with pytest.raises(ValueError):bind_exclusions(**d)
