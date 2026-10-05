#!/usr/bin/env python3
"""Metadata/source-only checks for the C082 layer-orientation correction pack."""
from pathlib import Path
import json
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
source = ROOT / "candidate_source/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082R1_Def.xml"
root = ET.parse(source).getroot()
main = root.find("./casedef/geometry/commands/mainlist")
assert main is not None
extrudes = main.findall("drawextrude")
assert len(extrudes) == 1
ex = extrudes[0]
assert ex.attrib.get("closed") == "true"
layers = ex.find("layers")
assert layers is not None and layers.attrib.get("vdp") == "0,-1,-2,-3,-4"
assert not main.findall("drawfilestl")
assert not [e for e in main if e.tag.lower().startswith("erase")]
clip = main.find("clipplane")
assert clip is not None
assert clip.find("point").attrib == {"x": "2.00", "y": "0.00", "z": "0.00"}
assert clip.find("vector").attrib == {"x": "0.28", "y": "0.00", "z": "-1.00"}
fluid_i = next(i for i, e in enumerate(main) if e.tag == "drawbox" and e.attrib.get("cmt") == "initial_fluid_equilibrium_cell_centres_dp020")
extrude_i = next(i for i, e in enumerate(main) if e is ex)
assert extrude_i < fluid_i
binding = json.loads((ROOT / "proposed-gencase-binding.json").read_text())
assert binding["expected_fluid"] is None
assert binding["execution_policy"]["launch_allowed"] is False
report = json.loads((ROOT / "root225-gencase-metadata.json").read_text())
assert report["wrapper_returncode"] == 1
assert report["binary_completed_code"] == 0
assert report["actual_particle_counts_from_generated_xml_text"]["fluid"] == 31658
print("fresh083 source/metadata checks passed; no arrays or jobs accessed")
