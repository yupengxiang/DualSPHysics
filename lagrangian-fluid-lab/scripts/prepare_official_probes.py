#!/usr/bin/env python3
"""Prepare coarse, short probes derived from official DualSPHysics examples."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET


LAB_ROOT = Path(__file__).resolve().parents[1]
OFFICIAL = LAB_ROOT / "vendor" / "official" / "DualSPHysics_v5.4"
EXAMPLES = OFFICIAL / "examples"
BIN = OFFICIAL / "bin" / "linux"
GENCASE = BIN / "GenCase_linux64"
REPORT = LAB_ROOT / "reports" / "runtime" / "official-prepare-summary.json"


PROBES = [
    dict(id="O3_sloshing_motion", family="F3", mechanism="prescribed-moving-tank",
         source="main/05_SloshingTank", base="CaseSloshingMotion", dp=0.010, tmax=1.0, tout=0.10),
    dict(id="O3_sloshing_acc", family="F3", mechanism="accelerated-frame-sloshing",
         source="main/05_SloshingTank", base="CaseSloshingAcc", dp=0.010, tmax=1.0, tout=0.10),
    dict(id="O5_solitary_wave", family="F5", mechanism="solitary-wave-propagation",
         source="main/16_SolitaryWaves", base="CaseSolitaryWave_Boussinesq", dp=0.020, tmax=2.0, tout=0.20),
    dict(id="O5_wave_runup", family="F5", mechanism="wave-runup-moving-piston",
         source="main/17_WaveRunup", base="CaseWaveRunup", dp=0.040, tmax=4.0, tout=0.40),
    dict(id="O5_wave_runup_refined", family="F5", mechanism="wave-runup-moving-piston-refined",
         source="main/17_WaveRunup", base="CaseWaveRunup", dp=0.025, tmax=4.0, tout=0.40),
    dict(id="O6_floating_box", family="F6", mechanism="free-floating-body-six-dof",
         source="main/11_Floating", base="CaseFloating", dp=0.40, tmax=1.0, tout=0.10),
    dict(id="O6_floating_sphere", family="F6", mechanism="sphere-heave-decay",
         source="main/11_Floating", base="CaseFloatingSphereVal2D", dp=0.10, tmax=1.0, tout=0.10),
    dict(id="O4_impinging_jet", family="F4", mechanism="open-boundary-impinging-jet",
         source="inletoutlet/08_ImpingingJet", base="CaseJet2D", dp=0.001, tmax=0.03, tout=0.003),
    dict(id="O6_falling_wedge_vres", family="F6", mechanism="variable-resolution-water-entry",
         source="vresolution/04_FallingWedge2D", base="CaseFallingWedge2DVRes", dp=0.020,
         tmax=0.025, tout=0.0025, solver_flags=["-vres"]),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", nargs="*", help="Only prepare these case ids and merge the report")
    args = parser.parse_args()
    selected = set(args.cases or [])
    probes = [probe for probe in PROBES if not selected or probe["id"] in selected]
    unknown = selected - {probe["id"] for probe in PROBES}
    if unknown:
        parser.error(f"unknown case ids: {', '.join(sorted(unknown))}")
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = f"{BIN}:{env.get('LD_LIBRARY_PATH', '')}"
    results = []
    for probe in probes:
        source = EXAMPLES / probe["source"]
        generated = LAB_ROOT / "cases" / "official" / probe["id"] / "generated"
        generated.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, generated, dirs_exist_ok=True)
        target = generated / probe["id"]
        proc = subprocess.run([
            str(GENCASE), str(generated / f"{probe['base']}_Def"), str(target),
            f"-dp:{probe['dp']}", "-save:all",
        ], cwd=generated, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        # GenCase may create zero-byte placeholders for external time-series
        # files when input and output live together. Restore authoritative
        # example assets after generation so the solver reads the real data.
        for source_file in source.rglob("*"):
            if source_file.is_file():
                destination = generated / source_file.relative_to(source)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_file, destination)
        log = generated / "gencase.log"
        log.write_text(proc.stdout)
        fluid = re.search(r"Fluid\.\.\.\.:\s+([0-9,]+)", proc.stdout)
        total = re.search(r"Total particles:\s+([0-9,]+)", proc.stdout)
        shifting = None
        output_xml = target.with_suffix(".xml")
        if output_xml.is_file():
            tree = ET.parse(output_xml)
            shifting = next((int(node.get("value")) for node in tree.findall(".//parameter")
                             if node.get("key") == "Shifting"), None)
        result = {
            **probe,
            "status": "prepared" if proc.returncode == 0 else "prepare_failed",
            "returncode": proc.returncode,
            "fluid_particles": int(fluid.group(1).replace(",", "")) if fluid else None,
            "total_particles": int(total.group(1).replace(",", "")) if total else None,
            "shifting": shifting,
            "case_prefix": str(target.relative_to(LAB_ROOT)),
            "log": str(log.relative_to(LAB_ROOT)),
        }
        results.append(result)
        print(f"{probe['id']:26s} {result['status']:14s} fluid={result['fluid_particles']} total={result['total_particles']}")
    if selected and REPORT.is_file():
        previous = json.loads(REPORT.read_text()).get("cases", [])
        results = [record for record in previous if record["id"] not in selected] + results
        results.sort(key=lambda record: record["id"])
    summary = {
        "schema_version": 1,
        "upstream_package": "DualSPHysics_v5.4.3",
        "prepared": sum(r["status"] == "prepared" for r in results),
        "failed": sum(r["status"] != "prepared" for r in results),
        "cases": results,
    }
    REPORT.write_text(json.dumps(summary, indent=2) + "\n")
    print(f"prepared={summary['prepared']} failed={summary['failed']}")
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
