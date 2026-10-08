#!/usr/bin/env python3
"""Source and weighted-impact counterexamples for expanded F2 native audit."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import tempfile


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ds_data02_stage2_f2_fine_expanded_native_weighted_v1.py"
SPEC = importlib.util.spec_from_file_location("expanded_native_weighted_v1", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot import expanded native weighted module")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def expect_rejected(callback, label: str) -> None:
    try:
        callback()
    except MODULE.WeightedAuditError:
        return
    raise AssertionError(f"manufactured {label} was accepted")


def main() -> int:
    original_path, original_receipt = MODULE.read_json(MODULE.ORIGINAL_SOLVER_RECEIPT, "original solver")
    expanded_path, expanded_receipt = MODULE.read_json(MODULE.EXPANDED_SOLVER_RECEIPT, "expanded solver")
    original = MODULE.solver_source(original_path, original_receipt, MODULE.ORIGINAL_CASE)
    expanded = MODULE.solver_source(expanded_path, expanded_receipt, MODULE.EXPANDED_CASE)
    assert original["trajectory_inventory"]["content_hash_performed"] is False
    assert expanded["trajectory_inventory"]["content_hash_performed"] is False

    expanded_request_path, expanded_request = MODULE.read_json(MODULE.EXPANDED_REQUEST, "expanded request")
    original_xml = Path(str(original_receipt["request"]["command"][1])).with_suffix(".xml")
    expanded_xml = Path(str(expanded_request["command"][1])).with_suffix(".xml")
    original_meta, expanded_meta = MODULE.validate_pair_xml(original_xml, expanded_xml)
    assert original_meta["initial_mass_kg"] == 21.060888732
    assert expanded_meta["initial_mass_kg"] == original_meta["initial_mass_kg"]
    original_runparts = MODULE.parse_runparts(original["refs"]["runparts"]["path"], "original RunPARTs")
    expanded_runparts = MODULE.parse_runparts(expanded["refs"]["runparts"]["path"], "expanded RunPARTs")
    original_rows = MODULE.parse_native_csv(MODULE.ORIGINAL_DECODER_CSV, "original decoder CSV")
    assert len(original_rows) == 175
    assert original_runparts["totals"]["NpOut"] == 175
    assert expanded_runparts["totals"]["NpOut"] == 111

    with tempfile.TemporaryDirectory(prefix="ds02-expanded-weighted-tests-") as directory:
        root = Path(directory)
        wrong_receipt = copy.deepcopy(expanded_receipt)
        wrong_receipt["request"]["physical_case_id"] = "WRONG_CURRENT_CASE"
        wrong_receipt_path = root / "wrong-receipt.json"
        wrong_receipt_path.write_text(json.dumps(wrong_receipt), encoding="utf-8")
        expect_rejected(lambda: MODULE.solver_source(wrong_receipt_path, wrong_receipt, MODULE.EXPANDED_CASE), "wrong physical identity")

        altered_xml = root / "altered.xml"
        altered_xml.write_text(Path(expanded_xml).read_text(encoding="utf-8").replace('key="Visco" value="0.03"', 'key="Visco" value="0.04"', 1), encoding="utf-8")
        expect_rejected(lambda: MODULE.validate_pair_xml(original_xml, altered_xml), "non-domain XML mutation")

        native_csv = root / "native.csv"
        native_csv.write_text(
            "Idp,PartOut,Motive,Pos.x [m],Pos.y [m],Pos.z [m],Rhop [kg/m^3]\n"
            "540321,1,1,0,0,0,1000\n", encoding="utf-8"
        )
        good_rows = MODULE.parse_native_csv(native_csv, "manufactured native CSV")
        metadata = {"fluid_count": 1, "massfluid_kg": 0.5, "initial_mass_kg": 0.5,
                    "ranges": [{"mkfluid": 0, "mk_absolute": 1, "begin": 540321, "count": 1, "end": 540322}]}
        runparts = {"rows": [{"part": 0, "time_s": 0.0, "NpOut": 0, "NpOutPos": 0, "NpOutRho": 0, "NpOutMov": 0},
                              {"part": 1, "time_s": 0.1, "NpOut": 1, "NpOutPos": 1, "NpOutRho": 0, "NpOutMov": 0}],
                    "totals": {"NpOut": 1, "NpOutPos": 1, "NpOutRho": 0, "NpOutMov": 0}}
        paired = MODULE.paired_weighted_impact(good_rows, good_rows, runparts, runparts, metadata)
        assert paired["native_visibility_difference"]["original_minus_expanded_count"] == 0

        duplicate = root / "duplicate.csv"
        duplicate.write_text(native_csv.read_text(encoding="utf-8") + "540321,1,1,0,0,0,1000\n", encoding="utf-8")
        expect_rejected(lambda: MODULE.parse_native_csv(duplicate, "duplicate native CSV"), "duplicate Idp")

        expect_rejected(lambda: MODULE.no_trajectory(root / "Part_000.bi4", "manufactured trajectory"), "trajectory input")

        prepared_dir = root / "prepared-request"
        prepared = MODULE.prepare(prepared_dir)
        request = json.loads(Path(prepared["request"]).read_text(encoding="utf-8"))
        assert prepared["original_native_expected"] == 175
        assert prepared["expanded_native_expected"] == 111
        assert not any(path.endswith("trajectory.h5") or ("/Part_" in path and path.endswith(".bi4")) for path in request["input_files"])
        assert request["source_scope"]["config_closed"] is True
        assert request["source_read_cost"]["h5_bytes_read"] == 0
        assert request["source_read_cost"]["trajectory_bytes_read"] == 0

    print("stage2 F2 expanded native weighted source/config/impact counterexamples: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
