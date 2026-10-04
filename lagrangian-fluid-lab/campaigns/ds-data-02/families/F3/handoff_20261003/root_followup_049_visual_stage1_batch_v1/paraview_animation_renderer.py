"""ParaView Full-Animation Renderer for Stage 1 Visual Inspection (Followup 049).

Campaign: DS-DATA-02
Family: F3 (Two-Axis Tank Sloshing)
Authority: Root Followup 049 under F3 isolated worktree ds-data-02-f6
Schema: ds02.stage1.paraview-full-animation-integrity.v1

Features & Constraints:
- pvpython worker reading existing XDMF temporal sidecars (.xmf).
- Strictly NO h5py imported in pvpython process (uses native XDMFReader).
- Exact XDMFReader type assertion (reader.GetXMLName() == 'XdmfReader').
- Dual-camera true 3D layout: isometric view + orthogonal transverse side view.
- Explicit particle class thresholds:
  * valid: valid == 1
  * fluid: valid == 1 and type == 3
  * boundary: valid == 1 and type in [0, 2] (fixed box walls opacity ~0.15)
- Full 836-frame sequence rendered without sampling skips (all saved frames).
- Diagnostic integrity checks on EVERY frame:
  * Finite coordinates for all active points
  * Strict identity preservation (ids == first_ids, zones == first_zones)
  * Finite physical fields (mass, velocity, density, pressure)
  * Fluid bounding box envelope (min_xyz, max_xyz)
- Outputs:
  * Individual frame PNG sequence: frame_0000.png .. frame_0835.png
  * Indexed contact sheets covering all frames: all_frames_000.png ..
  * Full GIF animation: full_saved_animation.gif (40ms per saved frame)
  * ParaView state file: case.pvsm
  * Integrity report: paraview-full-animation-report.json
- Boundary note: Tank walls are fixedType0 in accelerating coordinate frame;
  no floating/moving rigid body claim is made.
- Visual status: pending root inspection; numerical precision is NOT accepted.
"""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys

import numpy as np
from PIL import Image, ImageDraw
from paraview import servermanager
from paraview.simple import (
    XDMFReader,
    Threshold,
    CreateView,
    CreateLayout,
    AssignViewToLayout,
    Show,
    ColorBy,
    Render,
    SaveScreenshot,
    SaveState,
    GetParaViewVersion,
)
from paraview.vtk.util.numpy_support import vtk_to_numpy


def sha256_file(path: Path) -> str:
    """Compute SHA256 of file in 1 MiB chunks."""
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1048576), b""):
            h.update(block)
    return h.hexdigest()


def iterate_leaf_blocks(data):
    """Iterate over leaf datasets in composite VTK dataset."""
    if data.IsA("vtkCompositeDataSet"):
        iterator = data.NewIterator()
        iterator.SkipEmptyNodesOn()
        iterator.InitTraversal()
        while not iterator.IsDoneWithTraversal():
            yield iterator.GetCurrentDataObject()
            iterator.GoToNextItem()
    else:
        yield data


def render_full_animation(
    manifest_path: Path,
    output_dir: Path,
    boundary_opacity: float = 0.15,
    contact_sheet_size: int = 24,
    frame_rate_duration_ms: int = 40,
) -> dict:
    """Execute complete full-animation rendering from XDMF manifest."""
    assert manifest_path.exists(), f"Manifest does not exist: {manifest_path}"
    manifest = json.loads(manifest_path.read_text())

    source_xdmf = Path(manifest["xdmf"])
    assert source_xdmf.exists(), f"XDMF file does not exist: {source_xdmf}"
    assert sha256_file(source_xdmf) == manifest["xdmf_sha256"], "XDMF digest mismatch vs manifest"

    output_dir.mkdir(parents=True, exist_ok=True)
    frames_dir = output_dir / "frames"
    assert not frames_dir.exists(), f"Frames directory already exists: {frames_dir}"
    frames_dir.mkdir()

    reader = XDMFReader(FileNames=[str(source_xdmf)])
    reader.UpdatePipelineInformation()
    assert reader.GetXMLName() == "XdmfReader", f"Expected XdmfReader, got {reader.GetXMLName()}"

    expected_times = np.asarray(manifest["actual_time_s"], dtype=np.float64)
    actual_times = np.asarray(list(reader.TimestepValues), dtype=np.float64)
    np.testing.assert_array_equal(actual_times, expected_times)
    num_frames = len(actual_times)

    reader.PointArrayStatus = list(reader.PointArrayStatus.Available)
    available_arrays = set(reader.PointArrayStatus.Available)
    expected_non_spatial_fields = set(manifest.get("fields", {}).keys()) - {"position", "time"}
    if expected_non_spatial_fields:
        assert expected_non_spatial_fields <= available_arrays, (
            f"Missing required fields: {expected_non_spatial_fields - available_arrays}"
        )

    # Filter 1: Valid particles (valid == 1)
    active = Threshold(Input=reader)
    active.Scalars = ["POINTS", "valid"]
    active.LowerThreshold = 1
    active.UpperThreshold = 1

    # Filter 2: Fluid particles (type == 3)
    fluid = Threshold(Input=active)
    fluid.Scalars = ["POINTS", "type"]
    fluid.LowerThreshold = 3
    fluid.UpperThreshold = 3

    # Filter 3: Boundary particles (type in [0, 2]: fixed box walls)
    boundary = Threshold(Input=active)
    boundary.Scalars = ["POINTS", "type"]
    boundary.LowerThreshold = 0
    boundary.UpperThreshold = 2

    # Layout: Dual-view (Isometric and Transverse Side)
    layout = CreateLayout(name="Stage 1 Visual Inspection: Isometric and Transverse Side Views")
    views = [CreateView("RenderView"), CreateView("RenderView")]
    layout.SplitHorizontal(0, 0.5)

    for index, view in enumerate(views):
        AssignViewToLayout(view=view, layout=layout, hint=1 + index)
        view.ViewSize = [640, 480]
        view.Background = [0.96, 0.97, 0.99]
        view.OrientationAxesVisibility = 1
        view.UseColorPaletteForBackground = 0

        # Boundary representation (opacity ~0.15)
        body_display = Show(boundary, view)
        body_display.Representation = "Points"
        body_display.PointSize = 2
        body_display.Opacity = boundary_opacity
        ColorBy(body_display, None)
        body_display.DiffuseColor = [0.20, 0.25, 0.30]

        # Fluid representation
        fluid_display = Show(fluid, view)
        fluid_display.Representation = "Points"
        fluid_display.PointSize = 2
        ColorBy(fluid_display, None)
        fluid_display.DiffuseColor = [0.0, 0.38, 0.85]

        view.CameraFocalPoint = [0.0, 0.0, 0.22]
        view.CameraParallelProjection = 1
        view.CameraParallelScale = 0.43
        view.CameraViewUp = [0.0, 0.0, 1.0]

        if index == 0:
            # View 0: Isometric perspective
            view.CameraPosition = [1.10, -1.60, 0.95]
        else:
            # View 1: Orthogonal transverse side view (looking down Y-axis)
            view.CameraPosition = [0.0, -2.00, 0.22]

    frame_diagnostics = []
    sheet_frames = []
    gif_frames = []
    sheet_index = 0
    first_ids = None
    first_zones = None

    for frame_idx, time_val in enumerate(actual_times):
        reader.UpdatePipeline(time=float(time_val))
        blocks = list(iterate_leaf_blocks(servermanager.Fetch(reader)))
        assert len(blocks) == 1, f"Expected 1 leaf block, got {len(blocks)}"
        data = blocks[0]

        total_pts = data.GetNumberOfPoints()
        assert total_pts == manifest["particles"], (
            f"Point count mismatch at frame {frame_idx}: got {total_pts}, expected {manifest['particles']}"
        )

        points = vtk_to_numpy(data.GetPoints().GetData())
        pd = data.GetPointData()

        valid_arr = vtk_to_numpy(pd.GetArray("valid")).astype(bool)
        types_arr = vtk_to_numpy(pd.GetArray("type"))
        ids_arr = vtk_to_numpy(pd.GetArray("particle_id"))
        zones_arr = vtk_to_numpy(pd.GetArray("particle_zone"))

        # Verify finite coordinates for all active particles
        assert np.isfinite(points[valid_arr]).all(), f"Non-finite point coordinates in frame {frame_idx}"

        # Strict identity preservation
        if frame_idx == 0:
            first_ids = ids_arr.copy()
            first_zones = zones_arr.copy()
        np.testing.assert_array_equal(ids_arr, first_ids, err_msg=f"Particle IDs mutated at frame {frame_idx}")
        np.testing.assert_array_equal(zones_arr, first_zones, err_msg=f"Particle zones mutated at frame {frame_idx}")

        # Check finite physics fields on valid particles
        for field_name in ("mass", "velocity", "density", "pressure"):
            arr = pd.GetArray(field_name)
            assert arr is not None, f"Field {field_name} missing at frame {frame_idx}"
            vals = vtk_to_numpy(arr)
            assert np.isfinite(vals[valid_arr]).all(), f"Non-finite values in {field_name} at frame {frame_idx}"

        fluid_points = points[valid_arr & (types_arr == 3)]
        assert len(fluid_points) > 0, f"No active fluid points at frame {frame_idx}"

        frame_diag = {
            "frame": frame_idx,
            "actual_time_s": float(time_val),
            "active": int(valid_arr.sum()),
            "missing": int((~valid_arr).sum()),
            "fluid_points": len(fluid_points),
            "fluid_min_xyz": fluid_points.min(axis=0).tolist(),
            "fluid_max_xyz": fluid_points.max(axis=0).tolist(),
        }
        frame_diagnostics.append(frame_diag)

        # Update views to current time
        for view in views:
            view.ViewTime = float(time_val)
            fluid.UpdatePipeline(time=float(time_val))
            boundary.UpdatePipeline(time=float(time_val))
            Render(view)

        png_path = frames_dir / f"frame_{frame_idx:04d}.png"
        SaveScreenshot(str(png_path), layout, ImageResolution=[1280, 480])

        with Image.open(png_path) as picture:
            annotated = picture.convert("RGB")
        ImageDraw.Draw(annotated).text(
            (12, 12),
            f"F3 TWOAXIS | frame {frame_idx:04d}/{num_frames - 1} | actual t={time_val:.6f} s | PRECISION NOT ACCEPTED",
            fill=(20, 20, 20),
        )
        annotated.save(png_path)

        tile = annotated.copy()
        tile.thumbnail((384, 144))
        sheet_frames.append(tile)

        anim_tile = annotated.copy()
        anim_tile.thumbnail((768, 288))
        gif_frames.append(anim_tile.convert("P", palette=Image.Palette.ADAPTIVE))

        # Contact sheet emission every contact_sheet_size frames
        if len(sheet_frames) == contact_sheet_size or frame_idx == num_frames - 1:
            sheet_img = Image.new("RGB", (4 * 384, 6 * 168), "white")
            draw = ImageDraw.Draw(sheet_img)
            start_idx = frame_idx - len(sheet_frames) + 1
            for tile_i, t_img in enumerate(sheet_frames):
                x = (tile_i % 4) * 384
                y = (tile_i // 4) * 168
                sheet_img.paste(t_img, (x, y))
                draw.text(
                    (x + 4, y + 144),
                    f"frame {start_idx + tile_i:04d}  t={actual_times[start_idx + tile_i]:.6f}",
                    fill="black",
                )
            sheet_path = output_dir / f"all_frames_{sheet_index:03d}.png"
            sheet_img.save(sheet_path)
            sheet_index += 1
            sheet_frames = []

        if frame_idx % 24 == 0 or frame_idx == num_frames - 1:
            print(json.dumps({"rendered_frame": frame_idx, "actual_time_s": float(time_val)}), flush=True)

    # Save full animated GIF
    gif_path = output_dir / "full_saved_animation.gif"
    gif_frames[0].save(
        gif_path,
        save_all=True,
        append_images=gif_frames[1:],
        duration=frame_rate_duration_ms,
        loop=0,
        optimize=False,
    )

    # Save ParaView state file
    pvsm_path = output_dir / "case.pvsm"
    SaveState(str(pvsm_path))

    report = {
        "schema": "ds02.stage1.paraview-full-animation-integrity.v1",
        "paraview_version": str(GetParaViewVersion()),
        "input_manifest": str(manifest_path),
        "manifest_sha256": sha256_file(manifest_path),
        "source_xdmf": str(source_xdmf),
        "frames": len(frame_diagnostics),
        "all_frames_rendered": len(frame_diagnostics) == manifest["frames"],
        "actual_times_preserved_exactly": True,
        "native_identity_axis_preserved": True,
        "nonfinite_active_states": 0,
        "frame_diagnostics": frame_diagnostics,
        "rendering": "CPU software/offscreen; fixed isometric and side cameras; all original saved frames",
        "visual_review": "pending root inspection of full animation and every contact sheet",
        "numerical_precision_status": "not accepted",
        "independent_case_increment": 0,
        "coordinate_frame": manifest["coordinate_frame"],
        "boundary_semantics": "fixed box walls are fixedType0 in accelerating coordinate frame; no floating or moving bodies",
        "animation_playback": f"{frame_rate_duration_ms}ms per original saved frame; actual simulation time annotated; playback speed differs from physical time",
    }

    report_path = output_dir / "paraview-full-animation-report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"all_frames_rendered": len(frame_diagnostics), "visual_review": "pending"}), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True, help="Path to XDMF product manifest.json")
    parser.add_argument("--output-dir", type=Path, required=True, help="Directory to save frames and animations")
    parser.add_argument("--opacity", type=float, default=0.15, help="Fixed boundary opacity (default: 0.15)")
    args = parser.parse_args()

    render_full_animation(
        manifest_path=args.manifest,
        output_dir=args.output_dir,
        boundary_opacity=args.opacity,
    )


if __name__ == "__main__":
    main()
