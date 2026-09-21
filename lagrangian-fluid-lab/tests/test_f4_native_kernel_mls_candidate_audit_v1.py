import json
from scripts.f4_native_kernel_mls_candidate_audit_v1 import audit

def test_existing_native_mls_candidate_is_blocked_without_mutation():
    r = audit()
    assert r["status"] == "blocked"
    assert r["credit"] == 0 and r["T2_macro"] is False
    assert r["gates"]["unknown_pass"] is True
    assert r["gates"]["cdf_pass"] is False
    assert r["gates"]["full_window_pass"] is False
    assert r["gates"]["residence_gate_pass"] is False
    assert r["execution"]["solver_started"] is False
