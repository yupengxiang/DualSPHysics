"""Prepare or execute one approved NoPen qualification cell, never a batch.

The historical conditional plan remains non-authorizing.  A separate immutable
execution stage binds the approved cap, passed NP01 audit and original inputs.
Stage gates must come from substantive scoring; this module checks their evidence
bindings and coverage, and does not turn an arbitrary pass boolean into a score.
"""

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import shutil
import tempfile
import xml.etree.ElementTree as ET

import numpy as np

from scripts.l1r_continuation_evidence import LAB, OUT, check_budget
from scripts.l1r_input_preflight import check_input
from scripts import l1r_q2_mdbc_bridge as q2

PLAN = "F3-NATIVE-NOPEN-QUALIFICATION-PLAN.json"
STAGE = "F3-NATIVE-NOPEN-EXECUTION-STAGE.json"
RECIPE = "F3_CELL3_NS_visco1_native_nopen"
NAME = "F3_CELL3_LONG_dp0p01_a1p000_noslip_visco1_nopen"
KEYS = ("dp_m", "amplitude", "cfl_number", "coef_dt_min", "output_interval_s")
EXPECTED = {
    "NP01": (.01, 1., .05, .05, .01),
    "NP02": (.01, 0., .05, .05, .01),
    "NP03": (.01, 1., .025, .025, .01),
    "NP04": (.01, 1., .05, .05, .002),
    "NP05": (.0075, 1., .05, .05, .01),
    "NP06": (.006, 1., .05, .05, .01),
    "NP07": (.01, .9, .05, .05, .01),
    "NP08": (.0075, .9, .05, .05, .01),
    "NP09": (.006, .9, .05, .05, .01),
    "NP10": (.01, 1.1, .05, .05, .01),
    "NP11": (.0075, 1.1, .05, .05, .01),
    "NP12": (.006, 1.1, .05, .05, .01),
    "NP13": (.01, .97, .05, .05, .01),
    "NP14": (.006, .97, .05, .05, .01),
}


def _read(path):
    return json.loads(path.read_text())


def _write(name, value):
    q2.atomic_json(OUT / name, value)


def _relative(path):
    return str(path.resolve().relative_to(LAB.resolve()))


def _lab_path(value):
    if not isinstance(value, str) or Path(value).is_absolute():
        raise ValueError("evidence paths must be LAB-relative")
    path = (LAB / value).resolve()
    path.relative_to(LAB.resolve())
    return path


def _fingerprint(path):
    return {"path": _relative(path), "sha256": q2.sha256(path)}


def _verify_fingerprint(value):
    if q2.sha256(_lab_path(value["path"])) != value["sha256"]:
        raise ValueError("bound evidence changed: " + value["path"])


def _plan():
    plan = _read(OUT / PLAN)
    if (plan.get("scope") != "conditional_plan_not_authorization"
            or plan.get("launch_allowed") is not False
            or plan.get("recipe_id") != RECIPE):
        raise ValueError("conditional plan identity or non-authorization scope changed")
    entries = plan.get("cases", [])
    if [e["plan_case_id"] for e in entries] != list(EXPECTED):
        raise ValueError("qualification plan must contain exactly NP01 through NP14")
    for entry in entries:
        if (tuple(entry.get(k) for k in KEYS) != EXPECTED[entry["plan_case_id"]]
                or entry.get("time_window_s") != [0, 8.35]
                or entry.get("launch_allowed_via_this_plan") is not False):
            raise ValueError("unregistered qualification cell parameters")
    return plan


def plan_entry(plan_case_id):
    """Read a single immutable planned cell without preparing or writing it."""
    if plan_case_id not in EXPECTED:
        raise ValueError("unknown qualification entry: " + str(plan_case_id))
    return copy.deepcopy(next(e for e in _plan()["cases"] if e["plan_case_id"] == plan_case_id))


def case_id_for(plan_case_id):
    """Stable artifact name, including the already-completed NP01 name."""
    entry = plan_entry(plan_case_id)
    if plan_case_id == "NP01":
        return NAME
    suffix = {"NP02": "_zero", "NP03": "_time", "NP04": "_output"}.get(plan_case_id, "")
    return (f"F3_CELL3_LONG_dp{entry['dp_m']}_a{entry['amplitude']:.3f}"
            f"_noslip_visco1_nopen{suffix}").replace(".", "p")


def _approved_limits():
    limits = _read(OUT / "RESOURCE-LIMITS.json")
    history = limits.get("authorization_history", [])
    approval = next((h for h in history if h.get("change", {}).get("qualification", {}).get("after") == 72
                     and h.get("owner_reply") == "批准资格求解总上限 72 次"), None)
    if approval is None or limits.get("limits", {}).get("qualification", 0) < 72:
        raise ValueError("explicit qualification cap 72 approval is required; old plan is not approval")
    return limits, approval


def _verify_assets(prefix, assets):
    required = {prefix.name + ext for ext in (".xml", "_Def.xml", ".bi4")}
    required.add("CaseSloshingAccData.csv")
    if not required.issubset(assets):
        raise ValueError("incomplete input asset binding")
    for name, digest in assets.items():
        if Path(name).name != name or q2.sha256(prefix.parent / name) != digest:
            raise ValueError("registered input asset changed: " + name)


def _asset_names(prefix):
    names = [prefix.name + ext for ext in (".xml", "_Def.xml", ".bi4")]
    names += ["CaseSloshingAccData.csv", prefix.name + "_hdp_Actual.vtk"]
    return names


def _parameters(root):
    nodes = root.findall("./execution/parameters/parameter")
    values = {n.get("key"): n.get("value") for n in nodes}
    if len(values) != len(nodes):
        raise ValueError("duplicate execution parameter")
    return values


def _hard_audit(record, audit):
    expected_n = record["gencase"]["fluid_particles"]
    if (audit.get("case_id") != record["id"] or audit.get("dp_m") != record["dp_m"]
            or audit.get("audit_status") != "pass_diagnostic"
            or audit.get("issues") != [] or audit.get("unknowns") != []):
        raise ValueError("source hard audit failed or belongs to another case")
    if (audit.get("time_start_s") != 0
            or not 8.35 <= audit.get("time_end_s", -1) < 8.36
            or audit.get("frames") != round(8.35 / record["time_out_s"]) + 1):
        raise ValueError("source audit does not cover the complete registered output window")
    for key in ("particle_axis_count", "initial_valid_particles", "final_valid_particles"):
        if audit.get(key) != expected_n:
            raise ValueError("source particle count disagrees with prepared native input")
    for key in ("identities_introduced_after_initial", "initial_identities_missing_at_final",
                "identities_reappeared_after_gap", "excluded_particles_from_solver_log", "finite_bad_value_rows"):
        if audit.get(key) != 0:
            raise ValueError("source lifecycle/finite hard gate is not verified zero")
    penetration = audit.get("penetration", {})
    for key in ("frames_with_penetration", "frames_with_runtime_domain_outside", "swept_crossing_count"):
        if penetration.get(key) != 0:
            raise ValueError("source wall hard gate is not verified zero")
    if penetration.get("runtime_domain_status") != "checked":
        raise ValueError("source runtime domain is unknown")
    hdf5 = _lab_path(audit["hdf5"])
    if hdf5 != (LAB / "campaigns/l1-resume/data/continuation" / (record["id"] + ".h5")).resolve():
        raise ValueError("source audit names another HDF5 case")
    if q2.sha256(hdf5) != audit.get("hdf5_sha256"):
        raise ValueError("source HDF5 changed after hard audit")


def _passed_case(plan_case_id):
    from scripts.l1r_branch_runner import check_completed_boundary

    name = case_id_for(plan_case_id)
    record = _read(OUT / (name + "-PREPARED.json"))
    entry = plan_entry(plan_case_id)
    expected = dict(id=name, case_id=name, recipe_id=RECIPE, solver_mode="-mdbc_noslip:1",
                    expected_slip_mode="No-slip", expected_no_penetration=True, max_attempts=1,
                    dp_m=entry["dp_m"], drive_amplitude=entry["amplitude"],
                    time_out_s=entry["output_interval_s"], time_max_s=8.35,
                    cfl_number=entry["cfl_number"], coef_dt_min=entry["coef_dt_min"])
    if any(record.get(k) != v for k, v in expected.items()):
        raise ValueError("source prepared case does not match its planned NoPen cell")
    _verify_assets(_lab_path(record["generated_prefix"]), record["input_assets"])
    audit = _read(OUT / (name + "-AUDIT.json"))
    _hard_audit(record, audit)
    solver = _read(OUT / (name + "-SOLVER.json"))
    if (solver.get("case_id") != name or solver.get("status") != "completed"
            or solver.get("solver_sha256") != q2.sha256(q2.SOLVER)):
        raise ValueError("source solver identity, completion or executable differs")
    executed = solver.get("source_record", {})
    for key in ("id", "generated_prefix", "input_assets", "gencase", "solver_mode", "recipe_id"):
        if executed.get(key) != record.get(key):
            raise ValueError("source prepared record differs from the actual executed inputs")
    native_parameters = _parameters(ET.parse(_lab_path(record["generated_prefix"]).with_suffix(".xml")).getroot())
    for key, value in {"Boundary": 2, "SlipMode": 2, "NoPenetration": 1, "Visco": .05,
                       "ViscoBoundFactor": 1, "Shifting": 0}.items():
        if float(native_parameters.get(key, "nan")) != value:
            raise ValueError("source native execution parameters differ from the NoPen recipe")
    check_completed_boundary(record, solver)
    return record, audit, solver


def _calibration():
    path = LAB / "diagnostics/f3-audit/v2-calibration.json"
    calibration = _read(path)
    if (calibration.get("calibrated") is not True
            or calibration.get("operator_sha256") != q2.sha256(LAB / "scripts/f3_observation_v2.py")):
        raise ValueError("v2 observation calibration failed or operator changed")
    return _fingerprint(path)


def verified_source(plan_case_id):
    """Return (record, audit, solver) after read-only native source verification."""
    return _passed_case(plan_case_id)


def _xml_metadata(prefix, dp):
    root = ET.parse(prefix.with_suffix(".xml")).getroot()
    definition = root.find("./casedef/geometry/definition")
    particles = root.find("./execution/particles")
    fluid = root.findall("./execution/particles/fluid")
    fixed = root.findall("./execution/particles/fixed")
    if (definition is None
            or not math.isclose(float(definition.get("dp")), dp, rel_tol=0.0, abs_tol=1e-8)
            or len(fluid) != 1 or len(fixed) != 1):
        raise ValueError("CELL3 source geometry or particle blocks do not match dp")
    n = math.prod(round(length / dp) for length in (.9, .18, .09))
    nb = int(fixed[0].get("count"))
    if (int(fluid[0].get("count")) != n or int(fluid[0].get("begin")) != nb
            or int(fixed[0].get("begin")) != 0
            or int(particles.get("np")) != n + nb
            or int(particles.get("nb")) != nb or int(particles.get("nbf")) != nb):
        raise ValueError("CELL3 generated particle counts or ID blocks are inconsistent")
    constants = root.find("./execution/constants")
    if not math.isclose(float(constants.find("dp").get("value")), dp,
                        rel_tol=0.0, abs_tol=1e-8):
        raise ValueError("generated constants use another dp")
    return {"total_particles": n + nb, "fluid_particles": n, "boundary_particles": nb}


def _initial_state(prefix, dp):
    """Check native BI4 identity, normals and the complete physical fluid lattice."""
    from scripts.l1r_q1_native import read_frame

    counts = _xml_metadata(prefix, dp)
    with tempfile.TemporaryDirectory(prefix="f3-nopen-initial-") as folder:
        temp = Path(folder) / "dump"
        ids, positions, velocities, density, meta, info = read_frame(prefix.with_suffix(".bi4"), temp)
        nb, n = counts["boundary_particles"], counts["fluid_particles"]
        if (meta.get("CaseName") != prefix.name
                or not math.isclose(float(meta["Dp"]), dp, rel_tol=0.0, abs_tol=1e-8)
                or int(meta["CaseNp"]) != counts["total_particles"]
                or int(meta["CaseNfixed"]) != nb or int(meta["CaseNfluid"]) != n
                or int(meta["CaseNmoving"]) != 0 or int(meta["CaseNfloat"]) != 0
                or not np.array_equal(ids, np.arange(n + nb, dtype=np.uint32))
                or float(info["TimeStep"]) != 0 or int(info["Nout"]) != 0):
            raise ValueError("native BI4 header or identities disagree with generated geometry")
        normals = np.fromfile(temp / "PART_0000/BoundNor.bin", np.float32).reshape(-1, 3)
        if (len(normals) != nb or not np.isfinite(normals).all()
                or np.any(np.linalg.norm(normals, axis=1) == 0)
                or not all(np.isfinite(a).all() for a in (positions, velocities, density))):
            raise ValueError("native initial arrays or boundary normals invalid")
        fluid = positions[nb:].astype(float)
        low, size = np.array([-.45, -.09, 0.]), np.array([.9, .18, .09])
        cells = np.rint((fluid - low) / dp - .5).astype(np.int64)
        shape = np.rint(size / dp).astype(np.int64)
        if (np.any(cells < 0) or np.any(cells >= shape)
                or not np.allclose(fluid, low + (cells + .5) * dp, atol=1e-6, rtol=0)
                or len(np.unique(np.ravel_multi_index(cells.T, shape))) != n):
            raise ValueError("native fluid lattice is not the complete CELL3 physical water volume")
        mass = n * float(meta["MassFluid"])
        if abs(mass / 14.58 - 1) > 1e-6:
            raise ValueError("native initial mass differs from the registered physical volume")
        return dict(counts, initial_mass_kg=mass, initial_com_m=fluid.mean(axis=0).tolist(),
                    native_dp_m=float(meta["Dp"]), zero_boundary_normals=0)


def _basis():
    plan = _plan()
    limits, approval = _approved_limits()
    base, audit, solver = _passed_case("NP01")
    design_path = OUT / "F3-NATIVE-NOPEN-DESIGN.json"
    if base.get("boundary_bridge_sha256") != q2.sha256(design_path):
        raise ValueError("NP01 native design binding changed")
    for path, digest in _read(design_path)["native_source_hashes"].items():
        if q2.sha256(_lab_path(path)) != digest:
            raise ValueError("native numerical source changed")
    evidence = [_fingerprint(OUT / PLAN), _fingerprint(design_path), _calibration(),
                _fingerprint(LAB / "scripts/f3_observation_v2.py"),
                _fingerprint(OUT / "F3-V2-OBSERVATION-DESIGN.json")]
    evidence += [_fingerprint(OUT / (NAME + suffix)) for suffix in ("-PREPARED.json", "-AUDIT.json", "-SOLVER.json")]
    evidence += [_fingerprint(Path(solver["attempt_directory"]) / "Run.out")]
    if audit.get("full_report"):
        _verify_fingerprint(audit["full_report"])
        evidence.append({k: audit["full_report"][k] for k in ("path", "sha256")})
    return plan, base, evidence, limits, approval


def register_stage():
    """Create/verify a separate execution registration; never rewrite the plan."""
    plan, base, evidence, limits, approval = _basis()
    path = OUT / STAGE
    if path.exists():
        stage = _read(path)
        if (stage.get("schema") != "f3.nopen.execution_stage.v1"
                or stage.get("recipe_id") != RECIPE or stage.get("evidence") != evidence
                or stage.get("entries") != plan["cases"][1:]
                or stage.get("max_attempts_per_case") != 1
                or stage.get("preparer_sha256") != q2.sha256(Path(__file__))):
            raise ValueError("immutable NoPen execution stage changed or its evidence is stale")
        for source in stage["initial_sources"].values():
            _verify_assets(_lab_path(source["prefix"]), source["assets"])
        return stage, base
    sources = {}
    for dp in (.01, .0075, .006):
        name = "F3_CELL3_plain_" + str(dp).replace(".", "p")
        prefix = LAB / "campaigns/l1-resume/artifacts/cell3" / name / name
        assets = {name: q2.sha256(prefix.parent / name) for name in _asset_names(prefix)}
        if dp == .01 and assets[prefix.name + ".bi4"] != base["input_assets"][prefix.name + ".bi4"]:
            raise ValueError("coarse CELL3 initial BI4 differs from the passed NP01 input")
        sources[str(dp)] = dict(prefix=_relative(prefix), assets=assets, **_initial_state(prefix, dp))
    stage = dict(schema="f3.nopen.execution_stage.v1", registered_at_utc=q2.utc_now(),
                 scope="qualification_execution_only_not_production_qualification", recipe_id=RECIPE,
                 conditional_plan=_fingerprint(OUT / PLAN), evidence=evidence,
                 authorization_snapshot=limits, approved_qualification_cap_at_registration=limits["limits"]["qualification"],
                 qualification_cap_72_owner_approval=approval, max_attempts_per_case=1,
                 entries=plan["cases"][1:], initial_sources=sources,
                 preparer_sha256=q2.sha256(Path(__file__)), auto_run_remaining_entries=False,
                 initial_ready_entries=[f"NP{i:02}" for i in range(2, 7)],
                 endpoint_gate="F3-NOPEN-NOMINAL-GATE.json", internal_gate="F3-NOPEN-ENDPOINT-GATE.json",
                 qualified=False, formal_release=False)
    _write(STAGE, stage)
    return stage, base


def _rewritten_xml(source, baseline, entry):
    """Keep this dp's generated geometry/constants and use NP01 execution policy."""
    tree, base = ET.parse(source), ET.parse(baseline).getroot()
    root = tree.getroot()
    execution = root.find("execution")
    for tag in ("special", "parameters"):
        old, new = execution.find(tag), base.find("./execution/" + tag)
        if old is None or new is None:
            raise ValueError("missing native execution policy section")
        index = list(execution).index(old)
        execution.remove(old)
        execution.insert(index, copy.deepcopy(new))
    changes = {"TimeMax": 8.35, "TimeOut": entry["output_interval_s"], "CoefDtMin": entry["coef_dt_min"]}
    for key, value in changes.items():
        nodes = root.findall(f'./execution/parameters/parameter[@key="{key}"]')
        if len(nodes) != 1:
            raise ValueError("missing or duplicate changed execution parameter")
        nodes[0].set("value", str(value))
    cfl = root.findall(".//cflnumber")
    if not cfl:
        raise ValueError("missing native CFL setting")
    for node in cfl:
        node.set("value", str(entry["cfl_number"]))
    expected = _parameters(base)
    expected.update({k: str(v) for k, v in changes.items()})
    if _parameters(root) != expected:
        raise ValueError("unintended execution parameter change")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _prepared_fields(entry, stage, source, target, prefix_name):
    name = case_id_for(entry["plan_case_id"])
    count_keys = ("total_particles", "fluid_particles", "boundary_particles")
    # Longer finite deadlines for larger native particle counts; shared runner
    # reserves the entire deadline against the approved GPU budget before launch.
    timeout = 1800 if entry["dp_m"] == .01 else (3600 if entry["dp_m"] == .0075 else 5400)
    return dict(id=name, case_id=name, phase="F3_native_nopen_qualification", plan_case_id=entry["plan_case_id"],
                recipe_id=RECIPE, variant="noslip_visco1_nopen", dp_m=entry["dp_m"], resolution=str(entry["dp_m"]),
                solver_mode="-mdbc_noslip:1", expected_slip_mode="No-slip", expected_no_penetration=True,
                max_attempts=1, solver_timeout_seconds=timeout, time_max_s=8.35, time_out_s=entry["output_interval_s"],
                cfl_number=entry["cfl_number"], coef_dt_min=entry["coef_dt_min"], drive_amplitude=entry["amplitude"],
                visco_bound_factor=1, native_velocity_displacement_correction=True, posthoc_particle_projection=False,
                generated_prefix=_relative(target / prefix_name), candidate_definition=_relative(target / (prefix_name + "_Def.xml")),
                gencase={**{k: source[k] for k in count_keys}, "reuse_source": str(Path(source["prefix"]).parent)},
                actual_y_layers=round(.18 / entry["dp_m"]), initial_mass_kg=source["initial_mass_kg"],
                initial_com_m=source["initial_com_m"], initial_target_mass_kg=14.58,
                initial_mass_relative_error=abs(source["initial_mass_kg"] / 14.58 - 1),
                initial_rule="Complete CELL3 cell-centred continuous 0.9 x 0.18 x 0.09 m water volume; native arrays unchanged",
                control_definition="F3_CELL3_gravity_preserving_amplitude_v1",
                qualification_stage_path=_relative(OUT / STAGE), qualification_stage_sha256=q2.sha256(OUT / STAGE),
                conditional_plan_sha256=stage["conditional_plan"]["sha256"],
                predecessor_audit_sha256=next(v["sha256"] for v in stage["evidence"] if v["path"].endswith(NAME + "-AUDIT.json")),
                comparison_scope="One cell of the native NoPen qualification matrix; reference/domain gates remain separate",
                input_repair="NP01 native execution policy with only the registered dp/control/time/output changes",
                qualified=False, formal_release=False)


def prepare(plan_case_id):
    if plan_case_id == "NP01":
        raise ValueError("NP01 already belongs to its separate one-attempt diagnostic")
    entry = plan_entry(plan_case_id)
    check_budget()
    stage, base = register_stage()
    name = case_id_for(plan_case_id)
    source = stage["initial_sources"][str(entry["dp_m"])]
    source_prefix = _lab_path(source["prefix"])
    target = LAB / "campaigns/l1-resume/artifacts/cell3-nopen-qualification" / name
    fields = _prepared_fields(entry, stage, source, target, source_prefix.name)
    saved = OUT / (name + "-PREPARED.json")
    if saved.exists():
        record = _read(saved)
        if any(record.get(k) != v for k, v in fields.items()):
            raise ValueError("immutable prepared NoPen record differs from its registered cell")
        prefix = _lab_path(record["generated_prefix"])
        _verify_assets(prefix, record["input_assets"])
        if q2.sha256(prefix.with_suffix(".xml")) != record.get("generated_xml_sha256"):
            raise ValueError("prepared XML fingerprint changed")
        base_prefix = _lab_path(base["generated_prefix"])
        for ext in (".xml", "_Def.xml"):
            expected_xml = _rewritten_xml(source_prefix.parent / (source_prefix.name + ext),
                                           base_prefix.parent / (base_prefix.name + ext), entry)
            if q2.sha256(prefix.parent / (prefix.name + ext)) != hashlib.sha256(expected_xml).hexdigest():
                raise ValueError("prepared XML differs from the registered single-factor transformation")
        for filename, digest in source["assets"].items():
            if not filename.endswith(".xml") and filename != "CaseSloshingAccData.csv":
                if q2.sha256(prefix.parent / filename) != digest:
                    raise ValueError("prepared native initial geometry differs from the registered dp source")
        check_input(record)
        return record
    attempts = LAB / "campaigns/l1-resume/runs/branches" / name / "attempts"
    if target.exists() or attempts.exists():
        raise ValueError("incomplete or attempted preparation exists; inspect without overwriting")
    target.mkdir(parents=True)
    for filename in source["assets"]:
        shutil.copy2(source_prefix.parent / filename, target / filename)
    base_prefix = _lab_path(base["generated_prefix"])
    for ext in (".xml", "_Def.xml"):
        xml = _rewritten_xml(source_prefix.parent / (source_prefix.name + ext),
                             base_prefix.parent / (base_prefix.name + ext), entry)
        (target / (source_prefix.name + ext)).write_bytes(xml)
    drive = target / "CaseSloshingAccData.csv"
    # Always transform the passed nominal input; never re-scale another endpoint.
    if entry["amplitude"] != 1.:
        values = np.loadtxt(base_prefix.parent / drive.name, delimiter=";", comments="#")
        gravity = np.array([0., 0., -9.81])
        values[:, 1:4] = gravity + entry["amplitude"] * (values[:, 1:4] - gravity)
        values[:, 4:7] *= entry["amplitude"]
        np.savetxt(drive, values, delimiter=";", fmt="%.17g", header="Time;LinearAccX;LinearAccY;LinearAccZ;AngularAccX;AngularAccY;AngularAccZ")
    elif q2.sha256(drive) != base["drive_sha256"]:
        raise ValueError("CELL3 nominal input differs from the passed NP01 forcing")
    record = copy.deepcopy(base)
    record.update(fields)
    record["wall_spec"].pop("runtime_domain", None)
    record.update(generated_xml_sha256=q2.sha256(target / (source_prefix.name + ".xml")),
                  drive_sha256=q2.sha256(drive),
                  input_assets={p.name: q2.sha256(p) for p in target.iterdir() if p.is_file()})
    if q2.sha256(target / (source_prefix.name + ".bi4")) != source["assets"][source_prefix.name + ".bi4"]:
        raise ValueError("native initial BI4 changed during preparation")
    if _xml_metadata(target / source_prefix.name, entry["dp_m"]) != {k: source[k] for k in ("total_particles", "fluid_particles", "boundary_particles")}:
        raise ValueError("prepared geometry no longer matches its original native dp source")
    check_input(record)
    _write(saved.name, record)
    return record


def _require_stage_gate(stage_name):
    if stage_name not in ("nominal", "endpoints"):
        raise ValueError("unknown stage gate")
    filename = "F3-NOPEN-NOMINAL-GATE.json" if stage_name == "nominal" else "F3-NOPEN-ENDPOINT-GATE.json"
    path = OUT / filename
    gate = _read(path)
    entries = range(1, 7) if stage_name == "nominal" else range(7, 13)
    plan_ids = [f"NP{i:02}" for i in entries]
    names = {case_id_for(i) for i in plan_ids}
    if (gate.get("schema") != "f3.nopen.stage_gate.v1" or gate.get("stage") != stage_name
            or gate.get("status") != "passed" or gate.get("recipe_id") != RECIPE
            or len(gate.get("case_ids", [])) != len(names) or set(gate.get("case_ids", [])) != names):
        raise ValueError("required stage gate is incomplete, failed or belongs to another recipe")
    bindings = gate.get("evidence_sha256")
    if not isinstance(bindings, dict) or not bindings:
        raise ValueError("stage gate lacks substantive evidence bindings")
    for relative, digest in bindings.items():
        _verify_fingerprint({"path": relative, "sha256": digest})
    for plan_id in plan_ids:
        name = case_id_for(plan_id)
        if _relative(OUT / (name + "-AUDIT.json")) not in bindings:
            raise ValueError("stage gate omits a required hard audit")
        _passed_case(plan_id)
    scores = gate.get("scoring_evidence_paths")
    if not isinstance(scores, list) or not scores:
        raise ValueError("stage gate must identify its substantive scoring reports")
    covered = set()
    for score_path in scores:
        if (score_path not in bindings or score_path.endswith("-AUDIT.json")
                or score_path.endswith("-GATE.json")):
            raise ValueError("scoring report is missing from bindings or is only an audit/gate")
        score = _read(_lab_path(score_path))
        covered.update(score.get("case_ids", score.get("cases", [])))
        if score.get("case_id"):
            covered.add(score["case_id"])
    if not names.issubset(covered):
        raise ValueError("stage scoring reports do not cover all required cases")
    if stage_name == "endpoints":
        _require_stage_gate("nominal")
        if _relative(OUT / "F3-NOPEN-NOMINAL-GATE.json") not in bindings:
            raise ValueError("endpoint gate must bind its passed nominal gate")
    return gate


def verify_stage_gate(stage_name):
    """Read/verify a substantively evaluated nominal or endpoint gate; no writes."""
    return _require_stage_gate(stage_name)


def run(plan_case_id):
    """Execute one cell through shared CPU/GPU/budget/attempt guards, then stop."""
    entry = plan_entry(plan_case_id)
    if 7 <= int(plan_case_id[2:]) <= 12:
        _require_stage_gate("nominal")
    elif plan_case_id in ("NP13", "NP14"):
        _require_stage_gate("endpoints")
    record = prepare(entry["plan_case_id"])
    from scripts.l1r_branch_runner import run as shared_run

    result = shared_run(record)
    failure = None
    try:
        _hard_audit(record, result)
    except (ValueError, KeyError, FileNotFoundError) as error:
        failure = str(error)
    return dict(case_id=record["id"], plan_case_id=plan_case_id,
                status="completed" if failure is None else "failed",
                solver_status=result.get("status"), audit_status=result.get("audit_status"),
                frames=result.get("frames"), issues=result.get("issues"), unknowns=result.get("unknowns"),
                hard_audit_passed=failure is None, failure_reason=failure,
                qualified=False, remaining_matrix_launched=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run"))
    parser.add_argument("entry", choices=tuple(k for k in EXPECTED if k != "NP01"))
    args = parser.parse_args(argv)
    if args.action == "prepare":
        print(prepare(args.entry)["id"], flush=True)
        return 0
    result = run(args.entry)
    print(json.dumps(result), flush=True)
    return 0 if result["hard_audit_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
