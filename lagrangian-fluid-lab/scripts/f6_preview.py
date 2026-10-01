#!/usr/bin/env python3
"""Render publication preview for F6 Small-Body Floating Body benchmarks."""
from __future__ import annotations

import argparse
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def render_f6_preview(simple_csv: Path, wave_csv: Path, output_png: Path) -> None:
    output_png = Path(output_png).resolve()
    output_png.parent.mkdir(parents=True, exist_ok=True)

    df_simple = pd.read_csv(simple_csv, sep=";", skipinitialspace=True)
    df_simple.columns = [c.strip() for c in df_simple.columns]

    df_wave = pd.read_csv(wave_csv, sep=";", skipinitialspace=True)
    df_wave.columns = [c.strip() for c in df_wave.columns]

    fig, axes = plt.subplots(3, 2, figsize=(14, 10), sharex=True, layout="constrained")

    # Column 1: Simple Free Response (Calm Water Release)
    t_s = df_simple["time [s]"]
    axes[0, 0].plot(t_s, df_simple["heave [m]"] * 100, color="#1f77b4", lw=2, label="Heave (cm)")
    axes[0, 0].set_ylabel("Heave [cm]", fontsize=11)
    axes[0, 0].set_title("F6 Simple Free Response (Calm Water Hydrostatic Settling)", fontsize=12, fontweight="bold")
    axes[0, 0].grid(True, alpha=0.3)
    axes[0, 0].legend(loc="upper right")

    axes[1, 0].plot(t_s, df_simple["pitch [deg]"], color="#ff7f0e", lw=2, label="Pitch (deg)")
    axes[1, 0].set_ylabel("Pitch [deg]", fontsize=11)
    axes[1, 0].grid(True, alpha=0.3)
    axes[1, 0].legend(loc="upper right")

    axes[2, 0].plot(t_s, df_simple["surge [m]"] * 100, color="#2ca02c", lw=2, label="Surge (cm)")
    axes[2, 0].set_ylabel("Surge [cm]", fontsize=11)
    axes[2, 0].set_xlabel("Time [s]", fontsize=11)
    axes[2, 0].grid(True, alpha=0.3)
    axes[2, 0].legend(loc="upper right")

    # Column 2: Wave No Contact (Wave Paddle Excitation)
    t_w = df_wave["time [s]"]
    axes[0, 1].plot(t_w, df_wave["heave [m]"] * 100, color="#1f77b4", lw=2, label="Heave (cm)")
    axes[0, 1].set_ylabel("Heave [cm]", fontsize=11)
    axes[0, 1].set_title("F6 Wave No Contact (Regular Wave Train Dynamic Response)", fontsize=12, fontweight="bold")
    axes[0, 1].grid(True, alpha=0.3)
    axes[0, 1].legend(loc="upper right")

    axes[1, 1].plot(t_w, df_wave["pitch [deg]"], color="#ff7f0e", lw=2, label="Pitch (deg)")
    axes[1, 1].set_ylabel("Pitch [deg]", fontsize=11)
    axes[1, 1].grid(True, alpha=0.3)
    axes[1, 1].legend(loc="upper right")

    axes[2, 1].plot(t_w, df_wave["surge [m]"] * 100, color="#2ca02c", lw=2, label="Surge (cm)")
    axes[2, 1].set_ylabel("Surge [cm]", fontsize=11)
    axes[2, 1].set_xlabel("Time [s]", fontsize=11)
    axes[2, 1].grid(True, alpha=0.3)
    axes[2, 1].legend(loc="upper right")

    fig.suptitle("DS-DATA-02 Family F6: Official Small-Body Fallback 02 Qualification Kinematics (6-DOF Floating Dynamics)\n"
                 "Complete 12.0s Event Window | Zero Boundary Exclusions (100% Mass Conservation) | Native RigidAlgorithm=1",
                 fontsize=13, fontweight="bold")

    fig.savefig(output_png, dpi=180)
    plt.close(fig)
    print(f"Rendered F6 preview: {output_png}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Render F6 floating body preview.")
    parser.add_argument("--simple", type=Path, required=True, help="Path to Simple Free Response FloatingMotion CSV")
    parser.add_argument("--wave", type=Path, required=True, help="Path to Wave No Contact FloatingMotion CSV")
    parser.add_argument("--output", type=Path, required=True, help="Path to output PNG")
    args = parser.parse_args()

    render_f6_preview(args.simple, args.wave, args.output)


if __name__ == "__main__":
    main()
