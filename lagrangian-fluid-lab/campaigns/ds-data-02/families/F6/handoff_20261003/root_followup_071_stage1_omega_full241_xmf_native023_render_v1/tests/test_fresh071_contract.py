import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def j(p): return json.loads((ROOT/p).read_text())
def test_actual_lineage():
    a=j(Path('strict')/'aggregate-binding.json'); assert a['launch_allowed'] is False and len(a['cases'])==2
    for c in a['cases']:
        assert c['native098']['status']=='completed' and c['native098']['returncode']==0
        assert c['typed068']['status']=='completed' and c['typed068']['returncode']==0
        assert c['typed068']['conversion_status']=='completed' and c['typed068']['frames']==241 and c['typed068']['particles']==417505
        assert c['typed068']['solver_dimension']['run_out_dimensions']==[3] and c['typed068']['partvtk_all_passed'] is True
        assert c['qa090']['pass'] is True and c['qa090']['checks_all_true'] is True and c['qa090']['failed_checks']==[]
        assert c['floatinginfo102']['status']=='completed' and c['floatinginfo102']['returncode']==0
        assert len(c['canonical_owner_sha256'])==64 and len(c['genuine_gencase073']['bi4_sha256'])==64
def test_disabled_requests():
    a=j(Path('strict')/'aggregate-binding.json')
    for c in a['cases']:
        x=j(Path('requests')/(c['case_id']+'-xmf-request.json')); r=j(Path('requests')/(c['case_id']+'-render-request.json'))
        assert x['launch'] is False and x['launch_allowed'] is False and x['estimated_output']['expected_frames']==241
        assert r['launch'] is False and r['launch_allowed'] is False and r['output_contract']['frame_count']==241 and r['output_contract']['frame_range']==[0,240]
        assert r['output_contract']['all_frames_rendered'] is True and r['output_contract']['camera_fixed_bounds_forbidden'] is True
        assert 'diagnostic-frames' not in r['command']
def test_future_hashes_null():
    a=j(Path('strict')/'aggregate-binding.json')
    for c in a['cases']:
        assert all(v is None for v in c['xmf_output_hashes'].values())
        assert all(v is None for v in c['render_output_hashes'].values())
def test_provenance():
    p=j(Path('provenance')/'source-provenance.json')
    assert p['workers']['render_native023']['upstream_sha256']=='5e78f7b92ad7c6f1d15902e3ccacc9099affb04b1b992a42f540eb88241bde66'
    assert p['read_policy']['h5_arrays_read'] is False and p['read_policy']['renderer_executed'] is False
