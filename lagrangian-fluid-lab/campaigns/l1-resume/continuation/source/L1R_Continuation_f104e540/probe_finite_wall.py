#!/usr/bin/env python3
"""Read-only, bounded crossing probe; not a CFD or full regression test.

Default: evaluate the source-derived bottom-face predicate used in this review.
With --lab: import the local scripts/finite_wall_audit.py and exercise its
public segment_crossing_events function. The output records which mode ran.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any
import numpy as np

BASELINE = 'f104e5409cec2c8dd4043f93ffc4f6c7cda96646'
TOLERANCE = 0.0051
WALL_SPEC = {
    'container_interior': {'xmin': 0., 'xmax': 1.2, 'ymin': 0., 'ymax': .4, 'zmin': 0., 'zmax': .6},
    'closed_faces': ['bottom', 'left', 'right', 'front', 'back'],
    'open_faces': ['top'], 'obstacles': [], 'runtime_domain': None,
}

def source_predicate(p0: float, p1: float) -> bool:
    # Literal numerical conditions from _segment_face_hits, reduced to the
    # bottom plane at z=0 and interior x/y. This is NOT the imported function.
    d = p1 - p0
    direction = d < 0.0
    candidate = direction and p0 >= -TOLERANCE and p1 < -TOLERANCE
    fraction = -p0 / d if direction else float('nan')
    return bool(candidate and np.isfinite(fraction) and 0.0 <= fraction <= 1.0)

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lab', type=Path, help='Actual local lagrangian-fluid-lab path; no solver is launched.')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    module: Any = None
    source_metadata: dict[str, Any] = {}
    if args.lab is not None:
        path = args.lab.resolve() / 'scripts' / 'finite_wall_audit.py'
        if not path.is_file():
            parser.error(f'Actual module is absent: {path}')
        spec = importlib.util.spec_from_file_location('review_finite_wall_module', path)
        if spec is None or spec.loader is None:
            raise RuntimeError('Cannot load finite_wall_audit.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        source_metadata = {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    scenarios = [('one_step', [.002, -.006]), ('same_line_more_frames', [.002, -.002, -.006])]
    rows = []
    for label, zs in scenarios:
        hit_counts = []
        for a, b in zip(zs[:-1], zs[1:]):
            if module is None:
                hit_counts.append(int(source_predicate(a, b)))
            else:
                p0 = np.array([[.6, .2, a]], dtype=float)
                p1 = np.array([[.6, .2, b]], dtype=float)
                events = module.segment_crossing_events(p0, p1, WALL_SPEC, TOLERANCE)
                hit_counts.append(sum(e.get('face') == 'bottom' for e in events))
        rows.append({'name': label, 'z_saved_m': zs, 'hits_by_interval': hit_counts,
                     'crossing_reported': sum(hit_counts) > 0,
                     'endpoint_beyond_band': zs[-1] < -TOLERANCE,
                     'analytic_path_crosses_z0': min(zs) < 0 < max(zs)})
    invariant = all(row['crossing_reported'] for row in rows)
    result = {
        'baseline_reviewed': BASELINE,
        'mode': 'actual_local_module' if module is not None else 'source_derived_predicate_only',
        'source': source_metadata,
        'tolerance_m': TOLERANCE,
        'cases': rows,
        'straight_path_resampling_preserves_detection': invariant,
        'claims_not_made': ['CFD was not run', 'Full regression was not run', 'This does not classify actual Q2 particles'],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))
    # A diagnostic observation is not an automatic campaign acceptance gate.
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
