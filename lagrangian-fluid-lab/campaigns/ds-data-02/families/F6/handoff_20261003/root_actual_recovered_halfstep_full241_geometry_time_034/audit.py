"""Audit every recovered rigid frame after an exporter filename-count defect."""
import argparse
import csv
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--binding', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    assert not args.output.exists()
    b = json.loads(args.binding.read_text())
    sys.path.insert(0, str(Path(b['geometry_worker']).parent))
    spec = importlib.util.spec_from_file_location('strict_native_geometry', b['geometry_worker'])
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    original_terminal = m.terminal
    failed_path = Path(b['half']['export_receipt'])
    failed = json.loads(failed_path.read_text())
    assert failed['status'] == 'failed' and failed['returncode'] == 1
    assert failed['input_hashes_at_launch'] == failed['input_hashes_after_run']
    stdout = failed_path.parent / 'stdout.log'
    text = stdout.read_text()
    assert 'SaveCSV> .../floating_parts/PartFloating_0240.csv  np:131072' in text
    assert 'assert len(outputs)' in text and text.rstrip().endswith('AssertionError')
    assert 'Time of operation:' in text
    for path, digest in failed['input_hashes_at_launch'].items():
        assert m.digest(path) == digest, 'Export input changed: ' + path
    assert m.digest(b['failed_export_worker']) == b['failed_export_worker_sha256']
    # Unchanged pinned source first asserts subprocess exit0 and an unchanged
    # raw source snapshot. Only then does its overly broad CSV glob fail.
    # Preserve the failed global receipt; validate all intended frames below.
    def artifact_terminal(path):
        if Path(path) == failed_path:
            return m.digest(path)
        return original_terminal(path)
    m.terminal = artifact_terminal
    half, half_report = m.audit_case(b['half'])
    _, ids0, coords0, _ = m.strict_frame(b['baseline_initial_csv'], 131072)
    _, ids1, coords1, _ = m.strict_frame(b['half']['csvs'][0], 131072)
    assert np.array_equal(ids0, ids1) and np.array_equal(coords0, coords1)
    parent = json.loads(Path(b['baseline_geometry_report']).read_text())
    original_terminal(b['baseline_geometry_receipt'])
    baseline_rows = parent['cases']['fine']['frames']
    assert len(baseline_rows) == 241
    alignment = {}
    trajectories = {}
    for role, records, fi in [('baseline', baseline_rows, b['baseline_floating_info']),
                              ('half', half_report['frames'], b['half']['floating_info'])]:
        with Path(fi).open() as stream:
            rows = list(csv.DictReader(stream, delimiter=';'))
        assert len(rows) == 241 and [int(r['part']) for r in rows] == list(range(241))
        times = np.asarray([float(r['time [s]']) for r in rows])
        rounded = np.asarray([r['time_s'] for r in records])
        assert times[0] == 0 and times[-1] >= 12 and np.isfinite(times).all()
        assert (np.diff(times) > 0).all() and np.max(np.abs(rounded-times)) < 1e-4
        trajectories[role] = {'times': times,
                              'centroids': np.asarray([r['center_m'] for r in records]),
                              'quaternions': np.asarray([r['quaternion_wxyz'] for r in records])}
        alignment[role] = {'full_precision_native_time_source': fi,
                           'maximum_exported_time_rounding_difference_s': float(np.max(np.abs(times-rounded)))}
    grid = np.arange(241) * .05
    assert all(t['times'][0] <= grid[0] and t['times'][-1] >= grid[-1] for t in trajectories.values())
    comparison = m.owner.compare_trajectories_physical_time(trajectories['baseline'], trajectories['half'], grid)
    result = {'schema': 'ds02.f6.actual-recovered-full241-independent-time-geometry.v1',
              'binding': b, 'half_native_geometry': half_report, 'alignment': alignment,
              'comparison': comparison, 'initial_native_identity_and_geometry_identical': True,
              'failed_export_receipt_status': 'failed', 'failed_export_receipt_sha256': m.digest(failed_path),
              'original_native_solver_OS_returncode': None,
              'recovery_evidence': 'Official PartVTK completed all241 frames; pinned wrapper passed child-exit0/raw-source-unchanged checks before its glob included PartFloating_stats.csv. Every intended native frame is independently validated here; original failed receipt unchanged.',
              'claim_boundary': {'q_n': 'not_granted', 'production_approval': 'none',
                                 'orientation_qualification_budget': None,
                                 'orientation_note': 'SO3 discrepancies descriptive; no invented radian reference scale or acceptance gate.',
                                 'translation_budget_note': 'Preserved original observer generic5% report; independent allocation must be traced to frozen contract before assigning qualification.',
                                 'full_fluid_state_and_transport': 'pending'}}
    with args.output.open('x') as stream:
        stream.write(json.dumps(result, indent=2, allow_nan=False) + '\n')
    print(json.dumps(comparison))


if __name__ == '__main__':
    main()
