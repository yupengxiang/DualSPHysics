"""Measure actual initial fluid/body separation before diagnosing native failures."""
import argparse
import csv
import json
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree


def audit(report_path, dp):
    report = json.loads(report_path.read_text())
    path = Path(report['partvtk_audit']['csv'])
    with path.open() as stream:
        header = next(csv.reader(stream))
    names = [name.strip() for name in header]
    fields = ('Pos.x [m]', 'Pos.y [m]', 'Pos.z [m]', 'Type')
    rows = np.loadtxt(path, delimiter=',', skiprows=1, usecols=[names.index(name) for name in fields])
    if not np.all(np.isfinite(rows)):
        raise ValueError('Nonfinite native initial positions/types')
    body = rows[rows[:, 3] == 2, :3]
    fluid = rows[rows[:, 3] == 3, :3]
    fixed = rows[rows[:, 3] == 0, :3]
    expected = report['partvtk_audit']['typed_counts']
    if len(body) != expected['body'] or len(fluid) != expected['fluid'] or len(fixed) != expected['fixed']:
        raise ValueError('Actual native initial typed counts differ from report')
    low, high = body.min(axis=0), body.max(axis=0)
    inside = np.all((fluid >= low) & (fluid <= high), axis=1)
    # Query every body support point against all actual fluid points. No
    # subsampling or bounding-box inference replaces the actual minimum.
    distance, nearest = cKDTree(fluid).query(body, k=1, workers=1)
    minimum = int(np.argmin(distance))
    return dict(case_id=report['case_id'],native_initial_report=str(report_path),
                official_initial_csv=str(path), dp_m=dp,body_particles=len(body),fluid_particles=len(fluid),
                body_bounds_m=[low.tolist(),high.tolist()],
                fluid_bounds_m=[fluid.min(axis=0).tolist(),fluid.max(axis=0).tolist()],
                minimum_body_fluid_distance_m=float(distance[minimum]),
                minimum_distance_in_dp=float(distance[minimum]/dp),
                minimum_pair_body_xyz_m=body[minimum].tolist(),
                minimum_pair_fluid_xyz_m=fluid[nearest[minimum]].tolist(),
                body_nearest_fluid_distance_quantiles_m={str(q):float(np.quantile(distance,q)) for q in (0,.01,.5,1)},
                fluid_inside_body_point_bounds=int(inside.sum()),
                exact_body_fluid_coordinate_overlaps=int(np.count_nonzero(distance < 1e-8)),
                interpretation='Initial clearance diagnostic only. A positive gap does not establish temporal stability or numerical qualification.')


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    sources=json.loads(args.manifest.read_text())['sources']
    records=[]
    for row in sources:
        records.append(audit(Path(row['report']),row['dp_m']))
        print(json.dumps(records[-1]),flush=True)
    output=dict(schema='ds02.f6.actual-native-initial-clearance.v1',status='completed',references=records,q_n_granted=False,production_granted=False)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x') as stream:
        json.dump(output,stream,indent=2);stream.write('\n')
