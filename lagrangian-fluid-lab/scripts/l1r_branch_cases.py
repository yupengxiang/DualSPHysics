"""Prepare the bounded whole-template F1 route and true 3-D F3 fallback."""

import argparse, copy, json, shutil, subprocess, time, xml.etree.ElementTree as ET
from scripts.l1r_continuation_evidence import LAB, OUT, write, vtk_arrays
from scripts import l1r_q2_mdbc_bridge as q2


def prepare(kind):
    base = LAB / "vendor/official/DualSPHysics_v5.4/examples"
    plans = (
        [("F1_OFFICIAL_NS_NOP0_dp02_t15", 0.02, "official")]
        if kind == "f1"
        else [
            (f"F3_3D_CELL2_{background}_dp{dp:g}", dp, background)
            for background in ("plain", "baffled")
            for dp in (0.03, 0.015, 0.01)
        ]
    )
    registered = []
    for name, dp, background in plans:
        name = name.replace(".", "p")
        attempted = LAB / "campaigns/l1-resume/runs/branches" / name / "attempts"
        if attempted.exists() and any(attempted.iterdir()):
            raise ValueError(
                "attempted case inputs are immutable; use a new revision ID"
            )
        source = base / (
            "mdbc/04_Dambreak/CaseDamBreak3D_NS_Def.xml"
            if kind == "f1"
            else "main/05_SloshingTank/CaseSloshingAcc_Def.xml"
        )
        dest = LAB / "campaigns/l1-resume/artifacts/branches" / name
        dest.mkdir(parents=True, exist_ok=True)
        tree = ET.parse(source)
        root = tree.getroot()
        definition = root.find(".//geometry/definition")
        definition.set("dp", str(dp))
        for k, v in [
            ("SavePosDouble", 2),
            ("TimeMax", 1.5),
            ("TimeOut", 0.01),
            ("NoPenetration", 0),
        ]:
            q2.l1._set_parameter(root, k, v)
        root.find(".//constantsdef/cflnumber").set("value", ".05")
        if kind == "f1":
            spec = {
                "container_interior": dict(
                    xmin=dp / 2,
                    xmax=3.22 - dp / 2,
                    ymin=dp / 2,
                    ymax=1 - dp / 2,
                    zmin=dp / 2,
                    zmax=1,
                ),
                "closed_faces": ["bottom", "left", "right", "front", "back"],
                "open_faces": ["top"],
                "obstacles": [
                    dict(
                        id="central",
                        xmin=0.66 - dp / 2,
                        xmax=0.82 + dp / 2,
                        ymin=0.30 - dp / 2,
                        ymax=0.70 + dp / 2,
                        zmin=dp / 2,
                        zmax=0.16 + dp / 2,
                    )
                ],
            }
            mode = "-mdbc_noslip:0"
        else:
            definition.find("pointmin").set("y", "-.2")
            definition.find("pointmax").set("y", ".2")
            definition.find("pointref").attrib.update(
                x=str(dp / 2), y=str(dp / 2), z=str(dp / 2)
            )
            commands = root.find(".//geometry/commands")
            commands.clear()
            normals_list = ET.SubElement(commands, "list", name="GeometryForNormals")
            ET.SubElement(normals_list, "setactive", drawpoints="0", drawshapes="1")
            ET.SubElement(normals_list, "setshapemode").text = "actual | bound"
            ET.SubElement(normals_list, "setnormalinvert", invert="true")
            ET.SubElement(normals_list, "setmkbound", mk="0")

            def box(parent, fill, point, size, layers=None):
                b = ET.SubElement(parent, "drawbox")
                ET.SubElement(b, "boxfill").text = fill
                ET.SubElement(b, "point", **dict(zip("xyz", map(str, point))))
                ET.SubElement(b, "size", **dict(zip("xyz", map(str, size))))
                if layers is not None:
                    ET.SubElement(b, "layers", vdp=layers)
                return b

            box(normals_list, "all^top", (-0.45, -0.09, 0), (0.9, 0.18, 0.51), "0")
            if background == "baffled":
                ET.SubElement(normals_list, "setnormalinvert", invert="false")
                ET.SubElement(normals_list, "setmkbound", mk="1")
                box(
                    normals_list,
                    "all^bottom",
                    (-0.03, -0.06, 0),
                    (0.06, 0.12, 0.06),
                    "0",
                )
            ET.SubElement(normals_list, "shapeout", file="hdp")
            ET.SubElement(normals_list, "resetdraw")
            main = ET.SubElement(commands, "mainlist")
            ET.SubElement(main, "runlist", name="GeometryForNormals")
            ET.SubElement(main, "setdrawmode", mode="full")
            ET.SubElement(main, "setmkfluid", mk="0")
            box(
                main,
                "solid",
                (-0.45 + dp / 2, -0.09 + dp / 2, dp / 2),
                (0.9 - dp, 0.18 - dp, 0.09 - dp),
            )
            ET.SubElement(main, "setmkbound", mk="0")
            box(
                main,
                "all^top",
                (-0.45 - dp / 2, -0.09 - dp / 2, -dp / 2),
                (0.9 + dp, 0.18 + dp, 0.51 + dp / 2),
                "0,1,2",
            )
            if background == "baffled":
                ET.SubElement(main, "setmkvoid")
                box(
                    main,
                    "solid",
                    (-0.03 + dp / 2, -0.06 + dp / 2, dp / 2),
                    (0.06 - dp, 0.12 - dp, 0.06 - dp),
                )
                ET.SubElement(main, "setmkbound", mk="1")
                box(
                    main,
                    "solid",
                    (-0.03 + dp / 2, -0.06 + dp / 2, dp / 2),
                    (0.06 - dp, 0.12 - dp, 0.06 - dp),
                )
            normals = ET.SubElement(root.find("casedef"), "normals", active="true")
            ng = ET.SubElement(normals, "norgeometry")
            ET.SubElement(ng, "geometryfile", file="[CaseName]_hdp_Actual.vtk")
            ET.SubElement(ng, "distanceh", v="3.0")
            q2.l1._set_parameter(root, "Boundary", 2)
            q2.l1._set_parameter(root, "SlipMode", 1)
            drive = source.parent / "CaseSloshingAccData.csv"
            shutil.copy2(drive, dest / drive.name)
            spec = {
                "container_interior": dict(
                    xmin=-0.45, xmax=0.45, ymin=-0.09, ymax=0.09, zmin=0, zmax=0.51
                ),
                "closed_faces": ["bottom", "left", "right", "front", "back"],
                "open_faces": ["top"],
                "obstacles": (
                    []
                    if background == "plain"
                    else [
                        dict(
                            id="baffle",
                            xmin=-0.03,
                            xmax=0.03,
                            ymin=-0.06,
                            ymax=0.06,
                            zmin=0,
                            zmax=0.06,
                        )
                    ]
                ),
            }
            mode = "-mdbc"
        target = dest / (name + "_Def.xml")
        ET.indent(tree)
        tree.write(target, encoding="utf-8", xml_declaration=True)
        prefix = dest / name
        start = time.monotonic()
        proc = subprocess.run(
            [str(q2.GENCASE), str(target.with_suffix("")), str(prefix), "-save:all"],
            cwd=dest,
            env=q2.environment(cpu=True),
            capture_output=True,
            text=True,
        )
        (dest / "gencase.log").write_text(proc.stdout + proc.stderr)
        if proc.returncode:
            raise RuntimeError(name + " generation failed")
        if kind == "f3":
            # GenCase may truncate same-path auxiliary copies; restore only in
            # a fresh preparation directory, then verify against source.
            shutil.copy2(drive, dest / drive.name)
            if q2.sha256(drive) != q2.sha256(dest / drive.name):
                raise RuntimeError("acceleration asset copy mismatch")
        fluid = vtk_arrays(dest / (name + "_Fluid.vtk"))["points"]
        allp = vtk_arrays(dest / (name + "_All.vtk"))["points"]
        record = {
            "id": name,
            "case_id": name,
            "family": kind.upper(),
            "background_id": background,
            "mechanism": (
                "dam-break/obstacle"
                if kind == "f1"
                else "prescribed acceleration sloshing"
            ),
            "phase": (
                "whole_official_template" if kind == "f1" else "F3_bounded_fallback"
            ),
            "dp_m": dp,
            "resolution": str(dp),
            "time_max_s": 1.5,
            "time_out_s": 0.01,
            "cfl_number": 0.05,
            "solver_mode": mode,
            "wall_spec": spec,
            "generated_prefix": str(prefix.relative_to(LAB)),
            "candidate_definition": str(target.relative_to(LAB)),
            "source_definition": q2.fingerprint(source),
            "generated_xml_sha256": q2.sha256(prefix.with_suffix(".xml")),
            "preparation_status": "completed",
            "gencase": {
                "total_particles": len(allp),
                "fluid_particles": len(fluid),
                "elapsed_seconds": time.monotonic() - start,
            },
            "initial_mass_kg": len(fluid) * 1000 * dp**3,
            "initial_com_m": fluid.mean(0).tolist(),
            "actual_y_layers": len(set(fluid[:, 1])),
            "formal_release": False,
            "comparison_scope": (
                "whole template with no-slip and NoPenetration disabled"
                if kind == "f1"
                else "true 3D finite sidewalls; official prescribed drive; new extrusion, no claim of validated 2D experiment transfer"
            ),
        }
        record["initial_target_mass_kg"] = (
            None if kind == "f1" else (14.58 if background == "plain" else 14.148)
        )
        record["initial_mass_relative_error"] = (
            None
            if kind == "f1"
            else abs(record["initial_mass_kg"] / record["initial_target_mass_kg"] - 1)
        )
        registered.append(record)
        write(name + "-PREPARED.json", record)
    write(
        ("F1-WHOLE-TEMPLATE" if kind == "f1" else "F3-REGISTERED-MATRIX") + ".json",
        {
            "records": registered,
            "new_solver_attempts": 0,
            "solver_cap": 2 if kind == "f1" else 6,
            "pre_registered_time_s": 1.5,
            "acceptance": "all saved-frame identity/lifecycle/mass/finite/finite-wall gates; F3 drive checked independently; spatial qualification not inferred from execution",
        },
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("kind", choices=["f1", "f3"])
    a = p.parse_args()
    prepare(a.kind)
