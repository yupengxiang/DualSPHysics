"""Immutable supplementary evidence for the L1-R continuation."""

from pathlib import Path
import argparse, json, re, time
from datetime import datetime, timezone
import numpy as np
import h5py
from scripts import l1r_q2_mdbc_bridge as q2
from scripts.finite_wall_audit import (
    FACE_AXIS,
    outside_closed_face_masks,
    segment_crossing_events,
    wall_penetration,
)

LAB = Path(__file__).resolve().parents[1]
OUT = LAB / "campaigns/l1-resume/continuation"


def resource_limits():
    """Owner-approved limits; historical charges are never reset."""
    return json.loads((OUT / "RESOURCE-LIMITS.json").read_text())["limits"]


def material_usage():
    """Reserve declared material configurations, including incomplete work."""
    return sum(json.loads(p.read_text()).get("configuration_charge",0)
               for p in OUT.glob("F3-MATERIAL-*.json"))


def write(name, data):
    q2.atomic_json(OUT / name, data)


def runtime_domain(attempt):
    m = re.search(
        r"MapRealPos\(final\)=\(([^)]+)\)-\(([^)]+)\)",
        (attempt / "Run.out").read_text(),
    )
    return (
        dict(
            zip(
                ("xmin", "ymin", "zmin", "xmax", "ymax", "zmax"),
                [float(x) for g in m.groups() for x in g.split(",")],
            )
        )
        if m
        else None
    )


def ledger():
    rows = []
    for name in ("l1-qualification", "l1-resume"):
        for f in sorted((LAB / "campaigns" / name / "runs").glob("**/attempt.json")):
            d = json.loads(f.read_text())
            rows.append(
                {
                    **{
                        k: d.get(k)
                        for k in (
                            "case_id",
                            "attempt_id",
                            "status",
                            "started_at_utc",
                            "finished_at_utc",
                            "elapsed_seconds",
                            "resource_guard_triggered",
                            "timeout_seconds",
                        )
                    },
                    "path": str(f.relative_to(LAB)),
                    "sha256": q2.sha256(f),
                    "backend": (
                        "gpu"
                        if any(str(x).startswith("-gpu") for x in d["command"])
                        else "cpu"
                    ),
                }
            )
    # Direct launches predate the attempt writer. Keep them in the budget on
    # every regeneration, including failed initialization and interrupted runs.
    supplement = LAB / "diagnostics/f3-audit/direct-attempt-reconciliation.json"
    if supplement.exists():
        for item in json.loads(supplement.read_text())["additional_attempts"]:
            rows.append({
                "case_id": item["id"], "attempt_id": item["id"],
                "status": item["status"], "backend": "gpu",
                "elapsed_seconds": item["elapsed_seconds"],
                "resource_guard_triggered": None,
                "path": item.get("log"), "sha256": item.get("sha256"),
                "accounting_source": str(supplement.relative_to(LAB)),
            })
    for row in rows:
        timeout=row.get("timeout_seconds")
        if row["status"] == "running" and isinstance(timeout,(int,float)) and np.isfinite(timeout) and timeout>0:
            row["budget_reserve_seconds"]=timeout
            row["reserve_basis"]="Recorded guarded-executor timeout reserved until terminal duration is available; not measured usage or evidence that a process is live."
        if row["elapsed_seconds"] is None and row.get("started_at_utc") and row.get("finished_at_utc"):
            row["elapsed_seconds"] = (datetime.fromisoformat(row["finished_at_utc"]) - datetime.fromisoformat(row["started_at_utc"])).total_seconds()
            row["duration_basis"] = "recorded_wall_clock_difference"
        if row["attempt_id"] in {"direct-006-out", "direct-0075-loader-failure", "direct-0075-missing-drive"}:
            row["budget_reserve_seconds"] = 3600
            row["reserve_basis"] = "Conservative one-hour charge, not measured runtime. Direct launches and terminal observations in conversation occurred within 13:19–13:40 local time; stop commit adec9b9 is timestamped 13:40:23."
    unknown_gpu = sum(r["backend"] == "gpu" and r["elapsed_seconds"] is None for r in rows)
    unbounded_gpu = sum(r["backend"] == "gpu" and r["elapsed_seconds"] is None and "budget_reserve_seconds" not in r for r in rows)
    reserve = OUT / "HISTORICAL-CPU-RESERVE.json"
    if not reserve.exists():
        now = datetime.now(timezone.utc)
        hours = (now - datetime(2026, 9, 9, tzinfo=timezone.utc)).total_seconds() / 3600
        write(
            reserve.name,
            {
                "captured_at": now.isoformat(),
                "cpu_core_hours_conservative_reserve": hours * 16 * 1.1,
                "basis": "entire activity since start-of-adoption-day at 2 x 8 CPU threads, plus 10 percent control-process allowance; includes failed and unmetered postprocessing, not a claim of measured usage",
            },
        )
    write(
        "RESOURCE-LEDGER.json",
        {
            "captured_at": q2.utc_now(),
            "start_evidence": "L1 W00 capture 2026-09-09T03:09:38.158441Z; adoption earlier on same date",
            "conservative_expiry_utc": "2026-09-16T00:00:00+00:00",
            "attempts": rows,
            "qualification_attempts_used": len(rows),
            "qualification_attempts_remaining": resource_limits()["qualification"] - len(rows),
            "material_configurations_used": material_usage(),
            "material_usage_basis": "Original L1 material usage was zero; current F3 engineering and manufactured-calibration configurations are charged including incomplete attempts. Qualified CFD material configurations do not yet exist.",
            "gpu_unmetered_attempts": unknown_gpu,
            "gpu_unbounded_attempts": unbounded_gpu,
            "gpu_budget_charge_hours": sum((r["elapsed_seconds"] if r["elapsed_seconds"] is not None else r.get("budget_reserve_seconds", 0)) for r in rows if r["backend"] == "gpu") / 3600,
            "gpu_accounting_status": "lower_bound_only" if unknown_gpu else "recorded_durations",
            "gpu_solver_hours": sum(
                r["elapsed_seconds"] or 0 for r in rows if r["backend"] == "gpu"
            )
            / 3600,
            "cpu_core_hours_upper_bound": json.loads(reserve.read_text())[
                "cpu_core_hours_conservative_reserve"
            ]
            + post_reserve_hours() * 16 * 1.1,
            "historical_cpu_accounting_status": "supplement reported totals with new timings; unmetered work is unknown, never zero",
            "limits": resource_limits(),
            "formal_release": False,
        },
    )


def vtk_arrays(path):
    data = path.read_bytes()
    m = re.search(rb"POINTS (\d+) (float|double)\n", data)
    if not m:
        raise ValueError(path)
    n = int(m[1])
    arrays = {
        "points": np.frombuffer(
            data,
            dtype=">f4" if m[2] == b"float" else ">f8",
            count=n * 3,
            offset=m.end(),
        )
        .reshape(-1, 3)
        .astype(float)
    }
    for m in re.finditer(
        rb"(?:VECTORS (\w+) (float|double)\n|\n(\w+) 3 (\d+) (float|double)\n)", data
    ):
        name = (m[1] or m[3]).decode()
        count = n if m[1] else int(m[4])
        kind = m[2] or m[5]
        arrays[name] = (
            np.frombuffer(
                data,
                dtype=">f4" if kind == b"float" else ">f8",
                count=count * 3,
                offset=m.end(),
            )
            .reshape(-1, 3)
            .astype(float)
        )
    return arrays


def geometry():
    attempt = next(q2.RUN_ROOT.glob("*/attempts/*.complete"))
    result = {}
    paths = (
        list(q2.RAW_ROOT.glob("*hdp_Actual.vtk"))
        + list(q2.RAW_ROOT.glob("*Bound.vtk"))
        + [attempt / "CfgInit_Normals.vtk", attempt / "CfgInit_NormalsGhost.vtk"]
    )
    for path in paths:
        arrays = vtk_arrays(path)
        result[path.name] = {
            "path": str(path.relative_to(LAB)),
            "sha256": q2.sha256(path),
            "arrays": {
                k: {
                    "count": len(v),
                    "min": v.min(axis=0).tolist(),
                    "max": v.max(axis=0).tolist(),
                    "first_5": v[:5].tolist(),
                }
                for k, v in arrays.items()
            },
        }
    write("Q2-GEOMETRY.json", result)


def trajectories():
    start = time.monotonic()
    cpu = time.process_time()
    h5path = next(q2.DATA_ROOT.glob("*.h5"))
    attempt = next(q2.RUN_ROOT.glob("*/attempts/*.complete"))
    spec = q2.build_record()["wall_spec"]
    spec["runtime_domain"] = runtime_domain(attempt)
    with h5py.File(h5path, "r") as h5:
        ids = h5["particle_id"][:]
        zones = h5["particle_zone"][:]
        times = h5["time"][:]
        masses = h5["mass"][0]
        records = {}
        pending = {}
        series = []
        previous = None
        previous_valid = None
        ever = np.zeros(len(ids), bool)
        for fi, t in enumerate(times):
            p = h5["position"][fi].astype(float)
            valid = h5["valid"][fi] & np.isfinite(p).all(axis=1)
            masks = outside_closed_face_masks(p, spec, 0.0051)
            if previous is not None:
                inds = np.flatnonzero(valid & previous_valid)
                for ev in segment_crossing_events(
                    previous[inds], p[inds], spec, 0.0051
                ):
                    if ev["kind"] == "closed_face":
                        pending[(int(inds[ev["point_index"]]), ev["face"])] = {
                            "interval_s": [float(times[fi - 1]), float(t)],
                            "position_m": ev["crossing_position_m"],
                            "chord_fraction": ev["fraction"],
                        }
            any_out = np.zeros(len(ids), bool)
            for face, mask in masks.items():
                axis, side = FACE_AXIS[face]
                plane = spec["container_interior"][
                    "xyz"[axis] + ("min" if side == 0 else "max")
                ]
                mask &= valid
                any_out |= mask
                for idx in np.flatnonzero(mask):
                    key = (int(idx), face)
                    depth = abs(float(p[idx, axis]) - plane)
                    if key not in records:
                        records[key] = {
                            "particle_id": int(ids[idx]),
                            "particle_zone": int(zones[idx]),
                            "face": face,
                            "mass_kg": float(masses[idx]),
                            "first_exceedance_time_s": float(t),
                            "first_geometric_crossing": pending.get(key),
                            "initially_outside": bool(fi == 0),
                            "max_depth_m": 0.0,
                            "episodes": [],
                        }
                    r = records[key]
                    if not r["episodes"] or r["episodes"][-1]["last_frame"] != fi - 1:
                        r["episodes"].append(
                            {
                                "first_frame": fi,
                                "last_frame": fi,
                                "start_s": float(t),
                                "last_observed_s": float(t),
                            }
                        )
                    r["episodes"][-1].update(last_frame=fi, last_observed_s=float(t))
                    if depth > r["max_depth_m"]:
                        edges = [
                            min(
                                abs(
                                    p[idx, j]
                                    - spec["container_interior"]["xyz"[j] + "min"]
                                ),
                                abs(
                                    p[idx, j]
                                    - spec["container_interior"]["xyz"[j] + "max"]
                                ),
                            )
                            for j in range(3)
                            if j != axis
                        ]
                        r.update(
                            max_depth_m=depth,
                            max_depth_dp=depth / 0.01,
                            max_depth_h=depth / 0.01732050807568877,
                            max_depth_time_s=float(t),
                            max_depth_position_m=p[idx].tolist(),
                            distance_to_nearest_face_edge_m=float(min(edges)),
                            distance_to_nearest_face_corner_m=float(
                                np.linalg.norm(edges)
                            ),
                        )
                for key in list(pending):
                    if key[1] == face:
                        idx = key[0]
                        inside = (
                            p[idx, axis] >= plane
                            if side == 0
                            else p[idx, axis] <= plane
                        )
                        if inside or not valid[idx]:
                            pending.pop(key)
            ever |= any_out
            summary = wall_penetration(p[valid], masses[valid], spec, 0.0051)
            series.append(
                {
                    "frame": fi,
                    "time_s": float(t),
                    "outside_mass_kg": float(masses[any_out].sum(dtype=float)),
                    "outside_count": int(any_out.sum()),
                    "runtime_outside_count": summary["runtime_domain_outside_count"],
                }
            )
            previous = p
            previous_valid = valid
        for (idx, face), r in records.items():
            r["final_position_m"] = p[idx].tolist()
            r["final_valid"] = bool(valid[idx])
            r["observed_duration_lower_bound_s"] = sum(
                e["last_observed_s"] - e["start_s"] for e in r["episodes"]
            )
        selected = (
            sorted(records, key=lambda k: records[k]["first_exceedance_time_s"])[:10]
            + sorted(records, key=lambda k: -records[k]["max_depth_m"])[:10]
        )
        snippets = []
        for idx, face in dict.fromkeys(selected):
            r = records[(idx, face)]
            anchors = [
                int(np.argmin(abs(times - r[k])))
                for k in ("first_exceedance_time_s", "max_depth_time_s")
            ]
            frames = sorted(
                set(
                    j
                    for a in anchors
                    for j in range(max(0, a - 3), min(len(times), a + 4))
                )
            )
            snippets.append(
                {
                    "particle_id": int(ids[idx]),
                    "face": face,
                    "samples": [
                        {
                            "time_s": float(times[j]),
                            "position_m": h5["position"][j, idx].astype(float).tolist(),
                        }
                        for j in frames
                    ],
                }
            )
    write(
        "Q2-TRAJECTORIES.json",
        {
            "source": q2.fingerprint(h5path),
            "runtime_domain": spec["runtime_domain"],
            "runtime_domain_source": str((attempt / "Run.out").relative_to(LAB)),
            "tolerance_m": 0.0051,
            "time_semantics": "saved-frame intervals; duration lower bounds, not exact continuous trajectories",
            "unique_exceeding_identities": int(ever.sum()),
            "cumulative_unique_exceeding_mass_kg": float(masses[ever].sum(dtype=float)),
            "max_instantaneous_mass_kg": max(x["outside_mass_kg"] for x in series),
            "max_depth_m": max((r["max_depth_m"] for r in records.values()), default=0),
            "identities": list(records.values()),
            "time_series": series,
            "earliest_and_deepest_snippets": snippets,
            "cpu_seconds": time.process_time() - cpu,
            "elapsed_seconds": time.monotonic() - start,
        },
    )


def check_budget():
    ledger()
    budget = json.loads((OUT / "RESOURCE-LEDGER.json").read_text())
    if budget.get("gpu_unbounded_attempts", 0):
        raise RuntimeError("reconcile unmetered GPU attempts before budget-dependent launches")
    if (
        budget["qualification_attempts_remaining"] <= 0
        or budget["gpu_budget_charge_hours"] >= budget["limits"]["gpu_hours"]
        or budget["cpu_core_hours_upper_bound"] >= budget["limits"]["cpu_core_hours"]
    ):
        raise RuntimeError("parent resource budget exhausted")
    total = sum(
        p.stat().st_size
        for root in ("l1-qualification", "l1-resume")
        for p in (LAB / "campaigns" / root).rglob("*")
        if p.is_file()
    )
    if total >= budget["limits"]["storage_gib"] * 1024**3:
        raise RuntimeError("parent storage budget exhausted")
    import shutil

    disk = shutil.disk_usage(LAB)
    if disk.free < max(100 * 1024**3, 0.1 * disk.total):
        raise RuntimeError("disk reserve")
    if datetime.now(timezone.utc) >= datetime.fromisoformat(
        budget["conservative_expiry_utc"]
    ):
        raise RuntimeError("parent campaign expired")
    write(
        "RESOURCE-PREFLIGHT.json",
        {
            "captured_at": q2.utc_now(),
            "campaign_storage_bytes": total,
            "disk_free_bytes": disk.free,
            "cpu_core_hours_upper_bound": budget["cpu_core_hours_upper_bound"],
            "gpu_hours": budget["gpu_solver_hours"],
            "qualification_remaining": budget["qualification_attempts_remaining"],
        },
    )
    return budget


def active_window_hours(windows, now):
    total = 0.0
    for row in windows:
        start = datetime.fromisoformat(row["started_at"])
        end = (
            datetime.fromisoformat(row["finished_at"])
            if row.get("finished_at")
            else now
        )
        if end < start:
            raise ValueError("resource window ends before it begins")
        total += (end - start).total_seconds() / 3600
    return total


def resource_windows():
    path = OUT / "RESOURCE-ACTIVE-WINDOWS.json"
    if not path.exists():
        capture = json.loads((OUT / "HISTORICAL-CPU-RESERVE.json").read_text())[
            "captured_at"
        ]
        write(path.name, [{"started_at": capture, "finished_at": None}])
    return json.loads(path.read_text())


def post_reserve_hours():
    return active_window_hours(resource_windows(), datetime.now(timezone.utc))


def begin_activity_window():
    windows = resource_windows()
    if windows[-1].get("finished_at"):
        windows.append({"started_at": q2.utc_now(), "finished_at": None})
        write("RESOURCE-ACTIVE-WINDOWS.json", windows)


def finish_activity_window():
    windows = resource_windows()
    if not windows[-1].get("finished_at"):
        windows[-1]["finished_at"] = q2.utc_now()
        write("RESOURCE-ACTIVE-WINDOWS.json", windows)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("task", choices=["ledger", "geometry", "q2"])
    a = p.parse_args()
    {"ledger": ledger, "geometry": geometry, "q2": trajectories}[a.task]()
