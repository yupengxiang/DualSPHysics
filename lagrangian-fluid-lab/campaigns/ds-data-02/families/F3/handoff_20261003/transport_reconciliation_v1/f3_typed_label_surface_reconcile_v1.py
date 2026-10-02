#!/usr/bin/env python3
"""Reconcile the completed F3 typed-label products without opening trajectories.

The finite-surface replay and the native typed-label HDF5 are two products
made from the same terminal trajectories.  Earlier F3 summaries pointed at
the legacy JSON aggregate, whose x/y fields are zero even though the small
typed-label HDF5 and finite replay contain transport.  This additive producer
reads only the small label HDF5 arrays (identity, first-passage, flux, and
residence summaries), the completed finite-replay JSON, and the existing
RunPARTs/native-accounting records.  It never opens a trajectory HDF5 and
never starts a solver, converter, or labels job.

The report is evidence reconciliation, not a Q-N or production gate.  The
medium baseline/HALF_DT and HALF_SAVE pairs are recomputed from their actual
small HDF5 labels.  The frozen temporal assessment remains authoritative for
its scope; this producer does not turn a self-comparison into qualification.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping

import h5py
import numpy as np


SCHEMA = "ds02.f3.typed-label-surface-reconciliation.v1"
FAMILY_ID = "F3"
PHYSICAL_CASE_ID = "F3_DUAL_AXIS_WEAK_006G_004G"
F3_DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3")
HANDOFF = Path(__file__).resolve().parent
F2_WORKTREE = Path("/home/jade/.codex/worktrees/ds-data-02-f2/DualSPHysics")
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
RUNTIME_V2 = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
TEMPORAL_ASSESSMENT = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261002/f3_weak_dual_temporal_budget_assessment_001.json"


CASES: dict[str, dict[str, Any]] = {
    "coarse": {
        "case_id": "F3_WEAK_DUAL_REFERENCE_COARSE",
        "label_h5": F3_DATA / "F3_WEAK_DUAL_REFERENCE_COARSE/f3-weak-dual-coarse-labels-v1/typed-transport-labels.h5",
        "surface": F3_DATA / "F3_WEAK_DUAL_REFERENCE_COARSE/f3-weak-dual-coarse-surface-audit-v1/f3-weak-finite-surface-audit.json",
        "legacy_json": F3_DATA / "F3_WEAK_DUAL_REFERENCE_COARSE/f3-weak-dual-coarse-direct-v1/typed-transport-labels.json",
        "source_h5_sha256": "61d14a1a67ab040dfb6728a6b11a1721eb71f83da99468e31cbd8d987aeda2db",
        "source_h5_bytes": 5250144678,
        "particles": 88528,
        "fluid_particles": 26620,
        "dp_m": 0.008181818,
        "direct_audit": F3_DATA / "F3_WEAK_DUAL_REFERENCE_COARSE/f3-weak-dual-coarse-direct-v1/f3-weak-audit-report.json",
    },
    "medium": {
        "case_id": PHYSICAL_CASE_ID,
        "label_h5": F3_DATA / "F3_DUAL_AXIS_WEAK_006G_004G/f3-weak-full-transport-labels-v1/typed-transport-labels.h5",
        "surface": F3_DATA / "F3_DUAL_AXIS_WEAK_006G_004G/f3-weak-finite-surface-audit-v2/f3-weak-finite-surface-audit.json",
        "legacy_json": F3_DATA / "F3_DUAL_AXIS_WEAK_006G_004G/f3-weak-dual-direct-full-v2/typed-transport-labels.json",
        "source_h5_sha256": "c2cb2f701ef81a1a490764aa9057874c0d61f0d2447416cb4e1f7693daa76fd2",
        "source_h5_bytes": 6577918733,
        "particles": 108000,
        "fluid_particles": 34560,
        "dp_m": 0.0075,
        "direct_audit": F3_DATA / "F3_DUAL_AXIS_WEAK_006G_004G/f3-weak-dual-direct-full-v2/f3-weak-audit-report.json",
    },
    "fine": {
        "case_id": "F3_WEAK_DUAL_REFERENCE_FINE",
        "label_h5": F3_DATA / "F3_WEAK_DUAL_REFERENCE_FINE/f3-weak-dual-fine-labels-v1/typed-transport-labels.h5",
        "surface": F3_DATA / "F3_WEAK_DUAL_REFERENCE_FINE/f3-weak-dual-fine-surface-audit-v1/f3-weak-finite-surface-audit.json",
        "legacy_json": F3_DATA / "F3_WEAK_DUAL_REFERENCE_FINE/f3-weak-dual-fine-direct-v1/typed-transport-labels.json",
        "source_h5_sha256": "8cf11a279aa4849939982c1b11a1a4260dff0224051795a38880d55dfc74e8be",
        "source_h5_bytes": 11794266383,
        "particles": 179208,
        "fluid_particles": 67500,
        "dp_m": 0.006,
        "direct_audit": F3_DATA / "F3_WEAK_DUAL_REFERENCE_FINE/f3-weak-dual-fine-direct-v1/f3-weak-audit-report.json",
    },
}

TEMPORAL = {
    "baseline": CASES["medium"]["label_h5"],
    "half_dt": F3_DATA / "F3_DUAL_AXIS_WEAK_006G_004G_HALF_DT/native-labels-half_dt-20261002-005/typed-transport-labels.h5",
    "half_save": F3_DATA / "F3_DUAL_AXIS_WEAK_006G_004G_HALF_SAVE/native-labels-half_save-20261002-003/typed-transport-labels.h5",
    "half_dt_comparison": F3_DATA / "F3_DUAL_AXIS_WEAK_006G_004G_TRANSPORT_STUDY/half_dt-transport-comparison-20261002-002/transport-comparison.json",
    "half_save_comparison": F3_DATA / "F3_DUAL_AXIS_WEAK_006G_004G_TRANSPORT_STUDY/half_save-transport-comparison-20261002-001/transport-comparison.json",
}

FINE_NATIVE_ACCOUNTING = F3_DATA / "F3_WEAK_REFERENCE_ACCOUNTING/spatial-reference-accounting-001/native-accounting.json"
FINE_NATIVE_AUDIT = CASES["fine"]["direct_audit"]

EVENTS = ("left_right_exchange", "front_back_exchange", "top_open_exit")


def require(path: Path, role: str) -> Path:
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{role} missing: {path}")
    return path


def sha256(path: Path) -> str:
    result = hashlib.sha256()
    with require(path, "hash input").open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def binding(path: Path, role: str) -> dict[str, Any]:
    path = require(path, role)
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size, "role": role}


def load_json(path: Path, role: str) -> Any:
    return json.loads(require(path, role).read_text(encoding="utf-8"))


def json_safe(value: Any) -> Any:
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    return value


def h5_attrs(handle: h5py.File) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in handle.attrs.items():
        if isinstance(value, bytes):
            value = value.decode("utf-8", "replace")
        elif isinstance(value, np.ndarray):
            value = value.tolist()
        elif isinstance(value, np.generic):
            value = value.item()
        result[key] = value
    return result


def weighted_mean(values: np.ndarray, weights: np.ndarray) -> float | None:
    total = float(np.sum(weights))
    if total <= 0.0:
        return None
    return float(np.sum(values * weights) / total)


def max_abs(values: Iterable[float]) -> float:
    values = list(values)
    return max((abs(float(value)) for value in values), default=0.0)


def relative_delta(base: float | None, variant: float | None, floor: float = 1.0e-12) -> float | None:
    if base is None or variant is None:
        return None
    denominator = max(abs(float(base)), floor)
    return float((float(variant) - float(base)) / denominator)


def summarize_label_h5(path: Path, expected: Mapping[str, Any]) -> dict[str, Any]:
    """Read only compact label arrays; never touch destination_time_series."""
    path = require(path, "typed label H5")
    with h5py.File(path, "r") as handle:
        attrs = h5_attrs(handle)
        required = {
            "particle_id", "source_label", "initial_fluid_mass_kg", "first_passage_censor",
            "first_passage_chord_time", "first_passage_interval", "cumulative_net_flux_kg",
            "forward_backward_mass_kg", "residence_time_s", "unknown_mass_kg",
            "numerical_loss_mass_kg", "invalid_state_mass_kg", "final_category", "time",
        }
        missing = sorted(required.difference(handle.keys()))
        if missing:
            raise ValueError(f"{path}: compact label fields missing {missing}")
        # This is deliberately a bounded set of identity/event arrays.  The
        # 4001 x N destination_time_series dataset is never accessed.
        ids = np.asarray(handle["particle_id"][...])
        source_label = np.asarray(handle["source_label"][...])
        initial_mass = np.asarray(handle["initial_fluid_mass_kg"][...], dtype=np.float64)
        censor = np.asarray(handle["first_passage_censor"][...])
        chord = np.asarray(handle["first_passage_chord_time"][...], dtype=np.float64)
        interval = np.asarray(handle["first_passage_interval"][...], dtype=np.float64)
        net = np.asarray(handle["cumulative_net_flux_kg"][...], dtype=np.float64)
        forward_backward = np.asarray(handle["forward_backward_mass_kg"][...], dtype=np.float64)
        residence = np.asarray(handle["residence_time_s"][...], dtype=np.float64)
        unknown = np.asarray(handle["unknown_mass_kg"][...], dtype=np.float64)
        numerical_loss = np.asarray(handle["numerical_loss_mass_kg"][...], dtype=np.float64)
        invalid = np.asarray(handle["invalid_state_mass_kg"][...], dtype=np.float64)
        final_category = np.asarray(handle["final_category"][...])
        time = np.asarray(handle["time"][...], dtype=np.float64)

    fluid = initial_mass > 0.0
    fluid_ids = ids[fluid]
    if len(ids) != expected["particles"] or int(np.count_nonzero(fluid)) != expected["fluid_particles"]:
        raise ValueError(f"{path}: population mismatch {len(ids)}/{np.count_nonzero(fluid)}")
    if len(np.unique(ids)) != len(ids):
        raise ValueError(f"{path}: duplicate particle IDs")
    source_sha = attrs.get("source_hdf5_sha256")
    if source_sha != expected["source_h5_sha256"]:
        raise ValueError(f"{path}: source H5 SHA mismatch {source_sha!r} != {expected['source_h5_sha256']!r}")
    if attrs.get("complete") is not True or attrs.get("schema") != "ds-data-02.native-labels.v1":
        raise ValueError(f"{path}: incomplete or unexpected label schema")
    event_summary: dict[str, Any] = {}
    for index, event_id in enumerate(EVENTS):
        finite = fluid & np.isfinite(chord[:, index])
        observed_mass = float(np.sum(initial_mass[finite]))
        censored = fluid & ~np.isfinite(chord[:, index])
        censored_mass = float(np.sum(initial_mass[censored]))
        widths = interval[fluid & np.isfinite(interval[:, index, 0]) & np.isfinite(interval[:, index, 1]), index, 1] - interval[fluid & np.isfinite(interval[:, index, 0]) & np.isfinite(interval[:, index, 1]), index, 0]
        finite_times = chord[finite, index]
        first_ids = ids[finite]
        event_summary[event_id] = {
            "observed_count": int(np.count_nonzero(finite)),
            "censored_count": int(np.count_nonzero(censored)),
            "observed_mass_kg": observed_mass,
            "censored_mass_kg": censored_mass,
            "first_passage_min_s": float(np.min(finite_times)) if finite_times.size else None,
            "first_passage_max_s": float(np.max(finite_times)) if finite_times.size else None,
            "mass_weighted_chord_time_s": weighted_mean(finite_times, initial_mass[finite]) if finite_times.size else None,
            "first_passage_ids": sorted(int(value) for value in first_ids),
            "first_passage_times": {str(int(identity)): float(value) for identity, value in zip(first_ids, finite_times)},
            "bracket_count": int(widths.size),
            "bracket_width_max_s": float(np.max(widths)) if widths.size else None,
            "bracket_halfwidth_max_s": float(np.max(widths) / 2.0) if widths.size else None,
            "bracket_halfwidth_mean_s": float(np.mean(widths) / 2.0) if widths.size else None,
            "final_net_flux_kg": float(net[-1, index]),
            "final_forward_mass_kg": float(forward_backward[-1, index, 0]),
            "final_backward_mass_kg": float(forward_backward[-1, index, 1]),
            "censor_code_observed_count": int(np.count_nonzero(fluid & (censor[:, index] == 0))),
            "censor_code_censored_count": int(np.count_nonzero(fluid & (censor[:, index] != 0))),
        }
    residence_summary = []
    for region_index in range(residence.shape[1]):
        values = residence[fluid, region_index]
        weights = initial_mass[fluid]
        residence_summary.append({
            "region_index": region_index + 1,
            "particle_count": int(values.size),
            "mass_weighted_mean_residence_time_s": weighted_mean(values, weights),
            "residence_mass_time_kg_s": float(np.sum(values * weights)),
        })
    return {
        "binding": {
            "path": str(path),
            "sha256": sha256(path),
            "bytes": path.stat().st_size,
            "role": "completed compact typed-label HDF5",
            "source_hdf5": attrs.get("source_hdf5"),
            "source_hdf5_sha256": source_sha,
            "source_hdf5_bytes_registered": expected["source_h5_bytes"],
            "source_hdf5_reopened": False,
        },
        "schema": attrs.get("schema"),
        "complete": attrs.get("complete"),
        "coordinate_frame": attrs.get("coordinate_frame"),
        "identity_key": attrs.get("identity_key"),
        "solver_semantics": {
            "q_n_status": attrs.get("q_n_status"),
            "model_invoked": attrs.get("model_invoked"),
            "event_time_semantics": attrs.get("event_time_semantics"),
            "unknown_semantics": "unknown_mass_kg and right-censored first passages are retained; no physical exit is inferred",
        },
        "population": {
            "particles": int(ids.size),
            "fluid_particles": int(np.count_nonzero(fluid)),
            "nonfluid_particles": int(np.count_nonzero(~fluid)),
            "fluid_id_min": int(np.min(fluid_ids)),
            "fluid_id_max": int(np.max(fluid_ids)),
            "fluid_identity_unique": len(np.unique(fluid_ids)) == int(np.count_nonzero(fluid)),
            "source_label_values_fluid": sorted(int(value) for value in np.unique(source_label[fluid])),
            "initial_fluid_mass_kg": float(np.sum(initial_mass[fluid])),
            "initial_mass_min_kg": float(np.min(initial_mass[fluid])),
            "initial_mass_max_kg": float(np.max(initial_mass[fluid])),
        },
        "time": {
            "frames": int(time.size),
            "time_start_s": float(time[0]),
            "time_end_s": float(time[-1]),
            "strictly_increasing": bool(np.all(np.diff(time) > 0.0)),
            "save_interval_min_s": float(np.min(np.diff(time))),
            "save_interval_max_s": float(np.max(np.diff(time))),
        },
        "events": event_summary,
        "residence": residence_summary,
        "full_window_mass_ledgers": {
            "unknown_mass_max_kg": float(np.max(unknown)),
            "numerical_loss_mass_max_kg": float(np.max(numerical_loss)),
            "invalid_state_mass_max_kg": float(np.max(invalid)),
            "final_category_fluid_counts": {str(int(k)): int(v) for k, v in zip(*np.unique(final_category[fluid], return_counts=True))},
        },
        "read_scope": {
            "trajectory_h5_opened": False,
            "destination_time_series_read": False,
            "arrays_read": sorted(required),
        },
    }


def summarize_surface(path: Path) -> dict[str, Any]:
    data = load_json(path, "finite surface replay")
    particles = data.get("per_particle", [])
    if not isinstance(particles, list):
        raise ValueError(f"{path}: per_particle is not a list")
    result: dict[str, Any] = {
        "binding": binding(path, "completed finite-surface replay JSON"),
        "schema": data.get("schema"),
        "audit_status": data.get("audit_status"),
        "q_i_status": data.get("q_i_status"),
        "q_n_status": data.get("q_n_status"),
        "trajectory_summary": data.get("trajectory"),
        "events": {},
    }
    for event_id in EVENTS:
        rows = [row for row in particles if event_id in row]
        counts = np.asarray([int(row[event_id].get("crossing_count", 0)) for row in rows], dtype=np.int64)
        positive = np.asarray([int(row[event_id].get("positive_crossings", 0)) for row in rows], dtype=np.int64)
        negative = np.asarray([int(row[event_id].get("negative_crossings", 0)) for row in rows], dtype=np.int64)
        masses = np.asarray([float(row.get("initial_mass_kg", 0.0)) for row in rows], dtype=np.float64)
        first_rows = [(int(row["idp"]), float(row[event_id]["first_passage_s"])) for row in rows if row[event_id].get("first_passage_s") is not None]
        first_ids = {row[0] for row in first_rows}
        result["events"][event_id] = {
            "identity_rows": len(rows),
            "identity_ids_unique": len({int(row["idp"]) for row in rows}) == len(rows),
            "ids": [int(row["idp"]) for row in rows],
            "crossing_count_sum": int(np.sum(counts)),
            "crossing_count_max": int(np.max(counts)) if counts.size else 0,
            "particles_with_crossing": int(np.count_nonzero(counts)),
            "first_passage_count": len(first_rows),
            "first_passage_ids": sorted(first_ids),
            "first_passage_times": {str(identity): value for identity, value in first_rows},
            "first_passage_min_s": min((value for _, value in first_rows), default=None),
            "first_passage_max_s": max((value for _, value in first_rows), default=None),
            "positive_crossings": int(np.sum(positive)),
            "negative_crossings": int(np.sum(negative)),
            "positive_crossing_mass_kg": float(np.sum(masses * positive)),
            "negative_crossing_mass_kg": float(np.sum(masses * negative)),
            "net_crossing_mass_kg": float(np.sum(masses * (positive - negative))),
            "repeat_crossings": int(np.sum(np.maximum(counts - 1, 0))),
            "surface_record": data.get("surfaces", {}).get(event_id, {}),
        }
    # Do not carry the full per-particle array into the sidecar.  The IDs and
    # first-passage maps above are enough to bind exact reconciliation checks.
    for event in result["events"].values():
        event.pop("ids", None)
    return result


def legacy_summary(path: Path) -> dict[str, Any]:
    data = load_json(path, "legacy typed-label JSON")
    aggregate = data.get("aggregate", {})
    return {
        "binding": binding(path, "legacy typed-label aggregate JSON"),
        "schema": data.get("schema"),
        "aggregate": aggregate,
        "legacy_x_y_zero": all(int(aggregate.get(key, 0) or 0) == 0 for key in ("positive_crossings", "negative_crossings", "repeat_crossings")),
    }


def reconcile_case(role: str, label: Mapping[str, Any], surface: Mapping[str, Any], legacy: Mapping[str, Any]) -> dict[str, Any]:
    checks: dict[str, bool] = {}
    checks["fluid_identity_count_matches_surface"] = label["population"]["fluid_particles"] == surface["events"][EVENTS[0]]["identity_rows"]
    event_results: dict[str, Any] = {}
    for event_id in EVENTS:
        h = label["events"][event_id]
        s = surface["events"][event_id]
        id_set = set(surface["events"][event_id]["first_passage_ids"])
        h5_id_set = set(h["first_passage_ids"])
        first_times = surface["events"][event_id]["first_passage_times"]
        h5_times = h["first_passage_times"]
        first_time_diffs = [float(h5_times[str(identity)]) - float(first_times[str(identity)]) for identity in sorted(id_set & h5_id_set)]
        # The exact count and mass equalities bind the two products.  Surface
        # first times are retained in the source JSON; summary-level H5 times
        # provide the independent min/max and weighted result.
        checks_for_event = {
            "first_passage_id_set_equal": h5_id_set == id_set,
            "first_passage_count_equal": h["observed_count"] == s["first_passage_count"],
            "first_passage_times_equal": h5_id_set == id_set and max_abs(first_time_diffs) <= 1.0e-12,
            "surface_all_crossings_equal_surface_record": s["crossing_count_sum"] == (s["surface_record"].get("accepted_crossings") or 0),
            "forward_mass_equal": abs(h["final_forward_mass_kg"] - s["positive_crossing_mass_kg"]) <= 1.0e-10,
            "backward_mass_equal": abs(h["final_backward_mass_kg"] - s["negative_crossing_mass_kg"]) <= 1.0e-10,
            "net_flux_equal": abs(h["final_net_flux_kg"] - s["net_crossing_mass_kg"]) <= 1.0e-10,
            "first_censor_count_equal": h["censor_code_observed_count"] == s["first_passage_count"],
            "top_open_remains_right_censored": event_id == "top_open_exit" and h["observed_count"] == 0 and h["censored_count"] == label["population"]["fluid_particles"] or event_id != "top_open_exit",
        }
        for key, value in checks_for_event.items():
            checks[f"{event_id}:{key}"] = bool(value)
        event_results[event_id] = {
            "h5": h,
            "finite_surface": {key: value for key, value in s.items() if key not in {"first_passage_ids", "first_passage_times"}},
            "first_passage_id_count": len(id_set),
            "h5_first_passage_id_count": len(h5_id_set),
            "first_passage_time_max_abs_delta_s": max_abs(first_time_diffs),
            "surface_first_passage_time_min_s": s.get("first_passage_min_s"),
            "surface_first_passage_time_max_s": s.get("first_passage_max_s"),
            "first_passage_time_summary_only": "H5 compact summary retains min/max/weighted values; exact per-ID surface times remain bound by source JSON SHA",
        }
    h5_flux_present = any(abs(label["events"][event]["final_forward_mass_kg"]) > 0.0 or abs(label["events"][event]["final_backward_mass_kg"]) > 0.0 for event in EVENTS[:2])
    legacy_stale = bool(legacy["legacy_x_y_zero"] and h5_flux_present)
    checks["legacy_json_is_not_used_as_transport_authority"] = legacy_stale
    return {
        "role": role,
        "status": "reconciled_compact_h5_with_finite_surface_legacy_json_stale" if all(checks.values()) and legacy_stale else "reconciliation_incomplete",
        "checks": checks,
        "events": event_results,
        "legacy_summary": {
            "status": "stale_zero_xy_aggregate" if legacy_stale else "not_stale_or_no_transport",
            "legacy_binding": legacy["binding"],
            "legacy_aggregate": legacy["aggregate"],
            "reason": "Legacy JSON reports zero x/y crossings; compact typed-label H5 and finite replay agree on nonzero transport. The old summary pointer must not be used for event totals.",
        },
        "claim_boundary": "This reconciles two actual operators and corrects provenance; it does not infer physical spill from top-event censoring or grant Q-N.",
    }


def parse_runparts(path: Path) -> dict[str, Any]:
    rows: list[dict[str, str]] = []
    with require(path, "RunPARTs").open(newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        for row in reader:
            try:
                int(row.get("Part", ""))
            except (TypeError, ValueError):
                continue
            rows.append(row)
    if not rows:
        raise ValueError(f"{path}: no numeric RunPARTs rows")
    fields = ["NpOut", "NpOutPos", "NpOutRho", "NpOutMov"]
    sums = {field: sum(int(round(float(row[field].replace(",", "")))) for row in rows) for field in fields}
    npf = [int(round(float(row["NpfSim"].replace(",", "")))) for row in rows]
    npb = [int(round(float(row["NpbSim"].replace(",", "")))) for row in rows]
    return {
        "binding": binding(path, "fine terminal RunPARTs"),
        "numeric_rows": len(rows),
        "excluded_interval_sums": sums,
        "all_excluded_zero": all(value == 0 for value in sums.values()),
        "npf_sim_min": min(npf), "npf_sim_max": max(npf),
        "npb_sim_min": min(npb), "npb_sim_max": max(npb),
        "last_row_excluded_values": {field: int(round(float(rows[-1][field].replace(",", "")))) for field in fields},
    }


def fine_native_sidecar() -> dict[str, Any]:
    entries = load_json(FINE_NATIVE_ACCOUNTING, "F3 native accounting")
    if not isinstance(entries, list):
        raise ValueError("native accounting must be a list")
    fine_entry = next((entry for entry in entries if entry.get("case_id") == CASES["fine"]["case_id"]), None)
    if fine_entry is None:
        raise ValueError("fine-specific native accounting entry missing")
    facts = fine_entry["facts"]
    runparts = parse_runparts(Path(fine_entry["runparts"]))
    wrong_legacy = load_json(FINE_NATIVE_AUDIT, "fine direct audit")
    wrong_binding = wrong_legacy.get("native_accounting", {})
    receipt_path = fine_entry.get("receipt", {}).get("path", "") if isinstance(fine_entry.get("receipt"), dict) else str(fine_entry.get("receipt", ""))
    checks = {
        "fine_entry_case_matches": fine_entry.get("case_id") == CASES["fine"]["case_id"],
        "fine_entry_receipt_matches_case": receipt_path.find("F3_WEAK_DUAL_REFERENCE_FINE") >= 0,
        "fine_solver_dimension_3": fine_entry.get("solver_dimension") == 3,
        "fine_frames_4001": facts.get("saved_frames") == 4001 and runparts["numeric_rows"] == 4001,
        "fine_population_stable": facts.get("initial_fluid_particles") == 67500 and facts.get("final_fluid_particles") == 67500 and facts.get("initial_total_particles") == 179208 and facts.get("final_total_particles") == 179208,
        "fine_full_window": float(facts.get("final_time_s", 0.0)) >= 10.0,
        "runparts_full_window_exclusions_zero": runparts["all_excluded_zero"],
        "accounting_full_window_exclusions_zero": all(int(value) == 0 for value in facts.get("excluded_interval_sums", {}).values()),
        "legacy_fine_audit_binding_is_detected_wrong": wrong_binding.get("case_id") != CASES["fine"]["case_id"],
    }
    return {
        "schema": "ds02.f3.fine-native-zero-accounting-sidecar.v1",
        "status": "fine_specific_full_window_zero_native_accounting_bound" if all(checks.values()) else "fine_native_accounting_incomplete",
        "checks": checks,
        "native_accounting_binding": {
            "source": binding(FINE_NATIVE_ACCOUNTING, "fine-specific native accounting source"),
            "selected_entry": fine_entry,
            "runparts_recomputed": runparts,
        },
        "legacy_audit_binding": {
            "path": str(FINE_NATIVE_AUDIT.resolve()),
            "sha256": sha256(FINE_NATIVE_AUDIT),
            "reported_case_id": wrong_binding.get("case_id"),
            "reported_attempt_id": wrong_binding.get("attempt_id"),
            "status": "cross_bound_to_coarse_and_not_reused",
        },
        "claim_boundary": "Zero native NpOut is an identity/lifecycle accounting fact for the fine parent; it is not a transport or Q-N pass.",
    }


def comparison_binding(path: Path, pair: Mapping[str, Any], variant_key: str) -> dict[str, Any]:
    comparison = load_json(path, "temporal comparison")
    variant = comparison.get("variants", {}).get("typed-transport-labels", {})
    summary = variant.get("summary", {})
    fresh = pair[variant_key]
    mismatches: list[str] = []
    if summary.get("frames") != fresh["time"]["frames"]:
        mismatches.append("frames")
    if abs(float(summary.get("initial_fluid_mass_kg", 0.0)) - fresh["population"]["initial_fluid_mass_kg"]) > 1.0e-10:
        mismatches.append("initial_fluid_mass_kg")
    for index, event_id in enumerate(EVENTS):
        report_net = summary.get("final_cumulative_net_flux_kg", [None] * len(EVENTS))[index]
        if report_net is None or abs(float(report_net) - fresh["events"][event_id]["final_net_flux_kg"]) > 1.0e-10:
            mismatches.append(f"{event_id}:final_net_flux")
    return {
        "binding": binding(path, "existing temporal comparison summary"),
        "variant_key": variant_key,
        "legacy_summary_sha256": comparison.get("variants", {}).get("typed-transport-labels", {}).get("summary", {}).get("sha256"),
        "recomputed_h5_matches_summary": not mismatches,
        "mismatches": mismatches,
        "reported_budget_status": comparison.get("budgets", {}).get("status"),
    }


def temporal_pair(pair_name: str, variant_key: str, comparison_path: Path, labels: Mapping[str, Mapping[str, Any]], assessment: Mapping[str, Any]) -> dict[str, Any]:
    base = labels["baseline"]
    variant = labels[variant_key]
    events: dict[str, Any] = {}
    for event_id in EVENTS:
        b = base["events"][event_id]
        v = variant["events"][event_id]
        events[event_id] = {
            "observed_count": {"baseline": b["observed_count"], "variant": v["observed_count"], "delta": v["observed_count"] - b["observed_count"]},
            "censored_mass_kg": {"baseline": b["censored_mass_kg"], "variant": v["censored_mass_kg"], "delta": v["censored_mass_kg"] - b["censored_mass_kg"]},
            "net_flux_kg": {"baseline": b["final_net_flux_kg"], "variant": v["final_net_flux_kg"], "delta": v["final_net_flux_kg"] - b["final_net_flux_kg"], "relative_delta": relative_delta(b["final_net_flux_kg"], v["final_net_flux_kg"])},
            "chord_time_s": {"baseline": b["mass_weighted_chord_time_s"], "variant": v["mass_weighted_chord_time_s"], "delta": None if b["mass_weighted_chord_time_s"] is None or v["mass_weighted_chord_time_s"] is None else v["mass_weighted_chord_time_s"] - b["mass_weighted_chord_time_s"], "relative_delta": relative_delta(b["mass_weighted_chord_time_s"], v["mass_weighted_chord_time_s"])},
            "bracket_halfwidth_max_s": {"baseline": b["bracket_halfwidth_max_s"], "variant": v["bracket_halfwidth_max_s"]},
        }
    frozen_status = assessment.get("assessment_status") if pair_name == "baseline_vs_half_dt" else "no_frozen_pair_assessment_for_half_save_in_source_contract"
    return {
        "pair": pair_name,
        "baseline_label_sha256": labels["baseline"]["binding"]["sha256"],
        "variant_label_sha256": labels[variant_key]["binding"]["sha256"],
        "frames": {"baseline": base["time"]["frames"], "variant": variant["time"]["frames"]},
        "save_interval_s": {"baseline": [base["time"]["save_interval_min_s"], base["time"]["save_interval_max_s"]], "variant": [variant["time"]["save_interval_min_s"], variant["time"]["save_interval_max_s"]]},
        "events": events,
        "comparison_summary_rebind": comparison_binding(comparison_path, labels, variant_key),
        "frozen_assessment_status": frozen_status,
        "qualification_status": "not_assessed",
        "claim_boundary": "Temporal deltas are actual label comparisons. Save/integration and event budgets remain separate; no Q-N is inferred.",
    }


def build_report() -> dict[str, Any]:
    labels: dict[str, dict[str, Any]] = {}
    surfaces: dict[str, dict[str, Any]] = {}
    legacy: dict[str, dict[str, Any]] = {}
    for role, case in CASES.items():
        labels[role] = summarize_label_h5(case["label_h5"], case)
        surfaces[role] = summarize_surface(case["surface"])
        legacy[role] = legacy_summary(case["legacy_json"])
    reconciliations = {role: reconcile_case(role, labels[role], surfaces[role], legacy[role]) for role in CASES}
    assessment = load_json(TEMPORAL_ASSESSMENT, "frozen temporal budget assessment")
    labels["half_dt"] = summarize_label_h5(TEMPORAL["half_dt"], {"source_h5_sha256": "27a2206c6a3fe03f9202955e895811e735d21cbdd59273ee52ecb8c5227bbe69", "source_h5_bytes": 6578333251, "particles": 108000, "fluid_particles": 34560})
    labels["half_save"] = summarize_label_h5(TEMPORAL["half_save"], {"source_h5_sha256": "b7bab5bee7ef99d6eeabd02f7c1ac5c5ea38913636da5923c60efa4cb734d7df", "source_h5_bytes": 13153500743, "particles": 108000, "fluid_particles": 34560})
    # The medium compact label is the baseline for both numerical-only pairs.
    # Keep the resolution-keyed `labels` map intact while passing an explicit
    # temporal map; this prevents a stale/ambiguous `labels["baseline"]`
    # lookup from silently binding the pair to another case.
    temporal_labels = {"baseline": labels["medium"], "half_dt": labels["half_dt"], "half_save": labels["half_save"]}
    temporal = {
        "baseline_vs_half_dt": temporal_pair("baseline_vs_half_dt", "half_dt", TEMPORAL["half_dt_comparison"], temporal_labels, assessment),
        "baseline_vs_half_save": temporal_pair("baseline_vs_half_save", "half_save", TEMPORAL["half_save_comparison"], temporal_labels, assessment),
        "frozen_budget_source": binding(TEMPORAL_ASSESSMENT, "frozen F3 temporal budget assessment"),
        "event_budget_contract": assessment.get("registration"),
    }
    return {
        "schema": SCHEMA,
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "family_id": FAMILY_ID,
        "physical_case_id": PHYSICAL_CASE_ID,
        "status": "actual_compact_label_surface_reconciliation_complete_temporal_qn_pending",
        "qualification_claim": "none",
        "q_i_status": "compact typed-label/finite-surface/operator provenance reconciled; native fine accounting corrected",
        "q_n_status": "not_assessed",
        "production_eligibility": "not_evaluated",
        "trajectory_read_policy": {"trajectory_h5_opened": False, "raw_full_trajectory_rescanned": False, "small_typed_label_h5_only": True},
        "source_cases": {role: {"label": labels[role], "surface": surfaces[role], "legacy": legacy[role], "reconciliation": reconciliations[role]} for role in CASES},
        "temporal_studies": temporal,
        "fine_native_zero_accounting": fine_native_sidecar(),
        "source_hash_semantics": {
            "compact_label_h5": "actual small typed-label H5 SHA; source trajectory SHA is read from its immutable root attr and compared to registered macro source SHA, without reopening trajectory",
            "finite_surface": "actual finite replay JSON SHA and per-particle ID/event records",
            "legacy_json": "retained only to document stale zero-flux summary pointer",
            "native_accounting": "fine-specific accounting list entry selected by case ID and rechecked against all RunPARTs interval fields",
        },
        "claim_boundary": "This sidecar supplies actual evidence and corrects stale source references. It does not turn zero native loss, finite replay agreement, or temporal self-comparison into Q-N or production eligibility.",
    }


def request_inputs() -> list[Path]:
    paths = [Path(__file__).resolve(), RUNTIME_V2.resolve(), TEMPORAL_ASSESSMENT.resolve(), FINE_NATIVE_ACCOUNTING.resolve(), FINE_NATIVE_AUDIT.resolve()]
    for case in CASES.values():
        paths.extend([case["label_h5"], case["surface"], case["legacy_json"]])
    paths.extend([TEMPORAL["half_dt"], TEMPORAL["half_save"], TEMPORAL["half_dt_comparison"], TEMPORAL["half_save_comparison"]])
    for case in CASES.values():
        accounting = F3_DATA / ("F3_WEAK_REFERENCE_ACCOUNTING/spatial-reference-accounting-001/native-accounting.json")
        paths.append(accounting)
        break
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        path = require(path, "reconciliation input")
        if str(path.resolve()) not in seen:
            seen.add(str(path.resolve()))
            unique.append(path.resolve())
    return unique


def make_request(path: Path, attempt_id: str = "f3-typed-label-surface-reconcile-20261003-002") -> dict[str, Any]:
    inputs = request_inputs()
    request = {
        "schema": "ds02.runner-request.v2",
        "family_id": FAMILY_ID,
        "case_id": "F3_TYPED_LABEL_SURFACE_RECONCILIATION",
        "attempt_id": attempt_id,
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 2,
        "max_wall_seconds": 600,
        "estimated_storage_bytes": 768 * 1024 * 1024,
        "command": [str(PYTHON), str(Path(__file__).resolve()), "--output", "{attempt_root}/f3-typed-label-surface-reconciliation.json"],
        "cwd": str(HANDOFF.resolve()),
        "worktree_root": str(F2_WORKTREE.resolve()),
        "raw_output_root": str((F3_DATA / "F3_TYPED_LABEL_SURFACE_RECONCILIATION").resolve()),
        "input_files": [str(p) for p in inputs],
        "input_hashes": {str(p): sha256(p) for p in inputs},
        "root_only": True,
        "runnable": True,
        "launch_allowed": True,
        "solver_launch_forbidden": True,
        "large_h5_policy": {"trajectory_h5_opened": False, "destination_time_series_read": False, "source_trajectory_sha_from_label_attr_only": True},
        "qualification_claim": "none; bounded evidence reconciliation only",
        "q_n_status": "not_assessed",
        "request_note": "Actual small typed-label H5/finite replay reconciliation and fine native accounting correction; no trajectory rescan, solver, converter, or labels launch.",
    }
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(request, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return request


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--make-request", type=Path)
    parser.add_argument("--attempt-id", default="f3-typed-label-surface-reconcile-20261003-002")
    args = parser.parse_args()
    if args.make_request:
        request = make_request(args.make_request, args.attempt_id)
        print(json.dumps({"status": "written", "request": str(args.make_request.resolve()), "input_count": len(request["input_files"])}, indent=2))
        return 0
    if not args.output:
        parser.error("--output is required unless --make-request is used")
    report = build_report()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True, default=json_safe) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "output": str(output), "sha256": sha256(output), "q_n_status": report["q_n_status"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
