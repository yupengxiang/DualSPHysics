from __future__ import annotations

from pathlib import Path

from scripts.r3_f45_external_feasibility import (
    _minimum_anchor,
    inspect_piston,
    inspect_wave_reference,
)


def _write_reference(path: Path, rows: list[str]) -> None:
    path.write_text("time [s] wg1_exp [m] wg2_exp [m] wg3_exp [m] wg4_exp [m] run-up_exp [m]\n"
                    + "\n".join(rows) + "\n")


def test_wave_reference_accepts_rounded_duplicate_timestamps(tmp_path):
    path = tmp_path / "reference.txt"
    _write_reference(path, [
        "0.00 0 0 0 0 0.25",
        "0.02 0.01 0 0 0 0.25",
        "0.04 0.03 0.01 0 0 0.26",
        "0.1 0.02 0.01 0 0 0.25",
        "0.1 0.01 0 0 0 0.25",
        "0.2 0 0 0 0 0.25",
    ])
    report = inspect_wave_reference(path)
    assert report["structural_pass"] is True
    assert report["time_non_decreasing"] is True
    assert report["time_strictly_increasing"] is False
    assert report["duplicate_time_count"] == 1
    assert report["duplicate_time_values_s"] == [0.1]


def test_wave_reference_rejects_backward_time(tmp_path):
    path = tmp_path / "reference.txt"
    _write_reference(path, [
        "0.00 0 0 0 0 0.25",
        "0.10 0.01 0 0 0 0.25",
        "0.05 0.02 0 0 0 0.25",
    ])
    report = inspect_wave_reference(path)
    assert report["structural_pass"] is False
    assert report["time_non_decreasing"] is False
    assert any("non-decreasing" in issue for issue in report["issues"])


def test_piston_forcing_allows_initial_duplicate_timestamp(tmp_path):
    path = tmp_path / "piston.dat"
    path.write_text("0.0 0.0\n0.0 0.0\n0.1 0.01\n")
    report = inspect_piston(path)
    assert report["structural_pass"] is True
    assert report["initial_duplicate_time_rows"] == 2


def test_f45_anchor_contracts_remain_candidate_only():
    for family in ("F4", "F5"):
        anchor = _minimum_anchor(family)
        assert anchor["status"] in {
            "blocked_missing_external_reference",
            "partial_reference_but_not_aligned",
        }
        assert "repeat the same physical case at three resolutions with fixed nondimensional inputs" in anchor[
            "numerical_acceptance"
        ]
        assert anchor["required_common_fields"][-1] == "measurement_uncertainty"
