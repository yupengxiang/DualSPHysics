"""Strict actual exported geometry audit; retain owner rigid-pose mathematics."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

import numpy as np
import owner_geometry_v1 as owner


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def terminal(path):
    receipt = json.loads(Path(path).read_text())
    if receipt['status'] != 'completed' or receipt['returncode'] != 0:
        raise ValueError('Source execution is not completed successfully')
    if receipt['input_hashes_at_launch'] != receipt['input_hashes_after_run']:
        raise ValueError('Source receipt input hashes changed')
    return digest(path)


def strict_frame(path, expected):
    before = digest(path)
    with Path(path).open() as stream:
        if next(stream).strip() != 'TimeStep [s],Np,Nbound,Nfixed,Nmoving,Nfloat,Nfluid':
            raise ValueError('Unexpected native metadata columns')
        meta = next(stream).strip().split(',')
        t = float(meta[0])
        counts = [int(v) for v in meta[1:]]
        if counts != [expected, expected, 0, 0, expected, 0]:
            raise ValueError('Exported metadata cohort count mismatch')
        if next(stream).strip():
            raise ValueError('Expected native header separator')
        if next(stream).strip() != 'Pos.x [m],Pos.y [m],Pos.z [m],Zone,Idp,Type,Mk,':
            raise ValueError('Unexpected native floating-node columns')
        # The official export has an empty eighth field after its final comma.
        rows = np.loadtxt(stream, delimiter=',', usecols=range(7), ndmin=2)
    if rows.shape != (expected, 7) or not np.isfinite(rows).all() or not np.isfinite(t):
        raise ValueError('Missing or nonfinite exported rows')
    if not np.array_equal(rows[:, 3:], np.floor(rows[:, 3:])):
        raise ValueError('Nonintegral native identity/type fields')
    if not ((rows[:, 3] == 0).all() and (rows[:, 5] == 2).all() and (rows[:, 6] == 60).all()):
        raise ValueError('Unexpected native Zone/Type/Mk; no row filtering permitted')
    ids = rows[:, 4].astype(np.int64)
    if (ids < 0).any() or len(np.unique(ids)) != expected:
        raise ValueError('Duplicate or invalid floating-node identity')
    order = np.argsort(ids)
    after = digest(path)
    if before != after:
        raise ValueError('Native CSV changed during analysis')
    return t, ids[order], rows[order, :3], before


def audit_case(case):
    bindings = {'export_receipt_sha256': terminal(case['export_receipt']),
                'floating_info_receipt_sha256': terminal(case['floating_info_receipt']),
                'xml_sha256': digest(case['xml']),
                'floating_info_sha256': digest(case['floating_info'])}
    paths = case['csvs']
    if len(paths) != 241 or [Path(p).name for p in paths] != [f'PartFloating_{i:04d}.csv' for i in range(241)]:
        raise ValueError('Full 241 explicit native Part sequence is required')
    n = case['expected_node_count']
    records = []
    hashes = {}
    for index, path in enumerate(paths):
        t, ids, coords, sha = strict_frame(path, n)
        if index == 0:
            initial_ids, initial_coords = ids.copy(), coords.copy()
        if not np.array_equal(ids, initial_ids):
            raise ValueError('Actual Zone/Idp cohort changed')
        if index and t <= records[-1]['time_s']:
            raise ValueError('Native times must increase strictly')
        fit = owner.compute_kabsch_svd(initial_coords, coords)
        R = fit['rotation_matrix']
        if not fit['is_rank_3'] or not np.isfinite(R).all() or not np.allclose(R.T @ R, np.eye(3), atol=1e-10, rtol=0) or abs(fit['det_R'] - 1) > 1e-10:
            raise ValueError('Rank-deficient or improper rigid-pose fit')
        hashes[path] = sha
        records.append({'part': index, 'time_s': t,
                        'center_m': fit['target_centroid_m'].tolist(),
                        'rotation_matrix': R.tolist(),
                        'quaternion_wxyz': fit['quaternion_wxyz'].tolist(),
                        'det_R': fit['det_R'], 'reference_covariance_singular_values_m2': fit['ref_singular_values'],
                        'rigidity_rms_m': fit['rigidity_rms_m'],
                        'rigidity_max_m': fit['rigidity_max_m'],
                        'reflection_correction_used': fit['reflection_detected']})
        if index % 40 == 0:
            print(case['role'], 'actual native geometry frame', index, '/240', flush=True)
    times = np.array([r['time_s'] for r in records])
    if times[0] != 0 or times[-1] < 12 or np.abs(times - np.arange(241) * .05).max() > .001:
        raise ValueError('Native sequence does not cover the full registered window')
    with Path(case['floating_info']).open() as stream:
        fi = list(csv.DictReader(stream, delimiter=';'))
    if len(fi) != 241 or [int(r['part']) for r in fi] != list(range(241)):
        raise ValueError('Full native FloatingInfo sequence is required')
    fi_times = np.array([float(r['time [s]']) for r in fi])
    fi_centres = np.array([[float(r[f'center.{axis} [m]']) for axis in 'xyz'] for r in fi])
    if not np.isfinite(fi_times).all() or not np.isfinite(fi_centres).all() or np.any(np.diff(fi_times) <= 0):
        raise ValueError('Nonfinite or nonmonotonic FloatingInfo source')
    offsets = np.abs(fi_times - times)
    if offsets.max() >= 1e-4:
        raise ValueError('All 241 same-Part FloatingInfo timestamps must match native node frames')
    centres = np.array([r['center_m'] for r in records])
    differences = np.linalg.norm(centres - fi_centres, axis=1)
    if digest(case['floating_info']) != bindings['floating_info_sha256']:
        raise ValueError('FloatingInfo source changed')
    trajectory = {'times': times, 'centroids': centres,
                  'quaternions': np.array([r['quaternion_wxyz'] for r in records])}
    report = {'case_id': case['case_id'], 'node_count': n, 'frame_count': 241,
              'native_window_s': [float(times[0]), float(times[-1])],
              'native_identity': 'exact immutable (Zone=0, Idp) floating cohort; Type=2, Mk=60, no skipped rows',
              'bindings': bindings, 'csv_sha256': hashes, 'frames': records,
              'centroid_validation': {'matched_frames': 241, 'max_timestamp_difference_s': float(offsets.max()),
                                      'geometry_minus_FloatingInfo_rmse_m': float(np.sqrt(np.mean(differences ** 2))),
                                      'geometry_minus_FloatingInfo_max_m': float(differences.max())},
              'rigidity_rms_max_m': max(r['rigidity_rms_m'] for r in records),
              'rigidity_residual_max_m': max(r['rigidity_max_m'] for r in records)}
    return trajectory, report


def main():
    p = argparse.ArgumentParser();p.add_argument('--binding', required=True);p.add_argument('--output', required=True)
    args = p.parse_args();b = json.loads(Path(args.binding).read_text())
    if digest(Path(__file__).with_name('owner_geometry_v1.py')) != b['owner_sha256']:
        raise ValueError('Owner helper bytes differ')
    plan = json.loads(Path(b['observation_plan']).read_text())
    if plan['physical_scales']['length_L_m'] != .8:
        raise ValueError('Frozen characteristic length changed')
    trajectories = {}; reports = {}
    for case in b['cases']:
        trajectories[case['role']], reports[case['role']] = audit_case(case)
    grid = np.arange(241, dtype=float) * .05
    for tr in trajectories.values():
        if grid[0] < tr['times'][0] or grid[-1] > tr['times'][-1]:
            raise ValueError('No pose extrapolation or endpoint clamping allowed')
    comparisons = {}
    for left, right in [('fine', 'medium'), ('fine', 'coarse'), ('medium', 'coarse')]:
        comparisons[left + '_vs_' + right] = owner.compare_trajectories_physical_time(trajectories[left], trajectories[right], grid)
    result = {'schema': 'ds02.f6.actual-full241-geometry-pose-comparison.v1', 'cases': reports,
              'physical_comparison_grid_s': grid.tolist(), 'pairs': comparisons,
              'observation_plan_sha256': digest(b['observation_plan']),
              'claim_boundary': {'q_n': 'not_granted', 'production_approval': 'none',
                                 'orientation_budget': None, 'orientation_budget_status': 'unregistered',
                                 'orientation_operator': 'geometry Kabsch relative initial same-UID body; physical-time SLERP, no Euler chart assumption',
                                 'mass_policy': 'uniform geometry fit, no physical mass normalization; rigid body 128 kg and lattice support approximately 256 kg remain distinct',
                                 'rigidity_residual_policy': 'descriptive actual geometric residuals; no invented numerical-convergence threshold',
                                 'translation_policy': 'generic L=0.8 m, 5% reference reporting does not establish whole-family Q-N'}}
    Path(args.output).write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')


if __name__ == '__main__':
    main()
