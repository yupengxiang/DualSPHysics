#!/usr/bin/env python3
"""Build bounded F6 angular-velocity source specifications only.

This builder emits review JSON and verifies the immutable corrected source XML hash.
It intentionally does not mutate XML, write BI4, run GenCase or the solver, decode
PartVTK, convert H5, generate CSV/arrays, or render an animation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


BASE_OMEGA = (0.08, 0.12, 0.06)
ALLOWED_SCALES = (0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0)


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
    dimension = table.get("single_control_dimension", {})
    if not isinstance(rows, list) or len(rows) != 8:
        raise ValueError("the F6 omega plan must contain exactly eight rows")
    if tuple(dimension.get("values", [])) != ALLOWED_SCALES:
        raise ValueError("unexpected angular velocity scale set")
    if tuple(dimension.get("base_vector_rad_s", [])) != BASE_OMEGA:
        raise ValueError("unexpected base angular velocity vector")
    if len({row.get("physical_case_id") for row in rows}) != 8:
        raise ValueError("physical_case_id values must be unique")

    anchor = table["source_evidence"]
    xml = Path(anchor["generated_xml"])
    if not xml.is_file():
        raise RuntimeError(f"source XML is missing: {xml}")
    observed_hash = sha256(xml)
    if observed_hash != anchor["generated_xml_sha256"]:
        raise RuntimeError(f"source XML hash mismatch: {observed_hash}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    cases_dir = args.output_dir / "cases"
    cases_dir.mkdir(exist_ok=True)
    for row in rows:
        scale = float(row["angular_velocity_scale_s"])
        if scale not in ALLOWED_SCALES:
            raise ValueError(f"scale outside bounded plan: {scale}")
        omega = [round(scale * component, 12) for component in BASE_OMEGA]
        if row["initial_angular_velocity_rad_s"] != omega:
            raise ValueError(f"row omega does not equal scale*base: {row['physical_case_id']}")
        if row.get("variation_dimension") != "angular_velocity_scale_s":
            raise ValueError("a non-omega variation was found")
        if row.get("orientation_angle_deg") != 0.0 or row.get("center_m") != [2.4, 1.2, 1.08]:
            raise ValueError("orientation or center changed in an omega-only row")

        case_dir = cases_dir / row["physical_case_id"]
        case_dir.mkdir(exist_ok=True)
        spec = {
            "schema": "ds02.f6.omega-source-definition.v1",
            "family_id": "F6",
            "physical_case_id": row["physical_case_id"],
            "source_mother": "F6_ANGULAR_RELEASE_DP025",
            "variation_dimension": "angular_velocity_scale_s",
            "angular_velocity_scale_s": scale,
            "angularvelini_rad_s": omega,
            "fixed_initial_state": {
                "orientation": "identity; axis-angle z/0 degrees",
                "linear_velocity_m_s": [0.0, 0.0, 0.0],
                "center_m": [2.4, 1.2, 1.08],
                "body_mass_kg": 128.0,
                "native_support_mass_kg": 256.0,
                "dp_m": 0.025,
            },
            "source_xml": str(xml),
            "source_xml_sha256": anchor["generated_xml_sha256"],
            "generation_policy": {
                "change_only": "floating angularvelini",
                "fresh_gencase_required": True,
                "old_bi4_reuse": "forbidden",
                "initial_bi4_zero_velocity": "must be regenerated and re-audited; no byte cloning",
                "original_initial_qa_required": True,
                "semantic_audit_required": True,
                "frame0_propagation_audit_required": True,
            },
            "execution_policy": {
                "source_only": True,
                "gencase": "not invoked by this builder",
                "solver": "not invoked by this builder",
                "conversion": "not invoked by this builder",
                "arrays": "not materialized",
                "csv": "not generated",
                "rendering": "not invoked by this builder",
            },
            "claims": {
                "overlap_clearance": "unverified",
                "frame0_angular_propagation": "unobserved",
                "precision": "not accepted",
                "visual_acceptance": "pending",
                "q_n": "not_assessed",
            },
        }
        with (case_dir / "source-definition.json").open("w", encoding="utf-8") as stream:
            json.dump(spec, stream, indent=2, sort_keys=True)
            stream.write("\n")

    receipt = {
        "schema": "ds02.f6.omega-source-builder-receipt.v1",
        "source_plan": str(args.table),
        "source_plan_sha256": sha256(args.table),
        "case_count": len(rows),
        "output_kind": "bounded scalar angular velocity specifications only",
        "tools_invoked": [],
        "gencase_outputs": [],
        "solver_outputs": [],
        "h5_outputs": [],
        "bi4_outputs": [],
        "csv_outputs": [],
        "launch_allowed": False,
    }
    with (args.output_dir / "omega-plan-receipt.json").open("w", encoding="utf-8") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
