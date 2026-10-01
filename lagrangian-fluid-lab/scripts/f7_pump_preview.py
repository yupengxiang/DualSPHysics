#!/usr/bin/env python3
"""Render actual saved F7 Pump states with native geometry, impeller, and fluid velocity."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import h5py
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np


def render_pump_preview(source_h5: Path, manifest_path: Path, output_png: Path) -> dict:
    source_h5 = Path(source_h5).resolve()
    output_png = Path(output_png).resolve()
    output_png.parent.mkdir(parents=True, exist_ok=True)

    manifest = json.loads(Path(manifest_path).read_text(encoding='utf-8'))
    case_id = manifest.get('case_id', source_h5.stem)

    with h5py.File(source_h5, 'r') as h:
        times = h['time'][:]
        total_frames = len(times)
        target_times = [0.0, 2.0, 6.0, float(times[-1])]
        chosen_indices = [int(np.argmin(np.abs(times - t))) for t in target_times]

        initial_fluid = (h['valid'][0].astype(bool)) & (h['type'][0] == 3)
        initial_mass = float(np.sum(h['mass'][0][initial_fluid]))

        fig, axes = plt.subplots(2, 4, figsize=(16, 8), layout='constrained')

        for col, ti in enumerate(chosen_indices):
            t_val = times[ti]
            valid = h['valid'][ti].astype(bool)
            pos = h['position'][ti]
            types = h['type'][ti]
            vel = h['velocity'][ti]

            static_mask = valid & (types == 0)
            moving_mask = valid & (types == 1)
            fluid_mask = valid & (types == 3)

            static_pts = pos[static_mask]
            moving_pts = pos[moving_mask]
            fluid_pts = pos[fluid_mask]
            fluid_vel = vel[fluid_mask]
            fluid_speed = np.linalg.norm(fluid_vel, axis=-1)

            # Subsample boundary for crisp rendering
            s_stride = max(1, len(static_pts) // 4000)
            static_sub = static_pts[::s_stride]

            # Subsample fluid if very dense
            f_stride = max(1, len(fluid_pts) // 8000)
            fluid_sub = fluid_pts[::f_stride]
            speed_sub = fluid_speed[::f_stride]

            # Row 0: X-Z cross-section (impeller rotation plane)
            ax_xz = axes[0, col]
            ax_xz.scatter(static_sub[:, 0], static_sub[:, 2], s=2, c='#95a5a6', alpha=0.3, rasterized=True, label='Casing' if col == 0 else None)
            ax_xz.scatter(moving_pts[:, 0], moving_pts[:, 2], s=6, c='#e74c3c', alpha=0.9, rasterized=True, label='Impeller' if col == 0 else None)
            sc0 = ax_xz.scatter(fluid_sub[:, 0], fluid_sub[:, 2], s=4, c=speed_sub, cmap='viridis', vmin=0.0, vmax=2.5, alpha=0.75, rasterized=True, label='Fluid' if col == 0 else None)
            ax_xz.set_xlim(-0.35, 0.25)
            ax_xz.set_ylim(-1.05, -0.05)
            ax_xz.set_aspect('equal', adjustable='box')
            ax_xz.set_xlabel('x [m]')
            ax_xz.set_ylabel('z [m]')
            ax_xz.set_title(f't = {t_val:.2f} s (X-Z cross section)', fontsize=10)
            if col == 0:
                ax_xz.legend(loc='upper right', fontsize=8)

            # Row 1: Y-Z side view (axial & discharge channel)
            ax_yz = axes[1, col]
            ax_yz.scatter(static_sub[:, 1], static_sub[:, 2], s=2, c='#95a5a6', alpha=0.3, rasterized=True)
            ax_yz.scatter(moving_pts[:, 1], moving_pts[:, 2], s=6, c='#e74c3c', alpha=0.9, rasterized=True)
            sc1 = ax_yz.scatter(fluid_sub[:, 1], fluid_sub[:, 2], s=4, c=speed_sub, cmap='viridis', vmin=0.0, vmax=2.5, alpha=0.75, rasterized=True)
            ax_yz.set_xlim(-0.55, 0.30)
            ax_yz.set_ylim(-1.05, -0.05)
            ax_yz.set_aspect('equal', adjustable='box')
            ax_yz.set_xlabel('y [m]')
            ax_yz.set_ylabel('z [m]')
            ax_yz.set_title(f't = {t_val:.2f} s (Y-Z side view)', fontsize=10)

        cbar = fig.colorbar(sc1, ax=axes, orientation='horizontal', fraction=0.03, pad=0.04, aspect=40)
        cbar.set_label('Fluid velocity magnitude |v| [m/s]', fontsize=10)

        fig.suptitle(f'F7 Pump Recirculation ({case_id}): Actual Saved Particle Dynamics\n'
                     f'Red: Rotating Impeller (Axis || Y) | Color: Fluid Speed | Initial Fluid Mass: {initial_mass:.3f} kg',
                     fontsize=12)

        fig.savefig(output_png, dpi=180)
        plt.close(fig)

    return {
        'case_id': case_id,
        'source_h5': str(source_h5),
        'preview_png': str(output_png),
        'chosen_times_s': [float(times[i]) for i in chosen_indices],
        'initial_fluid_mass_kg': initial_mass,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True, help='Path to trajectory.h5')
    parser.add_argument('--manifest', type=Path, required=True, help='Path to case manifest JSON')
    parser.add_argument('--output', type=Path, required=True, help='Output preview PNG path')
    args = parser.parse_args()

    result = render_pump_preview(args.source, args.manifest, args.output)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
