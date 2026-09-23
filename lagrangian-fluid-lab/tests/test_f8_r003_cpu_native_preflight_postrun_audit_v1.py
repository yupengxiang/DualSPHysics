from __future__ import annotations

import pytest

from scripts import f8_r003_cpu_native_preflight_postrun_audit_v1 as audit_module


def test_r003_postrun_audit_retains_closed_control_copy_failure() -> None:
    audit = audit_module.build_audit()
    assert audit["status"] == "retained_hard_failure_no_retry_zero_credit"
    assert audit["qualification_credit"] == 0
    assert audit["failure_closure"]["gencase_invocations_confirmed"] == 1
    assert audit["failure_closure"]["native_decode_invocations_confirmed"] == 0
    assert audit["retained_facts"]["generated_fixed_boundary_particle_count"] == 512
    assert audit["retained_facts"]["generated_bi4_present_nonempty"] is True
    assert "not inspected" in audit["retained_facts"]["boundary_normals"]


def test_r003_postrun_audit_writer_is_immutable(tmp_path) -> None:
    target = tmp_path / "receipt.json"
    audit_module.write_audit(target)
    with pytest.raises(FileExistsError, match="immutable F8 r003 postrun audit"):
        audit_module.write_audit(target)
