"""Bounded official-strategy candidate on explicitly checked L1 geometry."""

import argparse, json, subprocess, time, hashlib, fcntl, os
from datetime import datetime, timezone
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np
from scripts import l1r_q2_mdbc_bridge as q2
from scripts import r5_f1_solver_gate as gate
from scripts.l1r_continuation_evidence import (
    LAB,
    OUT,
    write,
    vtk_arrays,
    runtime_domain,
    ledger,
)


def prepare(name, tmax, cfl, half=False):
    saved = OUT / (name + "-PREPARED.json")
    if saved.exists():
        existing = json.loads(saved.read_text())
        if existing.get("time_max_s") != tmax or existing.get("cfl_number") != cfl:
            raise ValueError(
                "case ID already bound to different parameters; use a new revision ID"
            )
        return existing
    dest = LAB / "campaigns/l1-resume/artifacts/continuation" / name
    dest.mkdir(parents=True, exist_ok=True)
    source = next(q2.CASE_ROOT.glob("*_Def.xml"))
    tree = ET.parse(source)
    root = tree.getroot()
    official = ET.parse(
        LAB
        / "vendor/official/DualSPHysics_v5.4/examples/mdbc/04_Dambreak/CaseDamBreak3D_Def.xml"
    ).getroot()
    # Adopt complete official constants/parameters, explicitly retaining the
    # comparable physical initial water column and conservative output/CFL.
    import copy

    case = root.find("casedef")
    case.remove(case.find("constantsdef"))
    case.insert(0, copy.deepcopy(official.find(".//constantsdef")))
    root.find(".//constantsdef/cflnumber").set("value", str(cfl))
    params = root.find(".//execution/parameters")
    params.clear()
    for node in official.find(".//execution/parameters"):
        params.append(copy.deepcopy(node))
    for k, v in [("TimeMax", tmax), ("TimeOut", 0.001), ("SavePosDouble", 2)]:
        q2.l1._set_parameter(root, k, v)
    # Predeclare physical interfaces at 0/1.2/0.4. Boundary nodes are one dp
    # outside, normals point to the canonical surface; no trajectory fitting.
    for box in root.findall('.//list[@name="GeometryForNormals"]/drawbox'):
        box.find("layers").set("vdp", "0")
    box = next(
        b
        for b in root.findall(".//mainlist/drawbox")
        if "bottom" in (b.findtext("boxfill") or "")
    )
    box.find("point").attrib.update(x="-0.01", y="-0.01", z="-0.01")
    box.find("size").attrib.update(x="1.22", y="0.42", z="0.61")
    if half:
        grid = root.find(".//geometry/definition")
        phase = grid.find("pointref")
        if phase is None:
            phase = ET.SubElement(grid, "pointref")
        phase.attrib.update(x="-0.005", y="-0.005", z="-0.005")
        box.find("point").attrib.update(x="-0.005", y="-0.005", z="-0.005")
        box.find("size").attrib.update(x="1.21", y="0.41", z="0.605")
    root.find(".//normals/norgeometry/distanceh").set("v", "3.0")
    definition = dest / (name + "_Def.xml")
    ET.indent(tree)
    tree.write(definition, encoding="utf-8", xml_declaration=True)
    prefix = dest / name
    start = time.monotonic()
    p = subprocess.run(
        [str(q2.GENCASE), str(definition.with_suffix("")), str(prefix), "-save:all"],
        cwd=dest,
        env=q2.environment(cpu=True),
        capture_output=True,
        text=True,
        timeout=600,
    )
    (dest / "gencase.log").write_text(p.stdout + p.stderr)
    if p.returncode:
        raise RuntimeError("GenCase failed")
    arrays = vtk_arrays(dest / (name + "_Bound.vtk"))
    pos = arrays["points"]
    normal = arrays["Normal"]
    interface = pos + normal
    checks = {}
    for face, (axis, side) in {
        "bottom": (2, 0),
        "left": (0, 0),
        "right": (0, 1),
        "front": (1, 0),
        "back": (1, 1),
    }.items():
        plane = (0, 0, 0)[axis] if side == 0 else (1.2, 0.4, 0.6)[axis]
        others = [i for i in range(3) if i != axis]
        mask = (pos[:, axis] < plane) if side == 0 else (pos[:, axis] > plane)
        for j in others:
            mask &= (pos[:, j] > 0.05) & (pos[:, j] < (1.2, 0.4, 0.6)[j] - 0.05)
        error = (
            float(np.max(abs(interface[mask, axis] - plane))) if mask.any() else None
        )
        checks[face] = {
            "nodes": int(mask.sum()),
            "interface_error_max_m": error,
            "normal_points_inward": bool(
                np.all(normal[mask, axis] > 0 if side == 0 else normal[mask, axis] < 0)
            ),
            "boundary_layers_m": np.unique(np.round(pos[mask, axis], 6)).tolist(),
        }
    ok = all(
        x["nodes"] and x["interface_error_max_m"] < 1e-6 and x["normal_points_inward"]
        for x in checks.values()
    ) and np.all(np.linalg.norm(normal, axis=1) > 1e-10)
    record = {
        **q2.build_record(),
        "id": name,
        "case_id": name,
        "phase": "continuation_official_strategy",
        "recipe_revision": "official_strategy_canonical_interface_v2",
        "time_max_s": tmax,
        "cfl_number": cfl,
        "generated_prefix": str(prefix.relative_to(LAB)),
        "preparation_status": "completed" if ok else "geometry_failed",
        "gencase": {
            "total_particles": len(vtk_arrays(dest / (name + "_All.vtk"))["points"]),
            "elapsed_seconds": time.monotonic() - start,
        },
        "geometry_checks": checks,
        "all_normals_nonzero": bool(np.all(np.linalg.norm(normal, axis=1) > 1e-10)),
        "source_definition": q2.fingerprint(definition),
        "numerical_strategy": "official StepAlgorithm2/Visco0.01/DensityDT3/hdp2; CFL and output explicitly overridden",
        "comparison_semantics": "system-level candidate including corrected interface representation; not single-factor causality",
    }
    record["candidate_definition"] = str(definition.relative_to(LAB))
    record["generated_xml_sha256"] = q2.sha256(prefix.with_suffix(".xml"))
    record["mdbc_recipe"].update(normal_source_layers_vdp="0", normal_distance_h=3.0)
    record["record_hash"] = hashlib.sha256(
        json.dumps(record, sort_keys=True).encode()
    ).hexdigest()
    write(name + "-PREPARED.json", record)
    return record


def main():
    from scripts.l1r_continuation_evidence import begin_activity_window

    begin_activity_window()
    p = argparse.ArgumentParser()
    p.add_argument("--name", required=True)
    p.add_argument("--time", type=float, default=0.6)
    p.add_argument("--cfl", type=float, default=0.05)
    p.add_argument("--half", action="store_true")
    p.add_argument("--run", action="store_true")
    a = p.parse_args()
    record = prepare(a.name, a.time, a.cfl, a.half)
    if not a.run:
        return
    with (OUT / "solver.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        from scripts.l1r_continuation_evidence import check_budget

        check_budget()
        ledger()
        budget = json.loads((OUT / "RESOURCE-LEDGER.json").read_text())
        if budget["qualification_attempts_remaining"] <= 6:
            raise RuntimeError("reserve F3 qualification attempts")
        if datetime.now(timezone.utc) >= datetime.fromisoformat(
            budget["conservative_expiry_utc"]
        ):
            raise RuntimeError("original activity expired")
        runs = LAB / "campaigns/l1-resume/runs/continuation"
        if len(list(runs.glob("*/attempts/*/attempt.json"))) >= 6:
            raise RuntimeError("Q2 six-attempt cap reached")
        active = subprocess.run(
            ["pgrep", "-f", "/DualSPHysics5.4_linux64"], capture_output=True, text=True
        )
        if active.stdout.strip():
            raise RuntimeError("solver already active")
        q2.CASE_ID = a.name
        q2.RUN_ROOT = runs
        q2.DATA_ROOT = LAB / "campaigns/l1-resume/data/continuation"
        q2.TIME_MAX_S = a.time
        result = q2.run_solver(record)
        write(a.name + "-SOLVER.json", result)
        ledger()
        if result["execution_status"] not in ("completed", "reused_completed"):
            return
        output = q2.DATA_ROOT / (a.name + ".h5")
        if output.exists():
            normalized = {
                "hdf5": str(output.relative_to(LAB)),
                "normalization_status": "reused_completed",
                "sha256": q2.sha256(output),
            }
        else:
            from scripts.l1r_native_normalize import normalize

            normalized = normalize(record, Path(result["attempt_directory"]), output)
        write(a.name + "-NORMALIZATION.json", normalized)
        attempt = Path(result["attempt_directory"])
        record["wall_spec"]["runtime_domain"] = runtime_domain(attempt)
        audit = gate.audit_hdf5(record, q2.DATA_ROOT / (a.name + ".h5"), attempt)
        write(a.name + "-AUDIT.json", audit)


if __name__ == "__main__":
    main()
