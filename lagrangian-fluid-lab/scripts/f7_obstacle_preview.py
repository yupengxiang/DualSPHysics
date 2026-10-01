#!/usr/bin/env python3
"""Render actual saved F7 Obstacle Exchange states with native geometry, rotating blade, and fluid velocity."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import h5py
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def render_obstacle_preview(source_h5: Path, manifest_path: Path, output_png: Path) -> dict:
    source_h5 = Path(source_h5).resolve()
    output_png = Path(output_png).resolve()
    output_png.parent.mkdir(parents=True, exist_ok=True)

    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8")) if Path(manifest_path).is_file() else {}
    case_id = manifest.get("case_id", source_h5.parent.parent.name)

    with h5py.File(source_h5, "r") as h:
        times = np.asarray(h["time"][:], dtype=np.float64)
        target_times = [0.0, 2.0, 6.0, float(times[-1])]
        chosen_indices = [int(np.argmin(np.abs(times - t))) for t in target_times]

        initial_fluid = (h["valid"][0].astype(bool)) & (h["type"][0] == 3)
        initial_mass = float(np.sum(h["mass"][0][initial_fluid]))
        fluid_count = int(np.sum(initial_fluid))

        fig, axes = plt.subplots(2, 4, figsize=(18, 8), layout="constrained")

        for col, ti in enumerate(chosen_indices):
            t_val = times[ti]
            valid = np.asarray(h["valid"][ti], dtype=bool)
            pos = np.asarray(h["position"][ti], dtype=np.float64)
            types = np.asarray(h["type"][ti], dtype=np.int64)
            vel = np.asarray(h["velocity"][ti], dtype=np.float64)

            static_mask = valid & (types == 0)
            moving_mask = valid & (types == 1)
            fluid_mask = valid & (types == 3)

            static_pts = pos[static_mask]
            moving_pts = pos[moving_mask]
            fluid_pts = pos[fluid_mask]
            fluid_vel = vel[fluid_mask]
            fluid_speed = np.linalg.norm(fluid_vel, axis=-1)

            # Subsample boundary for clean rendering
            s_stride = max(1, len(static_pts) // 4000)
            static_sub = static_pts[::s_stride]

            # Subsample fluid if very dense
            f_stride = max(1, len(fluid_pts) // 10000)
            fluid_sub = fluid_pts[::f_stride]
            speed_sub = fluid_speed[::f_stride]

            # Row 0: Top-Down View (X-Y plane)
            ax_top = axes[0, col]
            if len(static_sub) > 0:
                ax_top.scatter(static_sub[:, 0], static_sub[:, 1], c="gray", s=0.8, alpha=0.3, label="Tank Walls")
            if len(moving_pts) > 0:
                ax_top.scatter(moving_pts[:, 0], moving_pts[:, 1], c="crimson", s=2.5, alpha=0.8, label="Obstacle Blade")
            if len(fluid_sub) > 0:
                sc_top = ax_top.scatter(fluid_sub[:, 0], fluid_sub[:, 1], c=speed_sub, cmap="viridis", vmin=0.0, vmax=1.2, s=1.2, alpha=0.6)
            ax_top.set_xlim(-0.68, 0.68)
            ax_top.set_ylim(-0.48, 0.48)
            ax_top.set_aspect("equal", adjustable="box")
            ax_top.set_title(f"t = {t_val:.2f} s (Top View X-Y)", fontsize=11, fontweight="bold")
            ax_top.set_xlabel("x [m]", fontsize=9)
            ax_top.set_ylabel("y [m]", fontsize=9)
            ax_top.grid(True, linestyle=":", alpha=0.5)

            # Row 1: Side View (X-Z plane)
            ax_side = axes[1, col]
            if len(static_sub) > 0:
                ax_side.scatter(static_sub[:, 0], static_sub[:, 2], c="gray", s=0.8, alpha=0.3)
            if len(moving_pts) > 0:
                ax_side.scatter(moving_pts[:, 0], moving_pts[:, 2], c="crimson", s=2.5, alpha=0.8)
            if len(fluid_sub) > 0:
                sc_side = ax_side.scatter(fluid_sub[:, 0], fluid_sub[:, 2], c=speed_sub, cmap="viridis", vmin=0.0, vmax=1.2, s=1.2, alpha=0.6)
            ax_side.set_xlim(-0.68, 0.68)
            ax_side.set_ylim(-0.05, 0.68)
            ax_side.set_aspect("equal", adjustable="box")
            ax_side.set_title(f"t = {t_val:.2f} s (Side View X-Z)", fontsize=11, fontweight="bold")
            ax_side.set_xlabel("x [m]", fontsize=9)
            ax_side.set_ylabel("z [m]", fontsize=9)
            ax_side.grid(True, linestyle=":", alpha=0.5)

        fig.colorbar(sc_top, ax=axes, orientation="horizontal", fraction=0.04, pad=0.08, label="Fluid Speed |u| [m/s]")
        fig.suptitle(f"DS-DATA-02 Reference Study: {case_id} (Obstacle Exchange, {fluid_count:,} fluid particles, {initial_mass:.2f} kg)", fontsize=14, fontweight="bold")

        fig.savefig(output_png, dpi=180)
        plt.close(fig)

    return {
        "status": "completed",
        "output_png": str(output_png),
        "case_id": case_id,
        "fluid_particles": fluid_count,
        "fluid_mass_kg": initial_mass,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="Path to converted trajectory.h5")
    parser.add_argument("--manifest", type=Path, required=True, help="Path to case manifest JSON")
    parser.add_argument("--output", type=Path, required=True, help="Path to output PNG preview")
    args = parser.parse_args()

    res = render_obstacle_preview(args.source, args.manifest, args.output)
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
