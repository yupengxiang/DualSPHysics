"""Final Q1 lifecycle/exclusion reconciliation and revised finite-footprint audit."""

import json, time
import numpy as np
import pandas as pd
import h5py
from scripts.l1r_continuation_evidence import LAB, OUT, write
from scripts import l1r_q2_mdbc_bridge as q2
from scripts.finite_wall_audit import wall_penetration, segment_crossing_events
from scripts.l1r_cpu_slots import cpu_slot


def main():
    start = time.monotonic()
    original = json.loads((OUT / "Q1-FULL-FRAME-AUDIT.json").read_text())
    spec = original["geometry"]
    rows = []
    seen = None
    missing = None
    reappeared = set()
    previous = None
    events_unique = set()
    excluded = pd.read_csv(OUT / "q1-exclusions/excluded.csv", sep=";")
    exclude_ids = set(excluded.Idp.astype(int))
    with h5py.File(LAB / "campaigns/l1-resume/data/q1-native.h5", "r") as h:
        ids = h["particle_id"][:]
        fluid = h["type"][:] == 3
        massvalue = float(h.attrs["MassFluid"])
        missing = np.zeros(len(ids), bool)
        for fi, row in enumerate(original["frames"]):
            valid = h["valid"][fi]
            p = h["position"][fi].astype(float)
            selected = valid & fluid
            masses = np.full(selected.sum(), massvalue)
            reappeared.update(ids[valid & missing].astype(int).tolist())
            missing |= ~valid
            revised = wall_penetration(p[selected], masses, spec, 0.0051)
            if previous is not None:
                common = selected & np.isfinite(previous).all(1)
                events = segment_crossing_events(
                    previous[common], p[common], spec, 0.0051
                )
                events_unique.update(
                    ids[common][[e["point_index"] for e in events]].astype(int).tolist()
                    if events
                    else []
                )
            else:
                events = []
            rows.append({**row, **revised, "geometric_event_count": len(events)})
            previous = p
        absent = set(ids[~valid].astype(int))
        initial = float(original["frames"][0]["fluid_mass_kg"])
        final = float(rows[-1]["fluid_mass_kg"])
    write(
        "Q1-ACCEPTANCE.json",
        {
            "source_hdf5": original["source"],
            "auditor_sha256": q2.sha256(LAB / "scripts/finite_wall_audit.py"),
            "frames_checked": len(rows),
            "identity_unique_every_saved_frame": all(
                r["identity_unique"] for r in rows
            ),
            "nonfinite_rows": sum(r["nonfinite_rows"] for r in rows),
            "fixed_boundary_unchanged_every_saved_frame": all(
                r["fixed_positions_unchanged"] for r in rows
            ),
            "final_missing_identities": len(absent),
            "native_excluded_unique_identities": len(exclude_ids),
            "native_reconciliation_exact": absent == exclude_ids,
            "reappeared_identities": sorted(reappeared),
            "initial_mass_kg": initial,
            "final_mass_kg": final,
            "mass_retention": final / initial,
            "excluded_mass_kg": len(exclude_ids) * massvalue,
            "native_motive_counts": {
                str(k): int(v) for k, v in excluded.Motive.value_counts().items()
            },
            "frames_with_endpoint_wall_exceedance": sum(
                bool(r["outside_closed_container_count"]) for r in rows
            ),
            "frames_with_obstacle_interior": sum(
                bool(r["obstacle_penetration_count"]) for r in rows
            ),
            "max_instantaneous_wall_exceedance_mass_kg": max(
                r["outside_closed_container_mass_kg"] for r in rows
            ),
            "unique_geometric_event_identities": len(events_unique),
            "runtime_domain_scope": "valid saved particles only; already removed identities are reconciled separately against native PartOut",
            "native_motive_semantics": {
                "1": "position exclusion (JSph.cpp CODE_OUTPOS -> motive 1)"
            },
            "native_position_exclusions": int((excluded.Motive == 1).sum()),
            "runtime_domain_outside_frames": sum(
                bool(r["runtime_domain_outside_count"]) for r in rows
            ),
            "execution_status": "completed",
            "acceptance_status": (
                "quality_failed"
                if absent
                or any(
                    r["outside_closed_container_count"]
                    or r["obstacle_penetration_count"]
                    for r in rows
                )
                else "hard_gates_pass"
            ),
            "observable_status": "independent descriptive H1-H4 comparisons and pressure limitations in Q1-OBSERVABLES.json",
            "formal_release": False,
            "elapsed_seconds": time.monotonic() - start,
            "geometry": spec,
        },
    )
    write("Q1-FINAL-GEOMETRY-FRAMES.json", rows)


if __name__ == "__main__":
    with cpu_slot():
        main()
