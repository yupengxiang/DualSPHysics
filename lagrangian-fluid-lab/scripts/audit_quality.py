#!/usr/bin/env python3
"""Apply structural and semantic quality gates to all normalized probes."""

from __future__ import annotations

import json
from pathlib import Path

import h5py
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "reports" / "runtime"
JSON_REPORT = RUNTIME / "quality-gates.json"
MD_REPORT = ROOT / "reports" / "findings.md"


def load(name):
    return json.loads((RUNTIME / name).read_text())


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
    issues = []
    warnings = []
    h5_path = ROOT / audit["hdf5"]
    if solver_status != "completed":
        issues.append(f"solver status is {solver_status}")
    if not h5_path.is_file():
        issues.append("normalized HDF5 is missing")
    else:
        issues.extend(inspect_h5(h5_path))
    if audit["frames"] < 2:
        issues.append("fewer than two saved frames")
    if target_time is not None and audit["time_end"] < 0.99 * target_time:
        issues.append(f"ended at {audit['time_end']:.6g}s before target {target_time:.6g}s")
    if audit["density_min"] < 650 or audit["density_max"] > 1350:
        issues.append("density left the broad 650--1350 kg/m^3 sanity range")

    mechanism = audit["mechanism"]
    open_boundary = "open-boundary" in mechanism
    variable_resolution = "variable-resolution" in mechanism
    initial = audit.get("particles_initial", audit["ids_common_first_last"])
    excluded = audit.get("excluded_particles") or 0
    excluded_fraction = excluded / max(1, initial)
    if open_boundary:
        introduced = audit.get("identities_introduced_after_initial", 0)
        if introduced <= 0 or audit.get("particles_final", initial) <= initial:
            issues.append("open-boundary probe did not demonstrate particle injection")
        warnings.append("identity retention is intentionally not a quality gate for open boundaries")
    elif variable_resolution:
        if audit["identity_retention"] < 0.85:
            issues.append("too few initial (zone,idp) numerical nodes survive to the final frame")
        warnings.append("(zone,idp) tracks numerical nodes, not material identity through split/merge")
    else:
        if audit["identity_retention"] < 0.95:
            issues.append(f"closed-domain identity retention is only {audit['identity_retention']:.3f}")
        if excluded_fraction > 0.05:
            issues.append(f"excluded-particle fraction is {excluded_fraction:.3f}")
    if initial < 500:
        warnings.append("very small probe (<500 initial dynamic particles); useful for plumbing only")
    if audit.get("identity_key") == "(zone,idp)":
        warnings.append("composite zone-aware identity is required")
    return {
        "id": audit["id"], "family": audit["family"], "mechanism": mechanism,
        "status": "usable_probe" if not issues else "quality_failed",
        "solver_status": solver_status, "target_time": target_time,
        "time_end": audit["time_end"], "frames": audit["frames"],
        "particles_initial": initial, "particles_final": audit.get("particles_final"),
        "identity_retention": audit["identity_retention"],
        "excluded_particles": excluded, "issues": issues, "warnings": warnings,
        "hdf5": audit["hdf5"],
    }


def main():
    groups = [
        ("custom", load("trajectory-audit.json"), load("prepare-summary.json"), load("run-summary.json")),
        ("official", load("official-trajectory-audit.json"), load("official-prepare-summary.json"),
         load("official-run-summary.json")),
    ]
    results = []
    for origin, audits, prepared, runs in groups:
        targets = {r["id"]: r.get("time_max", r.get("tmax")) for r in prepared["cases"]}
        statuses = {r["id"]: r["status"] for r in runs["cases"]}
        for audit in audits["cases"]:
            item = assess(audit, targets.get(audit["id"]), statuses.get(audit["id"], "missing"))
            item["origin"] = origin
            results.append(item)
    usable = [r for r in results if r["status"] == "usable_probe"]
    failed = [r for r in results if r["status"] == "quality_failed"]
    report = {
        "schema_version": 1,
        "policy": {
            "closed_identity_retention_min": 0.95,
            "closed_excluded_fraction_max": 0.05,
            "density_sanity_kg_m3": [650, 1350],
            "time_completion_fraction_min": 0.99,
            "exceptions": ["open-boundary lifecycle", "variable-resolution composite identity"],
        },
        "total": len(results), "usable": len(usable), "quality_failed": len(failed),
        "cases": sorted(results, key=lambda r: r["id"]),
    }
    JSON_REPORT.write_text(json.dumps(report, indent=2) + "\n")

    lines = [
        "# Exploratory run findings", "",
        f"The end-to-end pipeline produced **{len(results)} normalized probes**: "
        f"**{len(usable)} passed** the current exploratory quality gates and "
        f"**{len(failed)} failed** them.", "",
        "A solver return code is deliberately not treated as proof of dataset quality. "
        "Each case must also reach its target time, satisfy HDF5 structural checks, keep density "
        "within a broad sanity range, and obey lifecycle rules appropriate to its boundary model.", "",
        "## Quality failures", "",
    ]
    if failed:
        for item in failed:
            lines.append(f"- `{item['id']}`: {'; '.join(item['issues'])}")
    else:
        lines.append("- None")
    lines += [
        "", "## Semantics established", "",
        "- Closed, fixed-resolution cases can use stable `Idp` trajectories; shifting is disabled in the custom probes.",
        "- Open boundaries need birth/death masks. The impinging-jet probe injects new IDs, so a fixed conserved particle set is invalid.",
        "- Variable resolution needs `(Zone, Idp)` to identify exported numerical nodes. Split/merge continuity requires a separate lineage representation.",
        "- Floating-body boundary particles are preserved with `Type=2` and can be tracked alongside `Type=3` fluid particles.",
        "", "## Most important resolution result", "",
        "The coarse wave-runup probe (`dp=0.04 m`) completed normally but lost 21,695 of 21,723 initial fluid identities. "
        "The refined probe (`dp=0.025 m`) retained essentially all particles (one exclusion). This is the clearest proof that "
        "workflow smoke tests and scientifically usable dataset runs must be reported separately.", "",
        "## Scope warning", "",
        "These are mechanism and plumbing probes, not converged CFD benchmarks. They establish installation, case generation, "
        "multi-GPU scheduling, raw-output retention, trajectory normalization, and failure detection. Resolution studies, validation "
        "against experiments, nondimensional coverage, and train/validation/test split design remain future work.", "",
    ]
    MD_REPORT.write_text("\n".join(lines))
    print(f"total={len(results)} usable={len(usable)} quality_failed={len(failed)}")
    for item in failed:
        print(f"FAIL {item['id']}: {'; '.join(item['issues'])}")
    return 1 if any(item["solver_status"] != "completed" for item in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
