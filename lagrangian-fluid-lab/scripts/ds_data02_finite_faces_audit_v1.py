"""Bounded native GenCase open-tank face audit; no solver or Q-N grant."""
import argparse
import json
from pathlib import Path

from ds_data02_finite_faces_v1 import bound_vtk_points, open_tank_coverage, face_coverage
from ds_data02_native_labels import digest


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--low', nargs=3, type=float, required=True)
    parser.add_argument('--high', nargs=3, type=float, required=True)
    parser.add_argument('--dp', type=float, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--include-moving', action='store_true')
    parser.add_argument('--separator-low', nargs=3, type=float)
    parser.add_argument('--separator-high', nargs=3, type=float)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    before = digest(args.source)
    points, types = bound_vtk_points(args.source)
    mask = (types == 0) | ((types == 1) & args.include_moving)
    result = open_tank_coverage(points[mask], low_m=args.low, high_m=args.high, dp_m=args.dp)
    if args.separator_low is not None:
        if args.separator_high is None:
            raise ValueError('Both separator bounds required')
        faces = {}
        for axis in range(3):
            tangent = [i for i in range(3) if i != axis]
            for side in ('low', 'high'):
                if axis == 2 and side == 'low':
                    continue  # Declared separator all^bottom meets the tank floor.
                faces[f'{"xyz"[axis]}_{side}'] = face_coverage(points[mask], normal_axis=axis, plane_m=(args.separator_low if side == 'low' else args.separator_high)[axis], tangential_low_m=[args.separator_low[i] for i in tangent], tangential_high_m=[args.separator_high[i] for i in tangent], dp_m=args.dp)
        result['separator_five_face_sampling'] = faces
        result['separator_face_coverage_pass'] = all(x['covered'] for x in faces.values())
    assert digest(args.source) == before
    result.update(schema='ds02.native-finite-face-sampled-audit.v1', native_source=str(args.source), native_source_sha256=before, source_point_count=len(points), selected_native_boundary_points=int(mask.sum()), included_types=[0, 1] if args.include_moving else [0], physical_tank_low_m=args.low, physical_tank_high_m=args.high, q_n_status='not_assessed', production_approval='none')
    args.output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({'all_five_finite_faces_covered': result['all_five_finite_faces_covered'], 'q_n_status': 'not_assessed'}))
