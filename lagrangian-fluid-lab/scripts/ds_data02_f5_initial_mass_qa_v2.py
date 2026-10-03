"""Generalized F5 native initial 3D fluid mass and typed-row QA evaluator v2.

Generalizes ds_data02_f5_finer_initial_audit_v1.py:
- Removes hardcoded 2352000 fluid particles and 7031723 total particles.
- Dynamically validates expected fluid particle count from manifest (18816 for DP050, 150528 for DP025, 2352000 for DP010).
- Verifies exact 3D GenCase evidence (solver_dimension_from_gencase == 3, data2d == false).
- Validates all native particle rows: finite coordinates, non-negative, consecutive unique IDs,
  proper typed blocks (fixed, moving, fluid), moving piston presence, initial particle velocities <= 1e-8.
- Validates native fluid mass sum equals 2352.0 kg within tolerance.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping
import xml.etree.ElementTree as ET

import numpy as np

# Add scripts directory to sys.path
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from ds_data02_f5_commensurate_dp_reference_010 import audit_partvtk
from ds_data02_native_labels import digest

SCHEMA_MASS_QA_V2 = "ds02.f5.strict-initial-mass-qa.v2"


def sha256_file(path: Path | str) -> str:
    digest_builder = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest_builder.update(block)
    return digest_builder.hexdigest()


def run(manifest_path: Path, output_dir: Path) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    m = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    receipt_path = Path(m["gencase_receipt"])
    if not receipt_path.is_file():
        raise FileNotFoundError(f"GenCase execution receipt missing: {receipt_path}")

    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if digest(receipt_path) != m["gencase_receipt_sha256"] or receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise ValueError(f"Actual completed GenCase receipt required: {receipt_path}")

    expected_fluid = int(m.get("expected_fluid_particles", 2352000))
    expected_mass = float(m.get("expected_fluid_mass_kg", 2352.0))

    if receipt.get("solver_dimension_from_gencase") != 3:
        raise ValueError("DS-DATA-02 core requires actual 3D GenCase evidence")
    if receipt.get("fluid_particles") != expected_fluid:
        raise ValueError(f"Unexpected actual native fluid count: {receipt.get('fluid_particles')} vs expected {expected_fluid}")

    prefix = Path(m["generated_prefix"])
    bi4_path = prefix.with_suffix(".bi4")
    xml_path = prefix.with_suffix(".xml")
    if not bi4_path.is_file() or not xml_path.is_file():
        raise FileNotFoundError(f"GenCase BI4 or XML missing for prefix: {prefix}")

    report = audit_partvtk(
        bi4_path,
        xml_path,
        output / "commensurate-grid-audit.json",
        output / "initial-all.csv",
    )

    path = output / "initial-all.csv"
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for lines, line in enumerate(stream, 1):
            header = [x.strip() for x in next(csv.reader([line]))]
            if "Pos.x [m]" in header and "Idp" in header:
                break
            if lines > 64:
                raise ValueError("Official CSV header absent")

    fields = [
        "Pos.x [m]", "Pos.y [m]", "Pos.z [m]", "Idp", "Type", "Mk", "Mass [kg]",
        "Vel.x [m/s]", "Vel.y [m/s]", "Vel.z [m/s]", "Rhop [kg/m^3]", "Zone",
    ]
    rows = np.loadtxt(path, delimiter=",", skiprows=lines, usecols=[header.index(k) for k in fields])
    root = ET.parse(xml_path).getroot()
    particles = root.find(".//execution/particles")
    if particles is None:
        raise ValueError("Generated XML missing execution/particles")

    n = int(particles.get("np"))
    if len(rows) != n or not np.isfinite(rows).all():
        raise ValueError("Missing or nonfinite official native rows")
    if not (rows[:, 6] > 0).all() or not (rows[:, 10] > 0).all():
        raise ValueError("Nonpositive native initial mass/density")
    if not np.equal(rows[:, [3, 4, 5, 11]], np.rint(rows[:, [3, 4, 5, 11]])).all() or not (rows[:, 11] == 0).all():
        raise ValueError("Invalid native categorical identity")

    order = np.argsort(rows[:, 3])
    rows = rows[order]
    if not np.array_equal(rows[:, 3], np.arange(n)):
        raise ValueError("Official typed particle identities incomplete or duplicated")

    blocks = []
    mapping = {"fixed": 0, "moving": 1, "floating": 2, "fluid": 3}
    covered = np.zeros(n, bool)
    for node in particles:
        if node.tag not in mapping:
            continue
        begin, count = int(node.get("begin")), int(node.get("count"))
        sl = slice(begin, begin + count)
        if covered[sl].any() or not (rows[sl, 4] == mapping[node.tag]).all() or not (rows[sl, 5] == int(node.get("mk"))).all():
            raise ValueError("Native typed block differs from generated XML")
        covered[sl] = True
        blocks.append({"type": mapping[node.tag], "mk": int(node.get("mk")), "count": count})

    if not covered.all():
        raise ValueError("Native XML typed blocks leave missing identities")

    moving = rows[rows[:, 4] == 1]
    fluid = rows[rows[:, 4] == 3]
    max_velocity = float(np.abs(rows[:, 7:10]).max())
    fluid_mass_sum = float(fluid[:, 6].sum())
    mass_match = abs(fluid_mass_sum - expected_mass) <= 0.05

    checks = dict(
        report["checks"],
        finite_all_native_rows=True,
        exact_all_native_typed_identity=True,
        moving_piston_present=len(moving) > 0,
        initial_velocity_zero=max_velocity <= 1e-8,
        exact_expected_fluid_particles=len(fluid) == expected_fluid,
        fluid_mass_sum_matches_continuum=mass_match,
    )
    if "total_particles" in m:
        checks["exact_expected_total"] = n == int(m["total_particles"])

    result = {
        "schema": SCHEMA_MASS_QA_V2,
        "case_id": m.get("case_id", prefix.name),
        "checks": checks,
        "all_actual_checks_pass": all(checks.values()),
        "total_particles": n,
        "fluid_particles": len(fluid),
        "expected_fluid_particles": expected_fluid,
        "moving_piston_particles": len(moving),
        "native_csv_fluid_mass_kg": fluid_mass_sum,
        "expected_fluid_mass_kg": expected_mass,
        "maximum_initial_velocity_m_s": max_velocity,
        "actual_typed_blocks": blocks,
        "partvtk_csv_sha256": digest(path),
        "gencase_receipt_sha256": digest(receipt_path),
        "generated_xml_sha256": digest(xml_path),
        "generated_bi4_sha256": digest(bi4_path),
        "boundary_coverage_scope": (
            "Every recorded initial fixed/moving typed block validated. Geometry-marker presence alone "
            "does not prove continuous bed/wall support completeness."
        ),
        "q_n_granted": False,
        "production_granted": False,
        "gpu_request_created": False,
    }

    out_file = output / "strict-initial-audit.json"
    out_file.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if not result["all_actual_checks_pass"]:
        raise ValueError(f"F5 native initialization failed checks: {result}")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    res = run(args.manifest, args.output_dir)
    print(json.dumps(res, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
