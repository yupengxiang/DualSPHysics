from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "campaigns/ds-data-02/families/F2/f2_handoff_20261002_temporal_audit.py"
SPEC = importlib.util.spec_from_file_location("f2_temporal_audit", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_runparts_parser_uses_numeric_rows_and_save_bracket_budget(tmp_path):
    path = tmp_path / "RunPARTs.csv"
    path.write_text(
        "Part;TimeStep [s];DtMin [s];DtMax [s]\n"
        "0;0;0;0\n"
        "1;0.001;0.00004;0.00004\n"
        "2;0.0022;0.00004;0.00004\n"
        "# explanatory tail;ignored;ignored;ignored\n",
        encoding="utf-8",
    )

    result = MODULE.read_runparts(path)

    assert result["numeric_rows"] == 3
    assert result["part_last"] == 2
    assert result["save_interval_max_s"] == pytest.approx(0.0012)
    assert result["save_half_width_max_s"] == pytest.approx(0.0006)
    assert result["save_half_width_within_budget"]
