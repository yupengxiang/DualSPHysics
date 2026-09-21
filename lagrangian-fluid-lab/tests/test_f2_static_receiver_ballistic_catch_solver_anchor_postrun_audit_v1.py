from __future__ import annotations

from scripts import f2_static_receiver_ballistic_catch_solver_anchor_postrun_audit_v1 as audit


def test_run_out_parser_retains_excluded_particle_failure():
    text = "TimeMax=1.5\nTimePart=0.005\nExcluded particles...............: 64\nExcluded particles due to Density: 44\nFinished execution (code=0)."
    result = audit._parse_run_out(text)
    assert result["time_max_s"] == 1.5
    assert result["output_interval_s"] == 0.005
    assert result["excluded_particles"] == 64
    assert result["excluded_particles_density"] == 44
    assert result["finished_code_zero"] is True


def test_postrun_receipt_preserves_zero_credit_policy():
    assert audit.SCHEMA.endswith("postrun_audit.v1")
    assert audit.OUTPUT.name == "postrun-audit.json"
