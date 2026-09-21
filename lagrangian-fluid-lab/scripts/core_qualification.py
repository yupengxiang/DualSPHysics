#!/usr/bin/env python3
"""Evaluate the frozen F4 13+2 matrix; incomplete/failed evidence stays visible."""
from __future__ import annotations
import argparse
import json
import re
from pathlib import Path
import sys
import tempfile

import h5py
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.core_runtime import Store, atomic_json, digest
from scripts.core_cfd import validate_prepared_matrix


def time_step_evidence(baseline_log, tightened_log):
    def parse(value):
        steps = re.search(r"Steps of simulation\.*\s*:\s*([\d,]+)", value)
        minimum = re.search(r"^DtMin=([\d.eE+-]+)", value, re.M)
        return {"steps": int(steps.group(1).replace(',', '')) if steps else None,
                "dt_min_s": float(minimum.group(1)) if minimum else None}
    a, b = parse(baseline_log), parse(tightened_log)
    passed = bool(a['steps'] and b['steps'] and b['steps'] >= 1.5*a['steps'])
    return {"passed": passed, "baseline": a, "tightened": b,
            "requirement": "same full horizon with at least 1.5 times the actual integration steps"}


def calibrate_f4(output, *, tallwall=False):
    """Manufactured exact masses/COM/energy and event ordering, without CFD fits."""
    from scripts.core_cfd import physical_observations, f4_config, lattice_box
    cfg = f4_config(.005, .5, stage="qualification")
    if tallwall:
        cfg.update(container_height_m=1.2,
                   observation_version="fixed_015m_vertical_reference060_v2")
        cfg["wall_bounds"] = dict(cfg["wall_bounds"], zmax=1.2)
    masses = np.array([46.592,5.824])
    times = np.array([0.,.1,.2,.4,.8])
    heights = (.95,.15,.75,.8,.1) if tallwall else (.47,.15,.25,.3,.1)
    positions = np.array([[[.2,.2,.1],[.6,.2,z]] for z in heights])
    velocities = np.zeros_like(positions)
    velocities[:,1,2] = [-.5,-.1,.1,-.1,0.]
    prepared = {"config":cfg,"sampling":{"fluid_boxes":[lattice_box(cfg[k]["low"],cfg[k]["size"],.005) for k in ("pool","drop")]}}
    with tempfile.TemporaryDirectory(prefix="core-observer-calibration-") as folder:
        path=Path(folder)/"manufactured.h5"
        with h5py.File(path,"w") as h:
            h["time"]=times;h["position"]=positions;h["velocity"]=velocities
            h["mass"]=np.tile(masses,(len(times),1));h["valid"]=np.ones((len(times),2),bool)
            h["source_label_initial_mk"]=[0,1]
        observed=physical_observations(prepared,path)
    expected=[]
    total=float(masses.sum())
    initial_energy=sum(float(masses[i])*(9.81*positions[0,i,2]+.5*sum(float(x*x) for x in velocities[0,i])) for i in range(2))
    for fi in range(len(times)):
        com=[sum(float(masses[i]*positions[fi,i,axis]) for i in range(2))/total/length for axis,length in enumerate((1.2,.4,.6))]
        ke=sum(.5*float(masses[i])*sum(float(x*x) for x in velocities[fi,i]) for i in range(2))/initial_energy
        histogram=np.zeros((4,2,8 if tallwall else 4))
        for i in range(2):
            indices=[min(size-1,int(np.floor(positions[fi,i,axis]/length*size))) for axis,(size,length) in enumerate(((4,1.2),(2,.4),(8,1.2) if tallwall else (4,.6)))]
            histogram[tuple(indices)]+=masses[i]/total
        expected.append([*com,ke,*histogram.reshape(-1),0.])
    error=float(np.max(np.abs(np.asarray(expected)-np.asarray(observed["normalized_values"]))))
    events=observed["event_times_s"]
    checks={"mass_COM_KE_fixed_cells_match_analytic":error<1e-12,
            "contact_then_upward_then_return":events=={"contact":.1,"upward":.2,"returning":.4},
            "post_return_window_required":observed["event_window_complete"],
            "all_mass_in_cells":bool(np.allclose(np.asarray(expected)[:,4:-1].sum(axis=1),1))}
    report={"schema":"core.observation_calibration.v1","family":"F4","passed":all(checks.values()),
            "checks":checks,"max_absolute_error":error,"event_times_s":events,
            "method":"independent scalar analytic manufactured two-source field; no CFD fitting or threshold selection",
            "scope":"COM/KE/fixed histogram/event ordering implementation, not external physical validation",
            "observation_version":observed["observation_version"],
            "observation_geometry":observed["observation_geometry"],
            "observable_layout":observed["observable_layout"],
            "observer_code_sha256":digest(Path(__file__).with_name("core_cfd.py"))}
    atomic_json(output,report)
    return report


def aligned_difference(first, second, cadence=.02):
    # Equal vector lengths do not establish equal physical observation semantics.
    for key in ("observation_version", "observation_geometry", "observable_layout"):
        if first.get(key) != second.get(key):
            raise ValueError(f"observation contract mismatch: {key}")
    if not np.isfinite(cadence) or cadence <= 0:
        raise ValueError("cadence must be finite and positive")
    a, b = np.asarray(first["time_s"]), np.asarray(second["time_s"])
    av, bv = np.asarray(first["normalized_values"]), np.asarray(second["normalized_values"])
    if av.ndim != 2 or bv.ndim != 2 or av.shape[1] != bv.shape[1]:
        raise ValueError("observation shape mismatch")
    if a.ndim != 1 or b.ndim != 1 or len(a) < 2 or len(b) < 2 or av.shape[0] != len(a) or bv.shape[0] != len(b) or not av.shape[1]:
        raise ValueError("observation time/value axes mismatch or empty")
    if any(not np.isfinite(x).all() for x in (a,b,av,bv)) or np.any(np.diff(a) <= 0) or np.any(np.diff(b) <= 0):
        raise ValueError("nonfinite or unordered observations")
    low, high = max(a[0], b[0]), min(a[-1], b[-1])
    grid = np.arange(np.ceil(low / cadence), np.floor(high / cadence) + 1) * cadence
    if len(grid) < 2:
        raise ValueError("insufficient common time support")
    aa = np.column_stack([np.interp(grid,a,av[:,i]) for i in range(av.shape[1])])
    bb = np.column_stack([np.interp(grid,b,bv[:,i]) for i in range(bv.shape[1])])
    errors = np.max(np.abs(aa - bb), axis=0)
    return {"maximum": float(errors.max()), "per_observable_maximum": errors.tolist(),
            "common_start_s": float(grid[0]), "common_end_s": float(grid[-1]), "score_frames": len(grid)}


def evaluate(matrix_root, runtime_root, *, observation_calibration=None):
    matrix_root = Path(matrix_root).resolve()
    static = validate_prepared_matrix(matrix_root)
    design = json.loads((matrix_root / "design.json").read_text())
    gates = design["preregistered_gates"]
    matrix = json.loads((matrix_root / "prepared-matrix.json").read_text())
    jobs = Store(runtime_root).jobs()
    cells, observations, missing, failures = [], {}, [], []
    solver_logs = {}
    for row in matrix["cells"]:
        prepared_path = Path(row["prepared"])
        config = json.loads(prepared_path.read_text())["config"]
        expected = digest(prepared_path)
        matching = [j for j in jobs if any(x.get("sha256") == expected and x.get("path") == str(prepared_path)
                                           for x in j["spec"].get("input_files", []))]
        completed = [j for j in matching if j["status"] == "succeeded"]
        if not completed:
            missing.append({"index": row["index"], "case_id": row["case_id"], "attempt_statuses": [j["status"] for j in matching]})
            continue
        # Do not pick whichever repeated scientific outcome looks most favorable.
        job = completed[0]
        output = Path(job["attempt_dir"]) / "product"
        audit_path, obs_path = output / "audit.json", output / "observations.json"
        audit, obs = json.loads(audit_path.read_text()), json.loads(obs_path.read_text())
        indexed = {x["path"]: x["sha256"] for x in job["result"].get("artifact_index", job["result"].get("outputs", []))}
        hashes_valid = all(indexed.get("product/" + p.name) == digest(p) for p in (audit_path, obs_path))
        good = bool(hashes_valid and audit.get("hard_integrity_pass") and audit.get("source_mass_gate_pass")
                    and audit.get("event_window_complete") and audit.get("case_id") == config["case_id"])
        if not good:
            failures.append({"index": row["index"], "case_id": row["case_id"], "reason": "hard_integrity_mass_event_or_hash_gate",
                             "hashes_valid": hashes_valid, "hard_integrity_pass": audit.get("hard_integrity_pass"),
                             "source_mass_gate_pass": audit.get("source_mass_gate_pass"), "event_window_complete": audit.get("event_window_complete")})
        cells.append({"index": row["index"], "case_id": row["case_id"], "job_id": job["job_id"], "passed": good,
                      "audit": {"path": str(audit_path), "sha256": digest(audit_path)},
                      "observations": {"path": str(obs_path), "sha256": digest(obs_path)}})
        observations[(config["parameter"]["q"], config["dp_m"], config["design_cell"])] = obs
        solver_path = output / 'solver/Run.out'
        if solver_path.exists() and indexed.get('product/solver/Run.out') == digest(solver_path):
            solver_logs[(config['parameter']['q'], config['dp_m'], config['design_cell'])] = solver_path.read_text()
    comparisons = []
    spatial_pass = independent_pass = temporal_pass = not missing
    for q in (0., .5, 1., .25, .75):
        middle = observations.get((q,.0075,"spatial"))
        fine = observations.get((q,.005,"spatial"))
        if middle is None or fine is None:
            spatial_pass = False
            if q in (.25,.75): independent_pass = False
            continue
        error = aligned_difference(middle, fine)
        passed = error["maximum"] <= gates["spatial_max_absolute_normalized_difference"]
        record = {"q": q, "kind": "production_fine", "passed": passed, **error}
        if q in (0., .5, 1.):
            coarse = observations.get((q,.01,"spatial"))
            if coarse is None:
                passed = False
            else:
                cm = aligned_difference(coarse,middle)
                cf = aligned_difference(coarse,fine)
                monotone = error["maximum"] <= cm["maximum"] + 1e-12
                passed &= max(cm["maximum"],cf["maximum"]) <= gates["spatial_max_absolute_normalized_difference"] and monotone
                record.update(coarse_production=cm,coarse_fine=cf,monotone_refinement=monotone)
        record["passed"] = bool(passed)
        comparisons.append(record)
        spatial_pass &= bool(passed)
        if q in (.25,.75): independent_pass &= bool(passed)
    for kind in ("internal_time", "native_output"):
        baseline, other = observations.get((.5,.0075,"spatial")), observations.get((.5,.0075,kind))
        if baseline is None or other is None:
            temporal_pass = False
            continue
        error = aligned_difference(baseline,other)
        passed = error["maximum"] <= gates["spatial_max_absolute_normalized_difference"] * gates["temporal_fraction_of_spatial_budget"]
        step_evidence = None
        if kind == 'internal_time':
            step_evidence = time_step_evidence(solver_logs.get((.5,.0075,'spatial'), ''),
                                              solver_logs.get((.5,.0075,kind), ''))
            passed = passed and step_evidence['passed']
        temporal_pass &= passed
        comparisons.append({"q":.5,"kind":kind,"passed":passed,"actual_step_evidence":step_evidence,**error})
    calibrated = False
    calibration = None
    if observation_calibration:
        path = Path(observation_calibration)
        calibration = json.loads(path.read_text())
        calibrated = (calibration.get("schema") == "core.observation_calibration.v1" and calibration.get("passed") is True
                      and calibration.get("observer_code_sha256") == digest(Path(__file__).with_name("core_cfd.py"))
                      and bool(observations)
                      and all(all(obs.get(key) == calibration.get(key) for key in
                                  ("observation_version", "observation_geometry", "observable_layout"))
                              for obs in observations.values()))
        calibration = {"path":str(path),"sha256":digest(path),"passed":calibrated}
    checks = {"static_matrix": static["static_quality_pass"], "matrix_complete": len(cells) == 15 and not missing,
              "all_case_hard_mass_event_gates": len(cells) == 15 and not failures,
              "spatial": bool(spatial_pass), "independent_checks": bool(independent_pass), "time_and_output": bool(temporal_pass),
              "observation_calibrated": calibrated}
    return {"schema":"core.qualification.v1","scope_id":design["scope_id"],"family":"F4",
            "extent":"parameter_range","T1_numerical":all(checks.values()),"T2_macro":False,"T2_path":False,
            "external_physical_validation":False,"matrix_complete":checks["matrix_complete"],
            "independent_checks_passed":bool(independent_pass), "checks":checks,
            "design_sha256":digest(matrix_root/"design.json"),"cells":cells,"missing":missing,"failures":failures,
            "comparisons":comparisons,"observation_calibration":calibration,
            "claim_limit":"finite registered domain and observation scales; not a mathematical all-parameter error guarantee"}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--calibrate-f4",action="store_true")
    p.add_argument("--tallwall-observer",action="store_true")
    p.add_argument("--matrix-root",type=Path)
    p.add_argument("--runtime-root",type=Path)
    p.add_argument("--observation-calibration",type=Path)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    if a.calibrate_f4:
        print(json.dumps(calibrate_f4(a.output,tallwall=a.tallwall_observer),indent=2))
        return
    if not a.matrix_root or not a.runtime_root:
        p.error("matrix and runtime roots are required for qualification")
    result=evaluate(a.matrix_root,a.runtime_root,observation_calibration=a.observation_calibration)
    atomic_json(a.output,result)
    print(json.dumps({k:result[k] for k in ("T1_numerical","checks","missing","failures")},indent=2))


if __name__=="__main__":main()
