#!/usr/bin/env python3
"""Synthetic layout tests for the fresh105 parser contract.

These fixtures are tiny text files created under a temporary directory.  They
are not registered PartVTK output and contain no scientific dataset payload.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
import sys

WORKERS = Path(__file__).resolve().parents[1] / "workers"
sys.path.insert(0, str(WORKERS))
from fresh105_initial_qa_csv_parser import stream_csv  # noqa: E402


EXPECTED = {"total": 2, "counts": {"fixed": 1, "moving": 0, "floating": 0, "fluid": 1}}


def fixture(path: Path, delimiter: str, *, inline_units: bool, standalone_units: bool) -> None:
    if inline_units:
        headers = ["Pos.x [m]", "Pos.y [m]", "Pos.z [m]", "Vel.x [m/s]", "Vel.y [m/s]", "Vel.z [m/s]", "Rhop [kg/m^3]", "Mass [kg]", "Idp", "Type", "Mk"]
    else:
        headers = ["Pos.x", "Pos.y", "Pos.z", "Vel.x", "Vel.y", "Vel.z", "Rhop", "Mass", "Idp", "Type", "Mk"]
    rows = [
        "# PartVTK preface,synthetic",
        delimiter.join(headers),
    ]
    if standalone_units:
        rows.append(delimiter.join(["[m]", "[m]", "[m]", "[m/s]", "[m/s]", "[m/s]", "[kg/m^3]", "[kg]", "Idp", "Type", "Mk"]))
    rows.extend([
        delimiter.join(["0", "0", "0", "0", "0", "0", "1000", "1", "0", "fixed", "0"]),
        delimiter.join(["1", "0", "0", "0", "0", "0", "1000", "1", "1", "fluid", "1"]),
    ])
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ds02-fresh105-layout-") as directory:
        root = Path(directory)
        comma = root / "comma-inline.csv"
        fixture(comma, ",", inline_units=True, standalone_units=False)
        comma_result = stream_csv(comma, EXPECTED)
        assert comma_result["status"] == "pass", comma_result
        assert comma_result["header"]["delimiter"] == ",", comma_result
        assert comma_result["unit_rows_skipped"] == 0, comma_result
        assert comma_result["checks"]["units_layout_supported"] is True, comma_result

        semicolon = root / "semicolon-units-row.csv"
        fixture(semicolon, ";", inline_units=False, standalone_units=True)
        semicolon_result = stream_csv(semicolon, EXPECTED)
        assert semicolon_result["status"] == "pass", semicolon_result
        assert semicolon_result["header"]["delimiter"] == ";", semicolon_result
        assert semicolon_result["unit_rows_skipped"] == 1, semicolon_result
        assert semicolon_result["checks"]["units_layout_supported"] is True, semicolon_result
    print("fresh105 synthetic CSV layout tests: pass (comma+inline, semicolon+standalone)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
