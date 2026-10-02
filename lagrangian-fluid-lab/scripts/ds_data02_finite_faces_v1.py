"""Audit every finite rectangular face interior against native boundary points."""
from pathlib import Path
import re

import numpy as np
from scipy.spatial import cKDTree


def bound_vtk_points(path):
    raw = Path(path).read_bytes()
    header = re.search(rb'POINTS\s+(\d+)\s+float\n', raw)
    if header is None:
        raise ValueError('Binary GenCase POINTS header absent')
    count = int(header[1])
    points = np.frombuffer(raw, dtype='>f4', count=count*3, offset=header.end()).reshape(count, 3).astype(float)
    header = re.search(rb'Type\s+1\s+'+str(count).encode()+rb'\s+unsigned_char\n', raw)
    if header is None:
        raise ValueError('Binary GenCase Type header absent')
    types = np.frombuffer(raw, dtype='u1', count=count, offset=header.end()).copy()
    return points, types


def face_coverage(points, *, normal_axis, plane_m, tangential_low_m, tangential_high_m, dp_m, tolerance_m=2e-6):
    """Cover the declared face, including interior, edges and physical corners.

    Sampling spacing is at most dp along both physical tangents. The permitted
    3D distance is half a cell diagonal plus serialization tolerance, allowing
    a documented half-dp lattice offset on any coordinate. This is an initial
    boundary population check, not a hydrodynamic accuracy certificate.
    """
    points = np.asarray(points, dtype=float)
    if points.ndim != 2 or points.shape[1] != 3 or not np.isfinite(points).all() or dp_m <= 0:
        raise ValueError('Invalid native points or dp')
    axes = [axis for axis in range(3) if axis != normal_axis]
    low, high = np.asarray(tangential_low_m), np.asarray(tangential_high_m)
    if len(low) != 2 or len(high) != 2 or np.any(high <= low):
        raise ValueError('Invalid finite face tangents')
    near = points[np.abs(points[:, normal_axis]-plane_m) <= dp_m/2+tolerance_m]
    radius = np.sqrt(3)*dp_m/2+tolerance_m
    samples = [np.linspace(low[i], high[i], int(np.ceil((high[i]-low[i])/dp_m))+1) for i in range(2)]
    first, second = np.meshgrid(*samples, indexing='ij')
    query = np.full((first.size, 3), plane_m)
    query[:, axes[0]], query[:, axes[1]] = first.ravel(), second.ravel()
    distances = cKDTree(near).query(query, workers=1)[0] if len(near) else np.full(len(query), np.inf)
    missing = distances > radius
    worst = int(np.argmax(distances))
    return {'normal_axis': normal_axis, 'plane_m': plane_m, 'tangential_low_m': low.tolist(), 'tangential_high_m': high.tolist(), 'sampling_spacing_at_most_dp_m': dp_m, 'native_near_plane_points': len(near), 'physical_surface_samples': len(query), 'maximum_distance_m': float(distances[worst]) if len(near) else None, 'acceptance_distance_m': float(radius), 'uncovered_surface_samples': int(missing.sum()), 'worst_physical_point_m': query[worst].tolist(), 'covered': bool(not missing.any()), 'claim_boundary': 'Native finite face population coverage only; full dynamics, normals, lifecycle and Q-N require separate evidence'}


def open_tank_coverage(points, *, low_m, high_m, dp_m):
    low, high = np.asarray(low_m), np.asarray(high_m)
    result = {}
    for axis in range(3):
        tangents = [i for i in range(3) if i != axis]
        for side in ('low', 'high'):
            if axis == 2 and side == 'high':
                continue
            result[f'{"xyz"[axis]}_{side}'] = face_coverage(points, normal_axis=axis, plane_m=float((low if side == 'low' else high)[axis]), tangential_low_m=low[tangents], tangential_high_m=high[tangents], dp_m=dp_m)
    return {'faces': result, 'all_five_finite_faces_covered': all(row['covered'] for row in result.values())}
