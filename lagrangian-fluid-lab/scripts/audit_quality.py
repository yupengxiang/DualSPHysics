#!/usr/bin/env python3
"""Reconcile planned cases with evidence and apply exploratory or strict gates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import h5py
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "reports" / "runtime"
DEFAULT_REGISTRY = ROOT / "campaigns" / "v0.1-candidate" / "case-registry.json"
DEFAULT_REPORT = ROOT / "campaigns" / "v0.1-candidate" / "w01-quality-strict.json"


def load(path: Path):
    return json.loads(path.read_text())


def case_map(path: Path):
    return {case["id"]: case for case in load(path).get("cases", [])}


def inspect_h5(path: Path):
    issues = []
    with h5py.File(path, "r") as h5:
        required = {"time", "particle_id", "particle_zone", "valid", "position", "velocity",
                    "density", "mass", "pressure", "type", "mk"}
        missing = sorted(required - set(h5))
        if missing:
            return [f"missing datasets: {missing}"]
        time = h5["time"][:]
        valid = h5["valid"][:]
        ids = h5["particle_id"][:]
        zones = h5["particle_zone"][:]
        if len(time) < 2 or not np.all(np.diff(time) > 0):
            issues.append("time is not strictly increasing with at least two frames")
        if valid.shape != (len(time), len(ids)):
            issues.append("valid mask shape does not match time and identity axes")
        if len(np.unique(np.column_stack((zones, ids)), axis=0)) != len(ids):
            issues.append("(zone,idp) identity keys are not unique")
        for name in ("position", "velocity"):
            if h5[name].shape != valid.shape + (3,):
                issues.append(f"{name} shape is inconsistent")
            elif not np.isfinite(h5[name][:][valid]).all():
                issues.append(f"{name} contains non-finite values for valid rows")
        for name in ("density", "mass", "pressure"):
            if h5[name].shape != valid.shape:
                issues.append(f"{name} shape is inconsistent")
            elif not np.isfinite(h5[name][:][valid]).all():
                issues.append(f"{name} contains non-finite values for valid rows")
    return issues


def assess(audit, target_time, solver_status):
    """Assess one case. Missing evidence is unknown, never an implicit zero/pass."""
    if audit is None:
        return {
            "observed_status": "unknown", "solver_status": solver_status,
            "issues": ["trajectory audit is missing"], "warnings": [],
            "excluded_particles": None,
        }
    issues = []
    warnings = []
    h5_relative = audit.get("hdf5")
    h5_path = ROOT / h5_relative if h5_relative else None
    if solver_status != "completed":
        issues.append(f"solver status is {solver_status}")
    if h5_path is None or not h5_path.is_file():
        issues.append("normalized HDF5 is missing")
    else:
        issues.extend(inspect_h5(h5_path))
    if audit.get("frames", 0) < 2:
        issues.append("fewer than two saved frames")
    if target_time is None:
        issues.append("target time evidence is unknown")
    elif audit.get("time_end") is None or audit["time_end"] < 0.99 * target_time:
        issues.append(f"run did not reach 99% of target time {target_time:.6g}s")
    if audit.get("density_min") is None or audit.get("density_max") is None:
        issues.append("density range evidence is unknown")
    elif audit["density_min"] < 650 or audit["density_max"] > 1350:
        issues.append("density left the broad 650--1350 kg/m^3 sanity range")

    mechanism = audit.get("mechanism", "unknown")
    open_boundary = "open-boundary" in mechanism
    variable_resolution = "variable-resolution" in mechanism
    initial = audit.get("particles_initial", audit.get("ids_common_first_last"))
    excluded = audit.get("excluded_particles")
    if initial is None:
        issues.append("initial particle count evidence is unknown")
    if excluded is None:
        issues.append("excluded particle evidence is unknown")
    if open_boundary:
        introduced = audit.get("identities_introduced_after_initial")
        final = audit.get("particles_final")
        if introduced is None or final is None:
            issues.append("open-boundary lifecycle evidence is unknown")
        elif introduced <= 0:
            issues.append("open-boundary probe did not demonstrate particle injection")
        warnings.append("open boundaries require flux/lifecycle gates; retention is descriptive only")
    elif variable_resolution:
        if audit.get("identity_key") != "(zone,idp)":
            issues.append("variable-resolution output lacks a composite (zone,idp) key")
        warnings.append("node retention is not a physical mass or material-lineage gate")
    elif initial is not None and excluded is not None:
        retention = audit.get("identity_retention")
        if retention is None or retention < 0.95:
            issues.append(f"closed-domain identity retention is {retention!r}")
        excluded_fraction = excluded / max(1, initial)
        if excluded_fraction > 0.05:
            issues.append(f"excluded-particle fraction is {excluded_fraction:.3f}")
    if initial is not None and initial < 500:
        warnings.append("very small probe (<500 initial dynamic particles); plumbing evidence only")
    return {
        "observed_status": "usable_probe" if not issues else "quality_failed",
        "solver_status": solver_status, "target_time": target_time,
        "time_end": audit.get("time_end"), "frames": audit.get("frames"),
        "particles_initial": initial, "particles_final": audit.get("particles_final"),
        "identity_retention": audit.get("identity_retention"),
        "excluded_particles": excluded, "issues": issues, "warnings": warnings,
        "hdf5": h5_relative,
    }


def reconcile(registry, evidence):
    results = []
    for planned in registry["cases"]:
        origin = planned["origin"]
        prepared = evidence[origin]["prepared"].get(planned["id"])
        run = evidence[origin]["runs"].get(planned["id"])
        audit = evidence[origin]["audits"].get(planned["id"])
        missing_stages = []
        if prepared is None:
            missing_stages.append("prepare")
        if run is None:
            missing_stages.append("run")
        if audit is None:
            missing_stages.append("audit")
        target_time = None if prepared is None else prepared.get("time_max", prepared.get("tmax"))
        solver_status = "missing" if run is None else run.get("status", "unknown")
        result = {**planned, **assess(audit, target_time, solver_status),
                  "missing_stages": missing_stages}
        expected = planned.get("expected_outcome", "usable_probe")
        observed = result["observed_status"]
        if missing_stages or observed == "unknown":
            result["disposition"] = "missing_evidence"
        elif observed == expected == "usable_probe":
            result["disposition"] = "accepted_probe"
        elif observed == expected == "quality_failed":
            result["disposition"] = "expected_failure"
        else:
            result["disposition"] = "unexpected_outcome"
        results.append(result)
    planned_ids = {case["id"] for case in registry["cases"]}
    extra = sorted({case_id for group in evidence.values() for stage in group.values()
                    for case_id in stage if case_id not in planned_ids})
    return results, extra


def build_report(registry_path=DEFAULT_REGISTRY):
    registry = load(Path(registry_path))
    evidence = {
        "custom": {
            "prepared": case_map(RUNTIME / "prepare-summary.json"),
            "runs": case_map(RUNTIME / "run-summary.json"),
            "audits": case_map(RUNTIME / "trajectory-audit.json"),
        },
        "official": {
            "prepared": case_map(RUNTIME / "official-prepare-summary.json"),
            "runs": case_map(RUNTIME / "official-run-summary.json"),
            "audits": case_map(RUNTIME / "official-trajectory-audit.json"),
        },
    }
    results, unplanned = reconcile(registry, evidence)
    blockers = [case for case in results if case["disposition"] in
                {"missing_evidence", "unexpected_outcome"}]
    counts = {name: sum(case["disposition"] == name for case in results) for name in
              ("accepted_probe", "expected_failure", "missing_evidence", "unexpected_outcome")}
    return {
        "schema_version": 2, "registry": str(Path(registry_path).relative_to(ROOT)),
        "mode_semantics": {
            "exploratory": "always writes evidence; quality outcomes remain visible",
            "strict": "nonzero exit for missing evidence, unplanned evidence, or unexpected outcome",
        },
        "planned_total": len(results), "counts": counts, "unplanned_evidence_ids": unplanned,
        "strict_pass": not blockers and not unplanned, "cases": results,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("exploratory", "strict"), default="exploratory")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    report = build_report(args.registry)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"planned={report['planned_total']} strict_pass={report['strict_pass']} "
          f"counts={report['counts']} unplanned={len(report['unplanned_evidence_ids'])}")
    for case in report["cases"]:
        if case["disposition"] not in {"accepted_probe", "expected_failure"}:
            print(f"BLOCK {case['id']}: {case['disposition']}: " + "; ".join(case["issues"]))
    if args.mode == "strict" and not report["strict_pass"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
