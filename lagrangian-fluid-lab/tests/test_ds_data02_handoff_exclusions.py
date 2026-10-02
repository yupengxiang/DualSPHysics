import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from ds_data02_handoff_exclusions import bind_exclusions, read_runparts


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


def test_official_native_footer_is_documentation(tmp_path):
    path=tmp_path/'RunPARTs.csv'
    path.write_text('Part;TimeStep [s];NpOut;NpOutPos;NpOutRho;NpOutMov\n'
                    '0;0;0;0;0;0\n1;0.1;1;1;0;0\n\n# NpOut: documentation.\n')
    assert read_runparts(path)['totals']['NpOut']==1
    path.write_text(path.read_text()+'malformed;data\n')
    with pytest.raises((ValueError,TypeError)):read_runparts(path)
