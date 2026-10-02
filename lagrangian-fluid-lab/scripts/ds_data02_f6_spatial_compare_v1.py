#!/usr/bin/env python3
"""Compare F6 rigid-body spatial trajectories over the complete [0,12] s window.

The comparison reads only rigid state arrays from already-produced H5 files. It
never changes solver data and does not turn a metric result into Q-N or
production qualification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import h5py
import numpy as np

WINDOW = (0.0, 12.0)
BUDGET = 0.05


def sha256(path: Path) -> str:
    d = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            d.update(block)
    return d.hexdigest()


def load(path: Path) -> dict[str, Any]:
    with h5py.File(path, "r") as h:
        rb = h["rigid_body"]
        t = np.asarray(h["time"][:], dtype=np.float64)
        return {
            "path": str(path.resolve()),
            "sha256": sha256(path),
            "case_id": str(h.attrs.get("case_id", "")),
            "frames": int(len(t)),
            "time_first_s": float(t[0]),
            "time_last_s": float(t[-1]),
            "time": t,
            "position": np.asarray(rb["position"][:], dtype=np.float64),
            "orientation_euler_rad": np.asarray(rb["orientation_euler_rad"][:], dtype=np.float64),
            "heave": np.asarray(rb["surge_sway_heave_m"][:, 2], dtype=np.float64),
            "massbody_kg": float(rb.attrs.get("mass_kg", h.attrs.get("floating_massbody_kg", np.nan))),
            "inertia": json.loads(str(rb.attrs.get("inertia_tensor_kg_m2", "[]"))),
        }


def interp(source: dict[str, Any], target_t: np.ndarray, key: str) -> np.ndarray:
    x = source["time"]
    y = source[key]
    if y.ndim == 1:
        return np.interp(target_t, x, y)
    return np.column_stack([np.interp(target_t, x, y[:, j]) for j in range(y.shape[1])])


def vector_metrics(reference: np.ndarray, candidate: np.ndarray) -> dict[str, Any]:
    delta = candidate - reference
    scale = np.maximum(np.max(np.abs(reference), axis=0), 1e-12)
    rmse = np.sqrt(np.mean(delta * delta, axis=0))
    return {
        "max_abs": np.max(np.abs(delta), axis=0).tolist(),
        "rmse": rmse.tolist(),
        "relative_rmse_to_reference_peak": (rmse / scale).tolist(),
        "max_relative_to_reference_peak": (np.max(np.abs(delta), axis=0) / scale).tolist(),
    }


def scalar_metrics(reference: np.ndarray, candidate: np.ndarray) -> dict[str, Any]:
    delta = candidate - reference
    scale = max(float(np.max(np.abs(reference))), 1e-12)
    return {
        "reference_peak_abs": float(np.max(np.abs(reference))),
        "candidate_peak_abs": float(np.max(np.abs(candidate))),
        "reference_rms": float(np.sqrt(np.mean(reference * reference))),
        "candidate_rms": float(np.sqrt(np.mean(candidate * candidate))),
        "max_abs": float(np.max(np.abs(delta))),
        "rmse": float(np.sqrt(np.mean(delta * delta))),
        "relative_rmse_to_reference_peak": float(np.sqrt(np.mean(delta * delta)) / scale),
        "max_relative_to_reference_peak": float(np.max(np.abs(delta)) / scale),
    }


def compare(reference: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    target_t = reference["time"]
    candidate_pos = interp(candidate, target_t, "position")
    candidate_ori = interp(candidate, target_t, "orientation_euler_rad")
    candidate_heave = interp(candidate, target_t, "heave")
    pos = vector_metrics(reference["position"], candidate_pos)
    ori = vector_metrics(reference["orientation_euler_rad"], candidate_ori)
    heave = scalar_metrics(reference["heave"], candidate_heave)
    max_macro = max(
        max(ori["relative_rmse_to_reference_peak"]),
        heave["relative_rmse_to_reference_peak"],
    )
    strict_window = (
        reference["frames"] == 241
        and candidate["frames"] == 241
        and reference["time_first_s"] <= WINDOW[0] + 1e-9
        and candidate["time_first_s"] <= WINDOW[0] + 1e-9
        and reference["time_last_s"] >= WINDOW[1] - 1e-6
        and candidate["time_last_s"] >= WINDOW[1] - 1e-6
    )
    return {
        "candidate": {k: candidate[k] for k in ("path", "sha256", "case_id", "frames", "time_first_s", "time_last_s", "massbody_kg", "inertia")},
        "strict_window_0_12_s": strict_window,
        "position_m": pos,
        "orientation_euler_rad": ori,
        "heave_m": heave,
        "max_macro_relative_rmse": float(max_macro),
        "macro_budget_5pct_pass": bool(strict_window and max_macro <= BUDGET),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--simple-dp025", type=Path, required=True)
    ap.add_argument("--simple-medium", type=Path, required=True)
    ap.add_argument("--simple-fine", type=Path, required=True)
    ap.add_argument("--wave-dp025", type=Path, required=True)
    ap.add_argument("--wave-medium", type=Path, required=True)
    ap.add_argument("--wave-fine", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    paths = {
        "simple_dp025": args.simple_dp025,
        "simple_medium": args.simple_medium,
        "simple_fine": args.simple_fine,
        "wave_dp025": args.wave_dp025,
        "wave_medium": args.wave_medium,
        "wave_fine": args.wave_fine,
    }
    loaded = {name: load(path.resolve()) for name, path in paths.items()}
    comparisons = {}
    for mechanism in ("simple", "wave"):
        ref = loaded[f"{mechanism}_dp025"]
        comparisons[f"{mechanism}_medium_vs_dp025"] = compare(ref, loaded[f"{mechanism}_medium"])
        comparisons[f"{mechanism}_fine_vs_dp025"] = compare(ref, loaded[f"{mechanism}_fine"])
        comparisons[f"{mechanism}_medium_vs_fine"] = compare(loaded[f"{mechanism}_fine"], loaded[f"{mechanism}_medium"])
    out = {
        "schema": "ds-data-02.f6.dp025.strict-spatial-comparison.v1",
        "family_id": "F6",
        "resolution_reference": "dp025",
        "window_s": list(WINDOW),
        "frame_contract": {"frames": 241, "save_interval_s": 0.05},
        "macro_budget_relative_rmse": BUDGET,
        "datasets": {name: {k: value[k] for k in ("path", "sha256", "case_id", "frames", "time_first_s", "time_last_s", "massbody_kg", "inertia")} for name, value in loaded.items()},
        "comparisons": comparisons,
        "interpretation": "Full-window rigid trajectory evidence only; no Q-N or production claim. Exclusion counts remain in native H5 valid masks and solver RunPARTs evidence.",
        "q_n_status": "pending independent scientific review and integrator/save study",
        "production_claim": "none",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(args.output.resolve()), "comparisons": {k: v["max_macro_relative_rmse"] for k, v in comparisons.items()}}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
