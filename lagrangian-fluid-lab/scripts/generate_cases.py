#!/usr/bin/env python3
"""Generate low-cost mechanism probes for the Lagrangian fluid exploration lab."""

from __future__ import annotations

import json
from pathlib import Path
import xml.etree.ElementTree as ET


LAB_ROOT = Path(__file__).resolve().parents[1]
CASE_ROOT = LAB_ROOT / "cases"


def box(point, size, mk=0, velocity=None):
    return {"point": point, "size": size, "mk": mk, "velocity": velocity}


def obstacle(point, size, mk=1):
    return {"point": point, "size": size, "mk": mk}


BASE_TANK = (1.20, 0.40, 0.60)

CASES = [
    dict(id="C0_static_tank", family="C0", mechanism="hydrostatic-rest",
         fluid=[box((0.10, 0.04, 0.04), (1.00, 0.32, 0.28))], time=0.20),
    dict(id="C0_impulse_tank", family="C0", mechanism="single-direction-impulse",
         fluid=[box((0.10, 0.04, 0.04), (0.65, 0.32, 0.28), velocity=(0.5, 0, 0))], time=0.35),
    dict(id="F1_dam_break_plain", family="F1", mechanism="collapse-runup-return",
         fluid=[box((0.04, 0.04, 0.04), (0.34, 0.32, 0.46))], time=0.55),
    dict(id="F1_center_obstacle", family="F1", mechanism="split-around-obstacle",
         fluid=[box((0.04, 0.04, 0.04), (0.34, 0.32, 0.46))],
         obstacles=[obstacle((0.68, 0.15, 0), (0.12, 0.10, 0.34))], time=0.60),
    dict(id="F1_twin_obstacle", family="F1", mechanism="multi-path-split-remerge",
         fluid=[box((0.04, 0.04, 0.04), (0.34, 0.32, 0.46))],
         obstacles=[obstacle((0.62, 0.06, 0), (0.10, 0.10, 0.30)),
                    obstacle((0.78, 0.24, 0), (0.10, 0.10, 0.30), 2)], time=0.65),
    dict(id="F1_opposing_columns", family="F1", mechanism="collapse-collision-reseparation",
         fluid=[box((0.04, 0.04, 0.04), (0.25, 0.32, 0.42), 0),
                box((0.91, 0.04, 0.04), (0.25, 0.32, 0.42), 1)], time=0.65),
    dict(id="F2_airborne_slug_centered", family="F2", mechanism="transfer-catch-spill",
         fluid=[box((0.10, 0.12, 0.35), (0.26, 0.16, 0.16), 0, (1.1, 0, 0))],
         obstacles=[obstacle((0.70, 0.04, 0), (0.06, 0.32, 0.20)),
                    obstacle((1.08, 0.04, 0), (0.06, 0.32, 0.20), 2)], time=0.65),
    dict(id="F2_airborne_slug_offset", family="F2", mechanism="offset-transfer-partial-capture",
         fluid=[box((0.10, 0.04, 0.35), (0.26, 0.16, 0.16), 0, (1.1, 0.35, 0))],
         obstacles=[obstacle((0.70, 0.04, 0), (0.06, 0.32, 0.20)),
                    obstacle((1.08, 0.04, 0), (0.06, 0.32, 0.20), 2)], time=0.65),
    dict(id="F2_two_source_layers", family="F2", mechanism="source-layer-destination-allocation",
         fluid=[box((0.10, 0.12, 0.35), (0.13, 0.16, 0.16), 0, (1.15, 0, 0)),
                box((0.27, 0.12, 0.35), (0.13, 0.16, 0.16), 1, (0.95, 0, 0))],
         obstacles=[obstacle((0.70, 0.04, 0), (0.06, 0.32, 0.20)),
                    obstacle((1.08, 0.04, 0), (0.06, 0.32, 0.20), 2)], time=0.65),
    dict(id="F3_impulse_slosh", family="F3", mechanism="free-surface-phase-memory",
         fluid=[box((0.10, 0.04, 0.04), (1.00, 0.32, 0.25), 0, (0.65, 0, 0))], time=0.90),
    dict(id="F3_baffled_slosh", family="F3", mechanism="baffle-exchange-repeated-impact",
         fluid=[box((0.10, 0.04, 0.04), (1.00, 0.32, 0.25), 0, (0.65, 0, 0))],
         obstacles=[obstacle((0.58, 0.04, 0), (0.04, 0.32, 0.19))], time=0.90),
    dict(id="F3_transverse_slosh", family="F3", mechanism="transverse-slosh",
         fluid=[box((0.10, 0.04, 0.04), (1.00, 0.32, 0.25), 0, (0, 0.45, 0))], time=0.75),
    dict(id="F4_head_on_columns", family="F4", mechanism="head-on-liquid-column-collision",
         fluid=[box((0.12, 0.10, 0.24), (0.22, 0.20, 0.18), 0, (1.0, 0, 0)),
                box((0.86, 0.10, 0.24), (0.22, 0.20, 0.18), 1, (-1.0, 0, 0))], time=0.55),
    dict(id="F4_oblique_columns", family="F4", mechanism="oblique-collision-deflection",
         fluid=[box((0.12, 0.04, 0.24), (0.22, 0.16, 0.18), 0, (1.0, 0.25, 0)),
                box((0.86, 0.20, 0.24), (0.22, 0.16, 0.18), 1, (-1.0, -0.25, 0))], time=0.55),
    dict(id="F4_drop_onto_pool", family="F4", mechanism="drop-pool-impact-reentry",
         fluid=[box((0.08, 0.04, 0.04), (1.04, 0.32, 0.14), 0),
                box((0.47, 0.12, 0.40), (0.26, 0.16, 0.14), 1, (0, 0, -0.5))], time=0.60),
    dict(id="F5_low_weir", family="F5", mechanism="runup-overtop-return",
         fluid=[box((0.04, 0.04, 0.04), (0.48, 0.32, 0.38))],
         obstacles=[obstacle((0.64, 0.04, 0), (0.10, 0.32, 0.23))], time=0.75),
    dict(id="F5_notched_weir", family="F5", mechanism="localized-overtopping-source-map",
         fluid=[box((0.04, 0.04, 0.04), (0.48, 0.32, 0.38))],
         obstacles=[obstacle((0.64, 0.04, 0), (0.10, 0.10, 0.27)),
                    obstacle((0.64, 0.26, 0), (0.10, 0.10, 0.27), 2)], time=0.75),
    dict(id="F5_wet_bed_overtop", family="F5", mechanism="overtop-reentry-wet-bed",
         fluid=[box((0.04, 0.04, 0.04), (0.48, 0.32, 0.38), 0),
                box((0.78, 0.04, 0.04), (0.36, 0.32, 0.10), 1)],
         obstacles=[obstacle((0.64, 0.04, 0), (0.10, 0.32, 0.23))], time=0.80),
    dict(id="F6_floating_box", family="F6", mechanism="buoyancy-heave-drift",
         fluid=[box((0.06, 0.04, 0.04), (1.08, 0.32, 0.30))],
         floaters=[dict(point=(0.48, 0.12, 0.27), size=(0.24, 0.16, 0.16), mk=5, rhop=500)], time=0.80),
    dict(id="F6_heavy_box_entry", family="F6", mechanism="water-entry-momentum-exchange",
         fluid=[box((0.06, 0.04, 0.04), (1.08, 0.32, 0.22))],
         floaters=[dict(point=(0.50, 0.12, 0.39), size=(0.20, 0.16, 0.16), mk=5, rhop=1400,
                        velocity=(0, 0, -0.8))], time=0.60),
    dict(id="F6_twin_floaters", family="F6", mechanism="multi-body-fluid-mediated-interaction",
         fluid=[box((0.06, 0.04, 0.04), (1.08, 0.32, 0.30))],
         floaters=[dict(point=(0.28, 0.12, 0.27), size=(0.20, 0.16, 0.16), mk=5, rhop=600),
                   dict(point=(0.72, 0.12, 0.27), size=(0.20, 0.16, 0.16), mk=6, rhop=800)], time=0.80),
]


def sub(parent, tag, **attrs):
    return ET.SubElement(parent, tag, {k: str(v) for k, v in attrs.items()})


def draw_box(commands, *, point, size, fill, kind, mk):
    sub(commands, f"setmk{kind}", mk=mk)
    node = sub(commands, "drawbox")
    sub(node, "boxfill").text = fill
    sub(node, "point", x=point[0], y=point[1], z=point[2])
    sub(node, "size", x=size[0], y=size[1], z=size[2])


def add_void(commands, *, point, size):
    sub(commands, "setmkvoid")
    node = sub(commands, "drawbox")
    sub(node, "boxfill").text = "solid"
    sub(node, "point", x=point[0], y=point[1], z=point[2])
    sub(node, "size", x=size[0], y=size[1], z=size[2])


def generate(case):
    case_dir = CASE_ROOT / case["family"] / case["id"]
    case_dir.mkdir(parents=True, exist_ok=True)
    name = case["id"]
    root = ET.Element("case")
    casedef = sub(root, "casedef")
    constants = sub(casedef, "constantsdef")
    sub(constants, "gravity", x=0, y=0, z=-9.81)
    sub(constants, "rhop0", value=1000)
    sub(constants, "rhopgradient", value=2)
    sub(constants, "hswl", value=0, auto="true")
    sub(constants, "gamma", value=7)
    sub(constants, "speedsystem", value=0, auto="true")
    sub(constants, "coefsound", value=20)
    sub(constants, "speedsound", value=0, auto="true")
    sub(constants, "coefh", value=1.0)
    sub(constants, "cflnumber", value=0.2)
    sub(casedef, "mkconfig", boundcount=200, fluidcount=16)

    geometry = sub(casedef, "geometry")
    definition = sub(geometry, "definition", dp=case.get("dp", 0.04))
    sub(definition, "pointmin", x=-0.12, y=-0.12, z=-0.12)
    sub(definition, "pointmax", x=1.35, y=0.55, z=0.85)
    commands_root = sub(geometry, "commands")
    commands = sub(commands_root, "mainlist")
    sub(commands, "setshapemode").text = "dp | bound"
    sub(commands, "setdrawmode", mode="full")

    for fluid in case["fluid"]:
        draw_box(commands, point=fluid["point"], size=fluid["size"], fill="solid",
                 kind="fluid", mk=fluid["mk"])
    draw_box(commands, point=(0, 0, 0), size=case.get("tank", BASE_TANK),
             fill="bottom | left | right | front | back", kind="bound", mk=0)
    for obs in case.get("obstacles", []):
        add_void(commands, point=obs["point"], size=obs["size"])
        draw_box(commands, point=obs["point"], size=obs["size"],
                 fill="top | left | right | front | back", kind="bound", mk=obs["mk"])
    for floating in case.get("floaters", []):
        add_void(commands, point=floating["point"], size=floating["size"])
        draw_box(commands, point=floating["point"], size=floating["size"],
                 fill="solid", kind="bound", mk=floating["mk"])

    moving = [f for f in case["fluid"] if f.get("velocity")]
    if moving:
        initials = sub(casedef, "initials")
        for fluid in moving:
            vx, vy, vz = fluid["velocity"]
            sub(initials, "velocity", mkfluid=fluid["mk"], x=vx, y=vy, z=vz)

    if case.get("floaters"):
        floatings = sub(casedef, "floatings")
        for floating in case["floaters"]:
            node = sub(floatings, "floating", mkbound=floating["mk"], rhopbody=floating["rhop"])
            if floating.get("velocity"):
                vx, vy, vz = floating["velocity"]
                sub(node, "linearvelini", x=vx, y=vy, z=vz)

    execution = sub(root, "execution")
    params = sub(execution, "parameters")
    values = [
        ("SavePosDouble", 0), ("StepAlgorithm", 1), ("VerletSteps", 40),
        ("Kernel", 2), ("ViscoTreatment", 1), ("Visco", 0.08),
        ("ViscoBoundFactor", 1), ("DensityDT", 2), ("DensityDTvalue", 0.1),
        ("Shifting", 0), ("RigidAlgorithm", 1), ("FtPause", 0),
        ("CoefDtMin", 0.05), ("DtIni", 0), ("DtMin", 0), ("DtFixed", 0),
        ("DtAllParticles", 0), ("TimeMax", case["time"]), ("TimeOut", 0.05),
        ("MinFluidStop", 0), ("RhopOutMin", 700), ("RhopOutMax", 1300),
    ]
    for key, value in values:
        sub(params, "parameter", key=key, value=value)
    domain = sub(params, "simulationdomain")
    sub(domain, "posmin", x="default - 25%", y="default - 25%", z="default - 25%")
    sub(domain, "posmax", x="default + 25%", y="default + 25%", z="default + 75%")

    ET.indent(root, space="    ")
    path = case_dir / f"{name}_Def.xml"
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    return {
        "id": name,
        "family": case["family"],
        "mechanism": case["mechanism"],
        "definition": str(path.relative_to(LAB_ROOT)),
        "dp": case.get("dp", 0.04),
        "time_max": case["time"],
        "shifting": 0,
        "status": "defined",
    }


def main():
    records = [generate(case) for case in CASES]
    manifest = {
        "schema_version": 1,
        "purpose": "low-cost breadth-first Lagrangian fluid mechanism exploration",
        "case_count": len(records),
        "cases": records,
    }
    (CASE_ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"generated {len(records)} case definitions")


if __name__ == "__main__":
    main()
