import json
from pathlib import Path


LAB = Path(__file__).resolve().parents[1]
AUDIT = LAB / "campaigns/core-v1/cfd/f5-wave-runup-third-t1/fresh-definition-v2/preflight-boundary-semantics-audit-v1.json"


def test_f5_boundary_semantics_audit_is_read_only_and_closes_counts():
    value = json.loads(AUDIT.read_text())
    assert value["schema"] == "core.f5.third_t1.preflight_boundary_semantics_audit.v1"
    assert value["status"] == "read_only_semantics_audit_passed"
    counts = value["counts"]
    assert counts["generated_total_particles"] == 1374477
    assert counts["generated_boundary_particles_including_moving"] == 94622
    assert counts["generated_fixed_particles"] == 86270
    assert counts["derived_moving_particles"] == 8352
    assert counts["generated_fluid_particles"] == 1279855
    assert counts["identity_closure"] is True
    assert counts["native_fixed_semantics_match"] is True
    controls = value["execution_controls"]
    assert controls["solver_invoked"] is False
    assert controls["gpu_started"] is False
    assert controls["qualification_credit"] == 0
