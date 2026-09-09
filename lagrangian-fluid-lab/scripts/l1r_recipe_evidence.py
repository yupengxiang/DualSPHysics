"""Source/generated/runtime recipe differences and measured normal interfaces."""

import json, re, xml.etree.ElementTree as ET
import numpy as np
from scipy.spatial import cKDTree
from scripts.l1r_continuation_evidence import *


def summary(path):
    root = ET.parse(path).getroot()
    result = {
        n.get("key"): n.get("value")
        for n in root.findall(".//execution/parameters/parameter")
    }
    for n in root.findall(".//constantsdef/*"):
        result["constant." + n.tag] = dict(n.attrib)
    result["simulationdomain"] = (
        ET.tostring(root.find(".//simulationdomain"), encoding="unicode")
        if root.find(".//simulationdomain") is not None
        else None
    )
    result["normal_definition"] = (
        ET.tostring(root.find(".//normals"), encoding="unicode")
        if root.find(".//normals") is not None
        else None
    )
    return result


def main():
    sources = {
        "Q1_source": LAB
        / "vendor/official/DualSPHysics_v5.4/examples/mdbc/04_Dambreak/CaseDamBreak3D_Def.xml",
        "Q2_source": next(q2.CASE_ROOT.glob("*Def.xml")),
    }
    for f in OUT.glob("*-PREPARED.json"):
        d = json.loads(f.read_text())
        sources[d["case_id"]] = LAB / d.get(
            "candidate_definition", d["source_definition"]["path"]
        )
    results = {
        k: {"source": q2.fingerprint(p), "settings": summary(p)}
        for k, p in sources.items()
    }
    for label, pattern in [
        ("Q1", "q1-official"),
        ("Q2", "q2-mdbc-bridge"),
        ("continuation", "continuation"),
        ("branches", "branches"),
    ]:
        for p in (LAB / "campaigns/l1-resume/runs" / pattern).glob(
            "*/attempts/*/Run.out"
        ):
            text = p.read_text()
            results[str(p.parent.parent.parent.name) + "_runtime"] = {
                "source": q2.fingerprint(p),
                "actual_reported_fields": {
                    m[0]: m[1]
                    for m in re.findall(
                        r"^\s*([A-Za-z][A-Za-z0-9 /.-]*)=(.*)$", text, re.M
                    )
                },
                "unreported_semantics": "unknown; not inferred from names",
            }
    write("RECIPE-DIFFERENCES.json", results)
    geometries = {}
    for label, root in [("Q2", q2.RAW_ROOT)] + [
        (f.parent.name, f.parent)
        for f in (LAB / "campaigns/l1-resume/artifacts/continuation").glob(
            "*/*_Bound.vtk"
        )
    ]:
        b = vtk_arrays(next(root.glob("*_Bound.vtk")))
        f = vtk_arrays(next(root.glob("*_Fluid.vtk")))
        p = b["points"]
        n = b["Normal"]
        interface = p + n
        ghost = p + 2 * n
        kernel = 0.034641016 if label == "Q2" else 0.04
        support = cKDTree(f["points"]).query_ball_point(
            ghost, kernel, return_length=True, workers=1
        )
        wet = support > 0
        inner = (
            (p[:, 2] < 0.001)
            & (p[:, 0] > 0.05)
            & (p[:, 0] < 1.15)
            & (p[:, 1] > 0.05)
            & (p[:, 1] < 0.35)
        )
        geometries[label] = {
            "boundary_count": len(p),
            "fluid_count": len(f["points"]),
            "fluid_volume_m3": len(f["points"]) * 0.01**3,
            "fluid_mass_kg": len(f["points"]) * 0.001,
            "fluid_com_m": f["points"].mean(0).tolist(),
            "fluid_bounds_m": [
                f["points"].min(0).tolist(),
                f["points"].max(0).tolist(),
            ],
            "interior_bottom_layers_m": np.unique(np.round(p[inner, 2], 7)).tolist(),
            "reconstructed_bottom_interface_m": np.unique(
                np.round(interface[inner, 2], 7)
            ).tolist(),
            "bottom_ghost_z_m": np.unique(np.round(ghost[inner, 2], 7)).tolist(),
            "all_normal_vectors_nonzero": bool(
                np.all(np.linalg.norm(n, axis=1) > 1e-10)
            ),
            "initial_ghost_fluid_support": {
                "radius_m": kernel,
                "wet_nodes": int(wet.sum()),
                "dry_nodes": int((~wet).sum()),
                "wet_min_neighbors": int(support[wet].min()) if wet.any() else None,
                "wet_median_neighbors": (
                    float(np.median(support[wet])) if wet.any() else None
                ),
                "semantics": "geometric initial neighbor count only, not proof of matrix conditioning or dynamic support",
            },
            "canonical_bottom_m": 0,
            "interface_matches_declared_bottom": bool(
                np.all(abs(interface[inner, 2]) < 1e-6)
            ),
        }
    write("GEOMETRY-AND-INITIAL-STATE.json", geometries)


if __name__ == "__main__":
    main()
