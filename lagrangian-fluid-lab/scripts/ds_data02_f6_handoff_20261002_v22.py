#!/usr/bin/env python3
"""Additive audit of PartVTKOut rows against the initial fluid cohort."""

from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
V21 = SCRIPT.with_name("ds_data02_f6_handoff_20261002_v21.py")
SPEC = importlib.util.spec_from_file_location("f6_handoff_v21_for_partvtkout_audit", V21)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load v21: {V21}")
V21_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(V21_MODULE)

POST_ROOT = V21_MODULE.POST_ROOT
RAW_ROOT = V21_MODULE.RAW_ROOT


def read_json(path: Path) -> dict[str, Any]:
    return V21_MODULE.read_json(path)


def write_json(path: Path, value: Any) -> None:
    V21_MODULE.write_json(path, value)


def sha256(path: Path) -> str:
    return V21_MODULE.sha256(path)


def _bbox(xml: Path) -> tuple[list[float], list[float]] | None:
    import xml.etree.ElementTree as ET

    root = ET.parse(xml).getroot()
    posmin = root.find(".//positions/posmin")
    posmax = root.find(".//positions/posmax")
    if posmin is None or posmax is None:
        return None
    return ([float(posmin.get(axis, "nan")) for axis in "xyz"], [float(posmax.get(axis, "nan")) for axis in "xyz"])


def _fluid_group(xml: Path) -> dict[str, Any]:
    import xml.etree.ElementTree as ET

    root = ET.parse(xml).getroot()
    node = root.find(".//execution/particles/fluid")
    if node is None:
        raise ValueError(f"fluid group missing: {xml}")
    begin = int(node.get("begin", "-1"))
    count = int(node.get("count", "0"))
    return {"begin": begin, "count": count, "end_exclusive": begin + count}


def audit() -> dict[str, Any]:
    source = read_json(POST_ROOT / "partvtkout_reconciliation_001.json")
    rows: list[dict[str, Any]] = []
    for case in source["cases"]:
        case_id = str(case["case_id"])
        decoded = case["partvtkout"]["decoded"]
        case_root = RAW_ROOT / case_id
        csv_path = Path(case["partvtkout"]["csv"])
        resume_path = csv_path.with_name("excluded-resume.csv")
        request_path = next(POST_ROOT.joinpath("execution_requests").glob(f"{case_id}_partvtkout_001.json"))
        request = read_json(request_path)
        xml = next(path for path in (case_root / f"{case_id}_GENCASE_001").glob("*.xml"))
        group = _fluid_group(xml)
        bbox = _bbox(xml)
        fluid_rows = [row for row in decoded.get("rows", []) if row.get("role") == "fluid"]
        first_rows = sorted(fluid_rows, key=lambda row: (float("inf") if row.get("time_s") is None else row["time_s"], row.get("particle_id", -1)))
        initial_rows: list[dict[str, Any]] = []
        for row in first_rows:
            position = row.get("position_m")
            axes_outside: list[str] = []
            if bbox and position and all(value is not None and math.isfinite(value) for value in position):
                low, high = bbox
                for idx, axis in enumerate("xyz"):
                    if position[idx] < low[idx] or position[idx] > high[idx]:
                        axes_outside.append(axis)
            initial_rows.append({
                "particle_id": row["particle_id"],
                "part_out": row["part_out"],
                "time_s": row.get("time_s"),
                "motive": row.get("motive"),
                "native_reason": row.get("native_reason"),
                "position_m": position,
                "density_kg_m3": row.get("density_kg_m3"),
                "outside_generated_xml_numeric_bbox_axes": axes_outside,
                "destination_after_exclusion": "unknown",
            })
        runparts_total = int(case["runparts"]["totals"].get("np_out", 0))
        row_count = len(decoded.get("rows", []))
        unknown_rows = [row for row in decoded.get("rows", []) if row.get("native_reason") == "unknown"]
        enriched = dict(case)
        enriched["initial_fluid_cohort"] = {"begin": group["begin"], "count": group["count"], "end_exclusive": group["end_exclusive"], "first_missing_rows": initial_rows, "first_missing_time_s": initial_rows[0]["time_s"] if initial_rows else None, "first_missing_particle_id": initial_rows[0]["particle_id"] if initial_rows else None}
        enriched["partvtkout_resume"] = {"path": str(resume_path.resolve()), "sha256": sha256(resume_path) if resume_path.is_file() else None, "exists": resume_path.is_file()}
        enriched["native_reconciliation_checks"] = {
            "receipt_completed_code0": case["receipt"]["status"] == "completed" and case["receipt"]["returncode"] == 0,
            "partout_row_count_equals_runparts_npout": row_count == runparts_total,
            "all_partout_rows_are_initial_fluid_cohort": len(initial_rows) == row_count,
            "native_reason_unknown_count": len(unknown_rows),
            "no_rows_and_zero_runparts_is_explicit": row_count == 0 and runparts_total == 0,
            "finite_positions_when_present": all(all(value is not None and math.isfinite(value) for value in row.get("position_m", [])) for row in decoded.get("rows", [])),
            "physical_destination_after_exclusion": "unknown_preserved",
        }
        enriched["unknown_physical_destination_preserved"] = True
        enriched["q_n_status"] = "pending_native_exclusion_reconciliation"
        rows.append(enriched)
    result = {
        "schema": "ds-data-02.f6.rigid003.partvtkout-reconciliation.v2",
        "family_id": "F6",
        "status": "review_only",
        "source_reconciliation": str((POST_ROOT / "partvtkout_reconciliation_001.json").resolve()),
        "source_reconciliation_sha256": sha256(POST_ROOT / "partvtkout_reconciliation_001.json"),
        "cases": rows,
        "qualification_claim": "none",
        "production_claim": "none",
        "unknown_policy": "PartVTKOut positions and Motive are retained; post-exclusion physical destination is unknown unless independently established.",
    }
    write_json(POST_ROOT / "partvtkout_reconciliation_002.json", result)
    return result


if __name__ == "__main__":
    print(json.dumps(audit(), ensure_ascii=False, indent=2))
