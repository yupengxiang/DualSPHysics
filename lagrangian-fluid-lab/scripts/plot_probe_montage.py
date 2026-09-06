#!/usr/bin/env python3
"""Render initial/final particle snapshots for representative mechanism probes."""

from __future__ import annotations

import json
from pathlib import Path

import h5py
import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
QUALITY = ROOT / "reports" / "runtime" / "quality-gates.json"
OUTPUT = ROOT / "reports" / "probe-montage.png"
SELECTED = [
    "C0_static_tank", "F1_center_obstacle", "F1_opposing_columns", "F2_two_source_layers",
    "O3_sloshing_motion", "F3_baffled_slosh", "F4_head_on_columns", "O4_impinging_jet",
    "F5_notched_weir", "O5_solitary_wave", "O5_wave_runup", "O5_wave_runup_refined",
    "F6_heavy_box_entry", "O6_floating_box", "O6_floating_sphere", "O6_falling_wedge_vres",
]


def main():
    quality = json.loads(QUALITY.read_text())
    by_id = {case["id"]: case for case in quality["cases"]}
    fig, axes = plt.subplots(4, 4, figsize=(16, 11), constrained_layout=True)
    fig.suptitle("DualSPHysics Lagrangian mechanism probes — initial → final", fontsize=16)
    for ax, case_id in zip(axes.flat, SELECTED):
        record = by_id[case_id]
        with h5py.File(ROOT / record["hdf5"], "r") as h5:
            valid = h5["valid"][:]
            pos = h5["position"][:]
            ptype = h5["type"][:]
            time = h5["time"][:]
            common = valid[0] & valid[-1]
            initial = valid[0]
            final = valid[-1]
            introduced = final & ~valid[0]
            displacement = np.full(valid.shape[1], np.nan)
            displacement[common] = np.linalg.norm(pos[-1, common] - pos[0, common], axis=1)
            ax.scatter(pos[0, initial, 0], pos[0, initial, 2], s=2, c="#c7c7c7",
                       alpha=0.32, linewidths=0, rasterized=True)
            moving_final = final & ~introduced
            values = displacement[moving_final]
            vmax = max(1e-6, float(np.nanpercentile(values, 95))) if len(values) else 1.0
            ax.scatter(pos[-1, moving_final, 0], pos[-1, moving_final, 2], s=3,
                       c=values, cmap="viridis", vmin=0, vmax=vmax, linewidths=0,
                       rasterized=True)
            if introduced.any():
                ax.scatter(pos[-1, introduced, 0], pos[-1, introduced, 2], s=3,
                           c="#ee7733", linewidths=0, rasterized=True)
            floating = final & (ptype[-1] == 2)
            if floating.any():
                ax.scatter(pos[-1, floating, 0], pos[-1, floating, 2], s=8,
                           facecolors="none", edgecolors="black", linewidths=0.35,
                           rasterized=True)
        status = "PASS" if record["status"] == "usable_probe" else "FAIL"
        color = "#17813b" if status == "PASS" else "#bd1f2d"
        ax.set_title(f"{case_id}\n{status}  t={time[-1]:.3g}s  n={final.sum():,}",
                     fontsize=8.5, color=color)
        ax.set_xlabel("x [m]", fontsize=7)
        ax.set_ylabel("z [m]", fontsize=7)
        ax.tick_params(labelsize=6)
        ax.set_aspect("equal", adjustable="datalim")
        ax.grid(alpha=0.15, linewidth=0.4)
    fig.text(0.5, 0.005,
             "gray: initial  |  viridis: final, colored by displacement (panel-wise 95% scale)  |  "
             "orange: IDs introduced after t=0  |  black outline: floating body",
             ha="center", fontsize=9)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUTPUT, dpi=180, bbox_inches="tight")
    print(OUTPUT)


if __name__ == "__main__":
    main()
