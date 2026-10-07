#!/usr/bin/env python3
"""Small source-closure counterexamples for the 118-case worker.

These tests use only manufactured CSV/argv values.  They prove that semantic
matching is keyed by Idp and that the official decoder command cannot silently
carry the previously rejected threads option or trajectory inputs.
"""
from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ds_data02_stage2_native_runtime_config_closure_v1.py"
SPEC = importlib.util.spec_from_file_location("closure_v1", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot import closure worker")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


HEADER = "Pos.x [m],Pos.y [m],Pos.z [m],PartOut,Motive,Idp,Vel.x [m/s],Vel.y [m/s],Vel.z [m/s],Rhop [kg/m^3],\n"
ROW = "0,0,0,3,1,42,1,2,3,1000,\n"


def write_csv(path: Path, row: str = ROW) -> None:
    path.write_text(HEADER + row, encoding="utf-8")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ds02-closure-tests-") as directory:
        root = Path(directory)
        old = root / "old.csv"
        fresh = root / "fresh.csv"
        write_csv(old)
        write_csv(fresh)
        match = MODULE.compare_rows(old, fresh, "manufactured")
        assert match["status"] == "EXACT_SEMANTIC_MATCH"
        assert match["row_count"] == 1

        wrong_id = root / "wrong-id.csv"
        write_csv(wrong_id, ROW.replace(",42,", ",43,"))
        try:
            MODULE.compare_rows(old, wrong_id, "wrong-id")
        except MODULE.ClosureError:
            pass
        else:
            raise AssertionError("wrong Idp unexpectedly received semantic-match credit")

        wrong_numeric = root / "wrong-numeric.csv"
        write_csv(wrong_numeric, ROW.replace(",1,2,3,1000,", ",1,2,3.0001,1000,"))
        try:
            MODULE.compare_rows(old, wrong_numeric, "wrong-numeric")
        except MODULE.ClosureError:
            pass
        else:
            raise AssertionError("wrong native position unexpectedly received semantic-match credit")

    tool = str(MODULE.TOOL_DEFAULT)
    try:
        MODULE.decoder_command({"command": [tool, "-dirdata", "/tmp/raw", "-savecsv", "/tmp/out", "-saveresume", "/tmp/resume", "-threads:1"]}, "threads")
    except MODULE.ClosureError:
        pass
    else:
        raise AssertionError("unsupported PartVTKOut threads option was accepted")

    for name in ("trajectory.h5", "Part_0001.bi4"):
        try:
            MODULE.assert_no_trajectory(Path("/tmp") / name, name)
        except MODULE.ClosureError:
            pass
        else:
            raise AssertionError(f"trajectory input was accepted: {name}")
    print("stage2 native config closure manufactured counterexamples: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
