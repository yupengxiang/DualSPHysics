#!/usr/bin/env python3
"""Build bounded F7 motion specifications without writing sampled motion data.

The builder emits one JSON specification per amplitude.  It does not generate the
native sampled ``.dat`` table, XML, BI4, H5, particle arrays, CSV, solver output, or
render.  Root can review these scalar specifications before a separate strict motion
preparation and full-window workflow.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"expected object in {path}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    table = load(args.table)
    rows = table.get("rows")
    axis = table.get("amplitude_axis", {})
    if not isinstance(rows, list) or len(rows) != 8:
        raise ValueError("the bounded F7 source plan must contain exactly eight rows")
    if axis.get("name") != "paddle_amplitude_deg":
        raise ValueError("F7 plan must vary paddle_amplitude_deg only")
    lower, upper = (float(value) for value in axis.get("bounded_range", []))
    if (lower, upper) != (30.0, 65.0):
        raise ValueError("unexpected F7 amplitude bounds")
    ids = [row.get("physical_case_id") for row in rows]
    if len(set(ids)) != len(ids):
        raise ValueError("physical_case_id values must be unique")
    amplitudes = [float(row.get("amplitude_deg")) for row in rows]
    if any(value < lower or value > upper for value in amplitudes):
        raise ValueError("amplitude outside the bounded source plan")
    if any(row.get("axis") != "paddle_amplitude_deg" for row in rows):
        raise ValueError("each row must vary the same single physical dimension")

    anchor = table["source_anchor"]
    xml = Path(anchor["definition_xml"])
    motion = Path(anchor["motion_source"])
    if not xml.is_file() or sha256(xml) != anchor["definition_xml_sha256"]:
        raise RuntimeError("F7 source XML is missing or has changed")
    if not motion.is_file() or sha256(motion) != anchor["motion_source_sha256"]:
        raise RuntimeError("F7 source motion reference is missing or has changed")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    cases_dir = args.output_dir / "cases"
    cases_dir.mkdir(exist_ok=True)
    for row in rows:
        amplitude = float(row["amplitude_deg"])
        case_dir = cases_dir / row["physical_case_id"]
        case_dir.mkdir(exist_ok=True)
        spec = {
            "schema": "ds02.f7.motion-source-spec.v1",
            "family_id": "F7",
            "physical_case_id": row["physical_case_id"],
            "variation_dimension": "paddle_amplitude_deg",
            "amplitude_deg": amplitude,
            "source_xml": str(xml),
            "source_xml_sha256": anchor["definition_xml_sha256"],
            "source_motion_template": str(motion),
            "source_motion_template_sha256": anchor["motion_source_sha256"],
            "motion_definition": {
                "analytic_target": "theta=A*s(u), s(u)=10u^3-15u^4+6u^5",
                "cycle_schedule_s": "two finite symmetric cycles on 0..8; rest/residual on 8..12",
                "amplitude_parameter": "A in degrees",
                "native_reader": "piecewise_linear_absolute_angle_increment",
                "analytic_regular": "C2",
                "native_sampled_regular": "not C2",
                "sample_interval_s": 0.001,
                "pivot_p1_m": [-0.04, 0.0, 0.05],
                "pivot_p2_m": [-0.04, 0.0, 1.05],
            },
            "execution_policy": {
                "source_only": True,
                "sampled_motion_table": "root later after review; this builder does not write it",
                "gencase": "root later after motion preparation",
                "initial_qa": "root later after GenCase",
                "solver": "not invoked by this builder",
                "conversion": "not invoked by this builder",
                "rendering": "not invoked by this builder",
                "arrays": "not materialized",
                "csv": "not generated",
            },
            "claims": {
                "native_C2": "not claimed; sampled reader is piecewise linear",
                "mass_rescale": "forbidden",
                "overlap_clearance": "unverified",
                "visual_acceptance": "pending",
                "numerical_precision": "not accepted",
            },
        }
        with (case_dir / "motion-spec.json").open("w", encoding="utf-8") as stream:
            json.dump(spec, stream, indent=2, sort_keys=True)
            stream.write("\n")

    receipt = {
        "schema": "ds02.f7.motion-builder-receipt.v1",
        "source_plan": str(args.table),
        "source_plan_sha256": sha256(args.table),
        "case_count": len(rows),
        "output_kind": "bounded scalar motion specifications only",
        "tools_invoked": [],
        "sampled_motion_tables_written": [],
        "binary_or_particle_outputs": [],
        "launch_allowed": False,
    }
    with (args.output_dir / "motion-plan-receipt.json").open("w", encoding="utf-8") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
