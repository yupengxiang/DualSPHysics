#!/usr/bin/env python3
"""Render publication preview for F5 Wave Runup and Weir Pair benchmarks."""
from __future__ import annotations

import argparse
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def render_f5_preview(runup_dir: Path, weir_dir: Path, output_png: Path) -> None:
    output_png = Path(output_png).resolve()
    output_png.parent.mkdir(parents=True, exist_ok=True)

    runup_dir = Path(runup_dir).resolve()
    weir_dir = Path(weir_dir).resolve()

    fig, axes = plt.subplots(3, 2, figsize=(15, 10), sharex="row", layout="constrained")

    # Bed profile definition
    bed_profile = np.array([
        [-1.1, 0.0],
        [3.55, 0.0],
        [5.15, 0.448],
        [6.55, 0.840],
        [7.15, 0.840],
        [9.45, 0.370],
        [10.5, 0.08],
        [10.85, 0.08]
    ])

    gauges = [
        ("WG1 (x=2.0m, deep)", "GaugesSWL_WG1.csv", 2.0),
        ("WG2 (x=3.55m, toe)", "GaugesSWL_WG2.csv", 3.55),
        ("WG3 (x=5.15m, slope)", "GaugesSWL_WG3.csv", 5.15),
        ("RunupToe (x=7.15m, crest)", "GaugesSWL_RunupToe.csv", 7.15),
    ]

    # Row 0: Tank profile and gauge locations
    for col, (title, is_weir) in enumerate([("F5 Runup Return (Continuous Sloping Beach)", False),
                                           ("F5 Weir Pair (Slotted Overtopping Weir)", True)]):
        ax = axes[0, col]
        ax.plot(bed_profile[:, 0], bed_profile[:, 1], color="#42484e", lw=2.5, label="Bed Elevation")
        ax.fill_between(bed_profile[:, 0], -0.1, bed_profile[:, 1], color="#d0d7de", alpha=0.5)
        ax.axhline(0.40, color="#2878b5", ls="--", lw=1.5, label="Initial SWL (z=0.40m)")

        if is_weir:
            # Weir at x ~ 5.8m
            ax.plot([5.8, 5.8], [0.55, 0.75], color="#d9534f", lw=4, label="Transverse Weir (h=0.20m)")

        for label, _, gx in gauges:
            ax.axvline(gx, color="#e58e26", ls=":", lw=1.2)
            ax.text(gx, 0.95, label.split()[0], rotation=90, verticalalignment="top", fontsize=8, color="#e58e26")

        ax.set_xlim(-1.2, 11.0)
        ax.set_ylim(-0.1, 1.2)
        ax.set_ylabel("Elevation z [m]", fontsize=10)
        ax.set_xlabel("Flume Axis x [m]", fontsize=10)
        ax.set_title(title, fontsize=11, fontweight="bold")
        ax.legend(loc="lower right", fontsize=8)
        ax.grid(True, alpha=0.3)

    # Row 1: WG1 and WG2 timeseries (incident and shoaling wave)
    for col, base_dir in enumerate([runup_dir, weir_dir]):
        ax = axes[1, col]
        for name, fname, _ in gauges[:2]:
            path = base_dir / fname
            if path.is_file():
                df = pd.read_csv(path, sep=";", skipinitialspace=True)
                df.columns = [c.strip() for c in df.columns]
                t = df["time [s]"]
                swl = df["swlz [m]"]
                ax.plot(t, (swl - 0.40) * 100, lw=1.8, label=f"{name.split()[0]} Wave Elevation (cm)")
        ax.set_ylabel("Surface Elevation η [cm]", fontsize=10)
        ax.set_xlabel("Time [s]", fontsize=10)
        ax.grid(True, alpha=0.3)
        ax.legend(loc="upper right", fontsize=8)
        ax.set_title("Incident and Shoaling Wave Train (WG1 & WG2)", fontsize=10)

    # Row 2: WG3 and RunupToe timeseries (runup, breaking, and overtopping)
    for col, base_dir in enumerate([runup_dir, weir_dir]):
        ax = axes[2, col]
        for name, fname, _ in gauges[2:]:
            path = base_dir / fname
            if path.is_file():
                df = pd.read_csv(path, sep=";", skipinitialspace=True)
                df.columns = [c.strip() for c in df.columns]
                t = df["time [s]"]
                swl = df["swlz [m]"]
                ax.plot(t, swl, lw=1.8, label=f"{name.split()[0]} Water Level z [m]")
        ax.set_ylabel("Water Level z [m]", fontsize=10)
        ax.set_xlabel("Time [s]", fontsize=10)
        ax.grid(True, alpha=0.3)
        ax.legend(loc="upper right", fontsize=8)
        ax.set_title("Runup and Overtopping Dynamics (WG3 & RunupToe)", fontsize=10)

    fig.suptitle("DS-DATA-02 Family F5: Wave Runup and Weir Pair Qualification Dynamics\n"
                 "3D Wave Flume | Bounded Initial Cohort (Zero Boundary Overwrites) | Exact Piston Kinematics",
                 fontsize=12, fontweight="bold")

    fig.savefig(output_png, dpi=180)
    plt.close(fig)
    print(f"Rendered F5 preview: {output_png}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Render F5 wave runup preview.")
    parser.add_argument("--runup", type=Path, required=True, help="Path to runup solver output dir")
    parser.add_argument("--weir", type=Path, required=True, help="Path to weir solver output dir")
    parser.add_argument("--output", type=Path, required=True, help="Path to output PNG")
    args = parser.parse_args()

    render_f5_preview(args.runup, args.weir, args.output)


if __name__ == "__main__":
    main()
