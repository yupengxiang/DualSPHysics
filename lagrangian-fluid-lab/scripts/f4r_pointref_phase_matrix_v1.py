#!/usr/bin/env python3
"""Prepare the predeclared F4R per-resolution pointref GenCase-only matrix."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
import xml.etree.ElementTree as ET


REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = (
    REPO_ROOT
    / "lagrangian-fluid-lab/campaigns/l2-multifamily/resume-c6b28c8/f4r-matrix/cases"
)
SOURCES = {
    "F4R_center_drop_pool_dp0081818_Def.xml": "d40142688493451f6c08512838d19489694c5a8de455ada9908965fd8b87cd8f",
    "F4R_offset_drop_pool_dp0081818_Def.xml": "5c39d523e5aaa1857cae2c6713ee802f906614735f8a3add580d56732fe3b555",
    "F4R_center_drop_pool_dp0075_Def.xml": "72e84a37e484b204a8cc08d0c3902c98a7903d850a9500db031eb1cf0630b399",
    "F4R_offset_drop_pool_dp0075_Def.xml": "15dce3a079400abeeed135f1adbcd084c79971e30e139306666860264deb41ff",
    "F4R_center_drop_pool_dp006_Def.xml": "1723ab90a7d19211b83f50cf7abb5149cf62ce2ea3e6709625cc1e31ef9fae71",
    "F4R_offset_drop_pool_dp006_Def.xml": "b9d8c218a5eb4c368cd0900171e92126c23681e3dbe6ac9b67f56527ed887aba",
}
DP_PHASES = {
    "0.008181818181818181": ("0.006818181818181818", "0.007727272727272727", "0.007727272727272727"),
    "0.0075": ("0", "0.005", "0.005"),
    "0.006": ("0.003", "0.005", "0.005"),
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def prepare(source: Path, expected_sha256: str, destination: Path) -> dict[str, object]:
    original = source.read_bytes()
    actual_sha256 = sha256(original)
    if actual_sha256 != expected_sha256:
        raise ValueError(f"source digest mismatch for {source.name}: {actual_sha256}")

    xml_text = original.decode("utf-8")
    if "<pointref" in xml_text:
        raise ValueError(f"source already contains pointref: {source.name}")

    matches = list(re.finditer(r'(?m)^([ \t]*)<definition dp="([^"]+)">\r?$', xml_text))
    if len(matches) != 1:
        raise ValueError(f"expected one definition element in {source.name}, got {len(matches)}")
    match = matches[0]
    dp = match.group(2)
    if dp not in DP_PHASES:
        raise ValueError(f"unregistered dp in {source.name}: {dp}")

    indent = match.group(1) + "    "
    x, y, z = DP_PHASES[dp]
    insertion = f'\n{indent}<pointref x="{x}" y="{y}" z="{z}" />'
    candidate = xml_text[: match.end()] + insertion + xml_text[match.end() :]
    ET.fromstring(candidate)
    encoded = candidate.encode("utf-8")
    destination.write_bytes(encoded)

    return {
        "source": source.relative_to(REPO_ROOT).as_posix(),
        "source_sha256": actual_sha256,
        "candidate": destination.name,
        "candidate_sha256": sha256(encoded),
        "dp_m": float(dp),
        "pointref_m": [float(x), float(y), float(z)],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "candidate-inputs.json"
    if manifest_path.exists():
        raise FileExistsError(f"refusing to overwrite {manifest_path}")
    candidates_dir = output_dir / "inputs"
    candidates_dir.mkdir(exist_ok=False)

    records = []
    for name, expected_sha256 in SOURCES.items():
        source = SOURCE_DIR / name
        candidate_name = name.replace("_Def.xml", "_pointref_Def.xml")
        records.append(prepare(source, expected_sha256, candidates_dir / candidate_name))

    manifest = {
        "schema": "core.cfd.f4r_pointref_phase_matrix_inputs.v1",
        "qualification_claim": "none",
        "solver_authorized": False,
        "phase_rule": "per-dp axiswise phase maximizing the precomputed minimum inward endpoint clearance for the pool box",
        "cases": records,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(manifest_path)
    for record in records:
        print(
            record["candidate"],
            "dp=", record["dp_m"],
            "pointref=", record["pointref_m"],
            "sha256=", record["candidate_sha256"],
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
