#!/usr/bin/env python3
"""Metadata/XML-only preflight for F5 fresh090 C082S1."""
from __future__ import annotations
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

CASE = "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1"
ROOT = Path(__file__).resolve().parents[1]

def req(v, m):
    if not v: raise AssertionError(m)

def main():
    source = ROOT / "source" / (CASE + "_Def.xml")
    root = ET.parse(source).getroot()
    req(root.tag == "case", "source XML root")
    definition = root.find("./casedef/geometry/definition")
    req(definition is not None and definition.get("dp") == "0.02", "dp")
    commands = root.findall("./casedef/geometry/commands/mainlist/*")
    tags = [node.tag for node in commands]
    fluid = [node for node in commands if node.tag == "drawbox" and node.get("cmt", "").startswith("c082s1_initial_fluid")]
    req(len(fluid) == 1, "exactly one C082S1 fluid drawbox")
    req(fluid[0].findtext("boxfill") == "solid", "fluid drawbox is not solid")
    point = fluid[0].find("point"); size = fluid[0].find("size")
    req(point is not None and [float(point.get(k)) for k in ("x","y","z")] == [0.01,-0.14,0.01], "fluid point")
    req(size is not None and [float(size.get(k)) for k in ("x","y","z")] == [3.42,0.28,0.38], "fluid size")
    req(not any(node.tag == "fillbox" for node in commands), "void/fillbox remains in source")
    ci = next(i for i, node in enumerate(commands) if node.tag == "clipplane")
    fi = next(i for i, node in enumerate(commands) if node is fluid[0])
    cr = next(i for i, node in enumerate(commands) if node.tag == "clipreset")
    req(ci < fi < cr, "fluid draw order relative to clipplane/reset")
    bed = [node for node in commands if node.tag == "drawextrude" and node.get("closed") == "true"]
    req(len(bed) == 1, "closed analytic bed")
    ext = bed[0].find("extrude")
    req(ext is not None and float(ext.get("y")) == 0.44, "bed extrusion")
    layers = bed[0].find("layers")
    req(layers is not None and layers.get("vdp") == "0,-1,-2,-3,-4", "bed layers")
    bound = next((node for node in commands if node.tag == "setmkbound" and node.get("mk") == "40"), None)
    req(bound is not None, "source mkbound40")
    motion = root.find("./casedef/motion/objreal/mvpredef")
    req(motion is not None and motion.get("duration") == "16", "motion duration")
    outdt = root.find("./execution/special/gauges/default/_outputdt")
    req(outdt is not None and outdt.get("value") == "0.02", "output cadence")
    for name in ("gencase-request.json","initial-qa-request.json","central-bed-coverage-request.json","short-native-qualification-request.json","typed-conversion-request-template.json","xmf-request-template.json","short-bed-audit-request.json"):
        data=json.loads((ROOT/"requests"/name).read_text())
        req(data.get("execution_allowed") is False and data.get("launch_allowed") is False, f"disabled {name}")
        req(data.get("full801_authorized") is False, f"full801 disabled {name}")
    qa=json.loads((ROOT/"bindings"/"initial-qa-binding-template.json").read_text())
    req(all(value is None for value in qa["actual_counts"].values()), "QA template prefilled counts")
    req(json.loads((ROOT/"requests"/"short-native-qualification-request.json").read_text())["expected_fluid_particles"] is None, "short template prefilled fluid count")
    print(json.dumps({"status":"preflight_pass","source":str(source),"nominal_fluid_lattice_axes":[172,15,20],"future_counts":"root-bind-from-actual-gencase","jobs_started":False,"arrays_opened":False}, sort_keys=True))

if __name__ == "__main__":
    main()
