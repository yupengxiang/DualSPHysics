import json
import pytest
from scripts import f3_long_campaign as campaign
from scripts.l1r_q2_mdbc_bridge import sha256


def test_failure_diagnostic_does_not_open_matrix(tmp_path,monkeypatch):
    monkeypatch.setattr(campaign,'OUT',tmp_path)
    source=tmp_path/'F3_CELL3_LONG_dp0p01_a1p000_noslip_visco1-AUDIT.json'
    source.write_text(json.dumps({'audit_status':'quality_failed','issues':['swept_finite_wall_or_obstacle_crossing']}))
    design=tmp_path/'F3-NS1-TIME-DIAGNOSTIC-DESIGN.json'
    design.write_text(json.dumps({'registered_before_solver':True,'attempts':1,'predecessor_audit_sha256':sha256(source)}))
    campaign.check_ns1_expansion('noslip_visco1_time',.01,1.)
    for variant,dp,amplitude in [('noslip_visco1',.0075,1.),('noslip_visco1_time',.0075,1.),('noslip_visco1_time',.01,.9),('noslip_visco1_output',.01,1.)]:
        with pytest.raises(ValueError):campaign.check_ns1_expansion(variant,dp,amplitude)
    source.write_text(source.read_text()+'\n')
    with pytest.raises(ValueError):campaign.check_ns1_expansion('noslip_visco1_time',.01,1.)
