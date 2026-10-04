#!/usr/bin/env python3
"""Build bounded F4 source specifications without running a physics tool.

The output is review metadata only.  It deliberately does not write XML/BI4/H5,
particle arrays, CSV, or solver output.  Root may use the specifications as inputs
to a separately reviewed GenCase and full-window native workflow.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ALLOWED_MOTHERS = {"drop", "columns"}
ALLOWED_DIMENSIONS = {
    "drop": {"anchor", "initial_height_gap", "initial_velocity"},
    "columns": {"anchor", "initial_horizontal_separation", "initial_transverse_offset"},
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_hash(path_text: str, expected: str) -> None:
    path = Path(path_text)
    if not path.is_file():
        raise RuntimeError(f"source reference is missing: {path}")
    observed = sha256(path)
    if observed != expected:
        raise RuntimeError(f"source hash mismatch for {path}: {observed} != {expected}")


def load(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"expected object in {path}")
    return value


def validate_row(row: dict[str, Any]) -> None:
    mother = row.get("source_mother")
    dimension = row.get("variation_dimension")
    if mother not in ALLOWED_MOTHERS:
        raise ValueError(f"unsupported mother {mother!r}")
    if dimension not in ALLOWED_DIMENSIONS[mother]:
        raise ValueError(f"unsupported variation {dimension!r} for {mother!r}")
    if not row.get("physical_case_id"):
        raise ValueError("physical_case_id is required")
    if row.get("dp_m") != 0.01:
        raise ValueError("F4 batch is pinned to the source DP010 recipe")
    if mother == "drop":
        gap = float(row["gap_m"])
        speed = float(row["drop_speed_m_per_s"])
        x_offset = abs(float(row["drop_x_offset_m"]))
        y_offset = abs(float(row["drop_y_offset_m"]))
        if not 0.18 <= gap <= 0.26:
            raise ValueError(f"drop gap outside bounded plan: {gap}")
        if not 0.4 <= speed <= 0.5:
            raise ValueError(f"drop speed outside bounded plan: {speed}")
        if x_offset > 0.08 or y_offset > 0.04:
            raise ValueError("drop offset outside bounded tank-safe plan")
    else:
        edge_gap = float(row["edge_gap_m"])
        y_offset = abs(float(row["right_y_offset_m"]))
        transverse = float(row["transverse_speed_m_per_s"])
        if not 0.36 <= edge_gap <= 0.60:
            raise ValueError(f"column edge gap outside bounded plan: {edge_gap}")
        if y_offset > 0.02:
            raise ValueError("column y offset outside bounded plan")
        if not 0.25 <= transverse <= 0.25:
            raise ValueError(f"column transverse speed changed from source recipe: {transverse}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    table = load(args.table)
    rows = table.get("rows")
    if not isinstance(rows, list) or len(rows) != 8:
        raise ValueError("the bounded F4 source plan must contain exactly eight rows")
    ids = [row.get("physical_case_id") for row in rows]
    if len(set(ids)) != len(ids):
        raise ValueError("physical_case_id values must be unique")

    anchors = table["source_anchors"]
    for name in ("drop", "columns"):
        anchor = anchors[name]
        require_hash(anchor["definition_xml"], anchor["definition_xml_sha256"])
        require_hash(anchor["generated_xml"], anchor["generated_xml_sha256"])

    for row in rows:
        validate_row(row)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    cases_dir = args.output_dir / "cases"
    cases_dir.mkdir(exist_ok=True)
    for row in rows:
        case_dir = cases_dir / row["physical_case_id"]
        case_dir.mkdir(exist_ok=True)
        mother = anchors[row["source_mother"]]
        spec = {
            "schema": "ds02.f4.source-definition.v1",
            "family_id": "F4",
            "physical_case_id": row["physical_case_id"],
            "source_mother": row["source_mother"],
            "variation_dimension": row["variation_dimension"],
            "source_definition_xml": mother["definition_xml"],
            "source_definition_xml_sha256": mother["definition_xml_sha256"],
            "source_generated_xml": mother["generated_xml"],
            "source_generated_xml_sha256": mother["generated_xml_sha256"],
            "dp_m": row["dp_m"],
            "physical_parameters": {
                key: value
                for key, value in row.items()
                if key.endswith("_m") or key.endswith("_m_per_s") or key in {"gap_m", "edge_gap_m"}
            },
            "execution_policy": {
                "source_only": True,
                "gencase": "root later after review",
                "initial_qa": "root later after GenCase",
                "solver": "not invoked by this builder",
                "conversion": "not invoked by this builder",
                "rendering": "not invoked by this builder",
                "arrays": "not materialized",
                "csv": "not generated",
            },
            "claims": {
                "overlap_clearance": "unverified",
                "legal_window": "unverified",
                "precision": "not accepted",
                "visual_acceptance": "pending",
            },
        }
        with (case_dir / "source-definition.json").open("w", encoding="utf-8") as stream:
            json.dump(spec, stream, indent=2, sort_keys=True)
            stream.write("\n")

    receipt = {
        "schema": "ds02.f4.source-builder-receipt.v1",
        "source_plan": str(args.table),
        "source_plan_sha256": sha256(args.table),
        "case_count": len(rows),
        "output_kind": "bounded JSON definitions only",
        "tools_invoked": [],
        "binary_or_particle_outputs": [],
        "launch_allowed": False,
    }
    with (args.output_dir / "source-plan-receipt.json").open("w", encoding="utf-8") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
