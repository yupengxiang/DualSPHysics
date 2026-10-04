#!/usr/bin/env python3
"""Reusable binding-driven native paired transport comparison worker for F3 two-axis sloshing.

Evaluates same-UID Lagrangian transport sensitivity:
1. Baseline vs Halfstep (time discretization sensitivity).
2. Baseline vs Dense (save frequency sensitivity).

Strict Scientific Gates & Semantics (as in Root nominal 050 and 055):
- No CDF qualification threshold; no retrospective pass gate.
- No new UIDpath timing gate absent preregistration.
- Retains all same-UID fate switches and switch masses.
- Retains sensitivity-only first passages (half-only or dense-only) and nominal-only first passages.
- Retains disjoint vs overlapping literal native brackets without censoring manipulation.
- Binary native weights immutable (MassFluid from native GenCase/BI4, no rescaling).
- Canonical physical condition hash: 49e319c0a874733707a028e916362e74e2301d6681e34bc6b717581dbd7edaeb.
- Historical negative evidence preserved (original dp0.0075 1388 switches, dp0.006 2336 switches).
- Pure descriptive sensitivity: q_n='not_granted', production_approval='none'.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Dict, List

import h5py
import numpy as np

CANONICAL_PHYSICAL_CONDITION_SHA256 = "49e319c0a874733707a028e916362e74e2301d6681e34bc6b717581dbd7edaeb"
DECLARED_TOP_LEVEL_ERRATUM_MARKER = "49d16330fd5267668670f166a20191bfb00c5223ad5528439630c7e62dd4c6a0"
FORBIDDEN_SINGLE_AXIS_HASHES = {
    "59abc8c59ecbb994aef358a683672feac00ff8d1024d55f0219c8fe257f6ff90",
    "86562c5afee8228131d58c1b53f360eb6c6a700381c01bf807a0f268bbc675c0",
}
FULL_WINDOW_TMAX_S = 8.35


def digest(path: Path | str) -> str:
    """Compute sha256 checksum of a file."""
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        while chunk := f.read(1048576):
            h.update(chunk)
    return h.hexdigest()


def compute_stats(delta: np.ndarray, weights: np.ndarray) -> Dict[str, Any]:
    """Compute mass-weighted gap statistics for paired delta arrays."""
    if len(delta) == 0 or weights.sum() <= 0:
        return {"identities": 0}
    abs_delta = np.abs(delta)
    w_sum = float(weights.sum())
    return {
        "identities": int(len(delta)),
        "native_mass_kg": w_sum,
        "mass_weighted_mean_abs_gap_s": float(np.dot(abs_delta, weights) / w_sum),
        "max_abs_gap_s": float(abs_delta.max()),
        "p95_abs_gap_s": float(np.percentile(abs_delta, 95)),
    }


def run_paired_transport_worker(
    binding_path: Path, output_path: Path, dry_run_check: bool = False
) -> Dict[str, Any]:
    """Execute binding-driven paired same-UID transport comparison."""
    binding = json.loads(binding_path.read_text())
    config_path = Path(binding["event_config"])
    config = json.loads(config_path.read_text())

    # Preflight validation
    cond_hash = binding.get("physical_condition_sha256")
    if cond_hash != CANONICAL_PHYSICAL_CONDITION_SHA256:
        raise ValueError(
            f"Invalid physical condition hash: expected canonical {CANONICAL_PHYSICAL_CONDITION_SHA256}, got {cond_hash}"
        )
    if cond_hash in FORBIDDEN_SINGLE_AXIS_HASHES:
        raise ValueError("Single-axis controls hash MUST NOT transfer to two-axis mechanism")

    declared = binding.get("declared_top_level_digest")
    if declared and declared != DECLARED_TOP_LEVEL_ERRATUM_MARKER:
        raise ValueError(
            f"Erratum declared digest mismatch: expected {DECLARED_TOP_LEVEL_ERRATUM_MARKER}, got {declared}"
        )

    if dry_run_check:
        return {
            "status": "preflight_passed",
            "binding": binding_path.name,
            "roles": list(binding["sources"].keys()),
            "physical_condition_sha256": cond_hash,
            "declared_top_level_digest": declared,
            "expected_frames": binding.get("expected_frames", {}),
            "claim": binding.get("claim"),
            "q_n": "not_granted",
            "production_approval": "none",
        }

    if output_path.exists():
        raise FileExistsError(f"Preserve existing output report: {output_path}")

    # Load and verify sources
    data: Dict[str, Dict[str, np.ndarray]] = {}
    sources = binding["sources"]
    roles = list(sources.keys())
    if "baseline" not in roles or len(roles) != 2:
        raise ValueError("Paired comparison requires exactly 'baseline' and one sensitivity role")
    comparison_role = [r for r in roles if r != "baseline"][0]

    for role, s in sources.items():
        receipt_path = Path(s["receipt"])
        report_path = Path(s["labels_report"])
        labels_path = Path(s["labels"])

        if not receipt_path.is_file():
            raise FileNotFoundError(f"Missing receipt for role {role}: {receipt_path}")
        if not report_path.is_file():
            raise FileNotFoundError(f"Missing labels report for role {role}: {report_path}")
        if not labels_path.is_file():
            raise FileNotFoundError(f"Missing labels file for role {role}: {labels_path}")

        receipt = json.loads(receipt_path.read_text())
        report = json.loads(report_path.read_text())

        if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
            raise ValueError(f"Role {role} receipt indicates non-completed status")
        if not report.get("closure", {}).get("passed", False):
            raise ValueError(f"Role {role} labels report failed closure check")
        if digest(labels_path) != s["sha256"]:
            raise ValueError(f"Role {role} labels file SHA256 mismatch")

        with h5py.File(labels_path, "r") as h:
            h_config = json.loads(h.attrs["config_json"])
            if h_config != config:
                raise ValueError(f"Role {role} event config differs from bound config")
            if not h.attrs.get("complete", False):
                raise ValueError(f"Role {role} labels file incomplete attribute")
            if "expected_source_hdf5_sha256" in s:
                if h.attrs.get("source_hdf5_sha256") != s["expected_source_hdf5_sha256"]:
                    raise ValueError(f"Role {role} source HDF5 sha256 differs from expected")

            keys = [
                "particle_id",
                "particle_zone",
                "initial_fluid_mass_kg",
                "source_label",
                "final_category",
                "first_passage_censor",
                "first_passage_interval",
                "first_passage_chord_time",
                "residence_time_s",
                "unresolved_interval_time_s",
                "time",
            ]
            data[role] = {k: h[k][:] for k in keys}

        times = data[role]["time"]
        exp_frames = binding.get("expected_frames", {}).get(role, len(times))
        if (
            len(times) != exp_frames
            or times[0] != 0.0
            or times[-1] < FULL_WINDOW_TMAX_S
            or not np.isfinite(times).all()
            or not np.all(np.diff(times) > 0)
        ):
            raise ValueError(f"Role {role} time support invalid or incomplete")

    x = data["baseline"]
    y = data[comparison_role]

    # Verify identical native UID partition and weights
    for k in ["particle_id", "particle_zone", "initial_fluid_mass_kg", "source_label"]:
        if not np.array_equal(x[k], y[k]):
            raise ValueError(f"Native UID/cohort/weight differs for key: {k}")

    ids = np.column_stack((x["particle_zone"], x["particle_id"]))
    mass = x["initial_fluid_mass_kg"]
    fluid = mass > 0
    n_total = len(ids)
    n_fluid = int(fluid.sum())

    if len(np.unique(ids, axis=0)) != n_total:
        raise ValueError("Particle IDs contain duplicate records")

    # Fate switches
    switches = fluid & (x["final_category"] != y["final_category"])
    actual_fate_switches = int(switches.sum())
    native_fate_switch_mass_kg = float(mass[switches].sum())

    # Event first passages
    events_result: List[Dict[str, Any]] = []
    for i, event in enumerate(config.get("events", [])):
        nx = fluid & (x["first_passage_censor"][:, i] == 0)
        ny = fluid & (y["first_passage_censor"][:, i] == 0)
        joint = nx & ny
        nominal_only = nx & ~ny
        sens_only = ny & ~nx

        ix = x["first_passage_interval"][joint, i]
        iy = y["first_passage_interval"][joint, i]
        overlap = np.maximum(ix[:, 0], iy[:, 0]) <= np.minimum(ix[:, 1], iy[:, 1])
        chord_delta = y["first_passage_chord_time"][joint, i] - x["first_passage_chord_time"][joint, i]

        sens_only_label = f"{comparison_role}_only_first_passages"
        events_result.append({
            "event": event["id"],
            "joint_first_passages": int(joint.sum()),
            "nominal_only_first_passages": int(nominal_only.sum()),
            sens_only_label: int(sens_only.sum()),
            "literal_native_bracket_overlap_count": int(overlap.sum()),
            "literal_native_bracket_disjoint_count": int((~overlap).sum()),
            "chord_gap": compute_stats(chord_delta, mass[joint]),
            "classification": "descriptive sameUID sensitivity, no new perUID timing acceptance or causality",
        })

    # Residence time comparison
    residence_result: List[Dict[str, Any]] = []
    for i, reg in enumerate(config.get("destination_regions", [])):
        res_delta = y["residence_time_s"][fluid, i] - x["residence_time_s"][fluid, i]
        residence_result.append({
            "destination": reg["id"],
            **compute_stats(res_delta, mass[fluid]),
        })

    # Unresolved interval time gap
    unresolved_delta = y["unresolved_interval_time_s"][fluid] - x["unresolved_interval_time_s"][fluid]
    unresolved_gap = compute_stats(unresolved_delta, mass[fluid])

    result = {
        "schema": "ds02.f3.actual-twoaxis-paired-transport-report.v1",
        "binding": binding,
        "mechanism_id": "F3_TWOAXIS_TRANSVERSE_LINACC_V1",
        "comparison_role": comparison_role,
        "total_identities": n_total,
        "fluid_identities": n_fluid,
        "native_initial_mass_kg": float(mass.sum()),
        "actual_fate_switches": actual_fate_switches,
        "native_fate_switch_mass_kg": native_fate_switch_mass_kg,
        "event_first_passages": events_result,
        "residence": residence_result,
        "unresolved_time_gap": unresolved_gap,
        "q_n": "not_granted",
        "production_approval": "none",
        "limitations": [
            "No CDF/macro proxy grants path equivalence.",
            "Canonical numerical loss/unknown/invalid codes remain actual final categories.",
            "Original dp0.0075 paired 1388 fate switches remains negative; candidate dp0.006 2336 switches preserved; no alias transfer.",
            "Binary native weights immutable; no rescaling or artificial normalization.",
            "Descriptive same-UID sensitivity observation only; no retrospective pass gate."
        ],
    }

    with output_path.open("x") as f:
        json.dump(result, f, indent=2)
        f.write("\n")

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding", type=Path, required=True, help="Path to transport comparison binding JSON")
    parser.add_argument("--output", type=Path, required=True, help="Path to output report JSON")
    parser.add_argument(
        "--dry-run-check", action="store_true", help="Perform preflight validation without executing comparison"
    )
    args = parser.parse_args()

    res = run_paired_transport_worker(
        binding_path=args.binding, output_path=args.output, dry_run_check=args.dry_run_check
    )
    print(
        json.dumps(
            {
                "actual_fate_switches": res.get("actual_fate_switches"),
                "native_fate_switch_mass_kg": res.get("native_fate_switch_mass_kg"),
                "q_n": "not_granted",
                "production_approval": "none",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
