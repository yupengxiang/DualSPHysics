from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import pytest


LAB = Path(__file__).resolve().parents[1]
SCRIPT = LAB / "scripts/f5_wave_runup_solver_anchor_runtime_v2.py"
SPEC = importlib.util.spec_from_file_location("f5_anchor_runtime_v2", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _real_run_out() -> Path:
    candidates = sorted(
        (
            LAB
            / "campaigns/core-v1/runtime/attempts/f5-wave-runup-third-t1-q05-dp0075-v2-protected-gpu-anchor"
        ).glob("*/product/solver/Run.out")
    )
    if not candidates:
        pytest.skip("the immutable local F5 anchor product is not present in this checkout")
    return candidates[-1]


def test_real_anchor_run_out_uses_native_output_cadence_without_mutation():
    run_out = _real_run_out()
    before = hashlib.sha256(run_out.read_bytes()).hexdigest()

    summary = MODULE._run_summary(run_out)

    assert summary["finished_code_zero"] is True
    assert summary["timemax_s"] == 16.0
    assert summary["output_dt_values_s"] == [0.02]
    assert summary["output_cadence_s"] == 0.02
    assert summary["excluded_particles"] == 0
    assert summary["steps"] == 138258
    assert hashlib.sha256(run_out.read_bytes()).hexdigest() == before


def test_timeout_token_alone_does_not_open_native_cadence_gate(tmp_path):
    run_out = tmp_path / "Run.out"
    run_out.write_text("TimeMax=16\nTimeOut=0.02\nFinished execution (code=0)\n", encoding="utf-8")

    summary = MODULE._run_summary(run_out)

    assert summary["timeout_s"] == 0.02
    assert summary["output_dt_values_s"] == []
    assert summary["output_cadence_s"] is None
    assert MODULE._cadence_gate(summary) is False


def test_native_output_record_accepts_spacing_and_scientific_notation(tmp_path):
    run_out = tmp_path / "Run.out"
    run_out.write_text(
        "TimeMax = 1.6e1\n"
        "Output........: 0 - 16   dt : 2e-2\n"
        "Output.....: 0 - 16   dt:0.02\n",
        encoding="utf-8",
    )

    summary = MODULE._run_summary(run_out)

    assert summary["timemax_s"] == 16.0
    assert summary["output_dt_values_s"] == [0.02]
    assert summary["output_record_count"] == 2
    assert MODULE._cadence_gate(summary) is True


def test_gauge_path_outside_snapshot_is_emitted_without_relative_to_failure(tmp_path):
    solver = tmp_path / "external-attempt" / "product" / "solver"
    solver.mkdir(parents=True)
    gauge = solver / "GaugesSWL_WG1.csv"
    rows = ["time [s];swlx [m];swly [m];swlz [m]"]
    rows.extend(f"{0.02 * index:.2f};0;0;{1.0 + index * 1e-4:.6f}" for index in range(801))
    gauge.write_text("\n".join(rows) + "\n", encoding="utf-8")

    result = MODULE._parse_gauge(gauge)

    assert result["path"] == str(gauge.resolve())
    assert result["rows"] == 801
    assert result["issues"] == []


def test_v2_contract_keeps_exact_one_zero_credit_and_forbidden_mutations():
    source = MODULE.__doc__ or ""
    assert "exactly one anchor" in source
    assert "zero qualification/matrix credit" in source
    assert MODULE.EXPECTED_FRAMES == 801
    assert MODULE.TOUT == 0.02


def test_frozen_v1_job_is_not_reused_until_a_new_v2_review_binds_the_worker():
    job = LAB / "campaigns/core-v1/cfd/f5-wave-runup-third-t1/fresh-definition-v2/solver-anchor-job-spec-v1.json"
    review = job.parent / "solver-anchor-root-review-v1.json"
    with pytest.raises(ValueError, match="runtime worker v2"):
        MODULE.verify_authorization(job, review)
