"""Read every actual XDMF frame in ParaView and render two fixed cameras.

CPU software rendering. Full frame sequence + all-frame contact sheets + GIF.
Automatic integrity checks do not replace the root's visual review.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from paraview import servermanager
from paraview.simple import (XDMFReader, Threshold, CreateView, CreateLayout,
                             AssignViewToLayout, Show, ColorBy, Render, Outline,
                             SaveScreenshot, SaveState, GetParaViewVersion, GetAnimationScene)
from paraview.vtk.util.numpy_support import vtk_to_numpy


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def leaves(data):
    if data.IsA('vtkCompositeDataSet'):
        iterator = data.NewIterator()
        iterator.SkipEmptyNodesOn()
        iterator.InitTraversal()
        while not iterator.IsDoneWithTraversal():
            yield iterator.GetCurrentDataObject()
            iterator.GoToNextItem()
    else:
        yield data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--diagnostic-frames', default=None)
    args = parser.parse_args()
    assert not (args.output_dir / 'frames').exists()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    frames_dir = args.output_dir / 'frames'
    frames_dir.mkdir()
    manifest = json.loads(args.manifest.read_text())
    source = Path(manifest['xdmf'])
    assert sha(source) == manifest['xdmf_sha256']
    reader = XDMFReader(FileNames=[str(source)])
    reader.UpdatePipelineInformation()
    assert reader.GetXMLName() == 'XdmfReader'
    expected_times = np.asarray(manifest['actual_time_s'], dtype=np.float64)
    actual_times = np.asarray(list(reader.TimestepValues), dtype=np.float64)
    np.testing.assert_array_equal(actual_times, expected_times)
    reader.PointArrayStatus = list(reader.PointArrayStatus.Available)
    scene = GetAnimationScene()
    scene.UpdateAnimationUsingDataTimeSteps()
    assert set(manifest['fields']) - {'position', 'time'} <= set(reader.PointArrayStatus.Available)
    active = Threshold(Input=reader)
    active.Scalars = ['POINTS', 'valid']
    active.LowerThreshold = 1
    active.UpperThreshold = 1
    fluid = Threshold(Input=active)
    fluid.Scalars = ['POINTS', 'type']
    fluid.LowerThreshold = 3
    fluid.UpperThreshold = 3
    boundary = Threshold(Input=active)
    boundary.Scalars = ['POINTS', 'type']
    boundary.LowerThreshold = 0
    boundary.UpperThreshold = 2
    boundary_outline = Outline(Input=boundary)
    layout = CreateLayout(name='Full saved state: isometric and transverse side views')
    views = [CreateView('RenderView'), CreateView('RenderView')]
    layout.SplitHorizontal(0, 0.5)
    for index, view in enumerate(views):
        AssignViewToLayout(view=view, layout=layout, hint=1 + index)
        view.ViewSize = [640, 480]
        view.Background = [0.96, 0.97, 0.99]
        view.OrientationAxesVisibility = 1
        view.UseColorPaletteForBackground = 0
        body_display = Show(boundary_outline, view)
        body_display.Representation = 'Wireframe'
        body_display.PointSize = 2
        body_display.Opacity = 0.5
        body_display.ColorArrayName = ['POINTS', '']
        body_display.DiffuseColor = [0.4, 0.45, 0.5]
        body_display.AmbientColor = [0.4, 0.45, 0.5]
        body_display.Ambient = 1
        body_display.Diffuse = 0
        fluid_display = Show(fluid, view)
        fluid_display.Representation = 'Points'
        fluid_display.PointSize = 2
        fluid_display.ColorArrayName = ['POINTS', '']
        fluid_display.DiffuseColor = [0.0, 0.38, 0.85]
        fluid_display.AmbientColor = [0.0, 0.38, 0.85]
        fluid_display.Ambient = 1
        fluid_display.Diffuse = 0
        view.CameraFocalPoint = [0, 0, 0.22]
        view.CameraParallelProjection = 1
        view.CameraParallelScale = 0.43
        if index == 0:
            view.CameraPosition = [1.1, -1.6, 0.95]
            view.CameraViewUp = [0, 0, 1]
        else:
            view.CameraPosition = [0, -2, 0.22]
            view.CameraViewUp = [0, 0, 1]
    rows = []
    sheet_frames = []
    gif_frames = []
    sheet_index = 0
    selection = list(range(len(actual_times))) if args.diagnostic_frames is None else [int(x) for x in args.diagnostic_frames.split(',')]
    for selection_index, frame in enumerate(selection):
        time = actual_times[frame]
        scene.AnimationTime = float(time)
        reader.UpdatePipeline(time=float(time))
        blocks = list(leaves(servermanager.Fetch(reader)))
        assert len(blocks) == 1
        data = blocks[0]
        assert data.GetNumberOfPoints() == manifest['particles']
        points = vtk_to_numpy(data.GetPoints().GetData())
        pd = data.GetPointData()
        valid = vtk_to_numpy(pd.GetArray('valid')).astype(bool)
        types = vtk_to_numpy(pd.GetArray('type'))
        ids = vtk_to_numpy(pd.GetArray('particle_id'))
        zones = vtk_to_numpy(pd.GetArray('particle_zone'))
        assert np.isfinite(points[valid]).all()
        if selection_index == 0:
            first_ids = ids.copy()
            first_zones = zones.copy()
        np.testing.assert_array_equal(ids, first_ids)
        np.testing.assert_array_equal(zones, first_zones)
        for name in ('mass', 'velocity', 'density', 'pressure'):
            values = vtk_to_numpy(pd.GetArray(name))
            assert values is not None and np.isfinite(values[valid]).all(), (frame, name)
        fluid_points = points[valid & (types == 3)]
        assert len(fluid_points) > 0
        rows.append({'frame': frame, 'actual_time_s': float(time),
                     'active': int(valid.sum()), 'missing': int((~valid).sum()),
                     'fluid_points': len(fluid_points),
                     'fluid_min_xyz': fluid_points.min(axis=0).tolist(),
                     'fluid_max_xyz': fluid_points.max(axis=0).tolist()})
        for view in views:
            view.ViewTime = float(time)
            fluid.UpdatePipeline(time=float(time))
            boundary.UpdatePipeline(time=float(time))
            Render(view)
        png = frames_dir / f'frame_{frame:04d}.png'
        SaveScreenshot(str(png), layout, ImageResolution=[1280, 480])
        with Image.open(png) as picture:
            annotated = picture.convert('RGB')
        ImageDraw.Draw(annotated).text((12, 12),
            f'F3 TWOAXIS | frame {frame:04d}/{len(actual_times)-1} | actual t={time:.6f} s | PRECISION NOT ACCEPTED',
            fill=(20, 20, 20))
        annotated.save(png)
        tile = annotated.copy()
        tile.thumbnail((384, 144))
        sheet_frames.append(tile)
        animation = annotated.copy()
        animation.thumbnail((768, 288))
        gif_frames.append(animation.convert('P', palette=Image.Palette.ADAPTIVE))
        if len(sheet_frames) == 24 or selection_index == len(selection) - 1:
            sheet = Image.new('RGB', (4 * 384, 6 * 168), 'white')
            draw = ImageDraw.Draw(sheet)
            first = selection_index - len(sheet_frames) + 1
            for index, tile in enumerate(sheet_frames):
                x, y = (index % 4) * 384, (index // 4) * 168
                sheet.paste(tile, (x, y))
                draw.text((x+4, y+144), f'frame {selection[first+index]:04d}  t={actual_times[selection[first+index]]:.6f}', fill='black')
            sheet.save(args.output_dir / f'all_frames_{sheet_index:03d}.png')
            sheet_index += 1
            sheet_frames = []
        if frame % 24 == 0:
            print(json.dumps({'rendered_frame': frame, 'actual_time_s': float(time)}), flush=True)
    gif_frames[0].save(args.output_dir / 'full_saved_animation.gif', save_all=True,
                       append_images=gif_frames[1:], duration=40, loop=0, optimize=False)
    SaveState(str(args.output_dir / 'case.pvsm'))
    result = {'schema': 'ds02.stage1.paraview-full-animation-integrity.v1',
              'paraview_version': str(GetParaViewVersion()),
              'input_manifest': str(args.manifest), 'manifest_sha256': sha(args.manifest),
              'frames': len(rows), 'all_frames_rendered': len(rows) == manifest['frames'],
              'actual_times_preserved_exactly': True, 'native_identity_axis_preserved': True,
              'nonfinite_active_states': 0, 'frame_diagnostics': rows,
              'rendering': 'CPU software/offscreen; native fluid points, native-boundary bounding outline for visibility; full geometry/state available through reader in PVSM', 'frame_selection': selection, 'diagnostic_only': args.diagnostic_frames is not None,
              'visual_review': 'pending root inspection of full animation and every contact sheet',
              'numerical_precision_status': 'not accepted', 'independent_case_increment': 0,
              'coordinate_frame': manifest['coordinate_frame'],
              'animation_playback': '40ms per original saved frame; actual simulation time annotated; playback speed differs from physical time'}
    (args.output_dir / 'paraview-full-animation-report.json').write_text(json.dumps(result, indent=2)+'\n')
    assert sha(source) == manifest['xdmf_sha256']
    print(json.dumps({'all_frames_rendered': len(rows), 'visual_review': 'pending'}), flush=True)


if __name__ == '__main__':
    main()
