import sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from ds_data02_finite_faces_v1 import face_coverage


def test_half_cell_phase_covers_full_physical_face():
    x, z = np.meshgrid(np.arange(.05, 1, .1), np.arange(.05, 1, .1))
    points = np.column_stack([x.ravel(), np.full(x.size, .05), z.ravel()])
    report = face_coverage(points, normal_axis=1, plane_m=0, tangential_low_m=[0, 0], tangential_high_m=[1, 1], dp_m=.1)
    assert report['covered']


def test_boundary_edges_cannot_masquerade_as_complete_face():
    x, z = np.meshgrid(np.linspace(0, 1, 11), np.linspace(0, 1, 11))
    edge = (x == 0) | (x == 1) | (z == 0) | (z == 1)
    points = np.column_stack([x[edge], np.zeros(edge.sum()), z[edge]])
    report = face_coverage(points, normal_axis=1, plane_m=0, tangential_low_m=[0, 0], tangential_high_m=[1, 1], dp_m=.1)
    assert not report['covered']
    assert report['uncovered_surface_samples'] > 0
    assert report['maximum_distance_m'] >= .5


def test_remote_objects_cannot_fill_missing_plane():
    x, z = np.meshgrid(np.linspace(0, 1, 11), np.linspace(0, 1, 11))
    points = np.column_stack([x.ravel(), np.full(x.size, .2), z.ravel()])
    assert not face_coverage(points, normal_axis=1, plane_m=0, tangential_low_m=[0, 0], tangential_high_m=[1, 1], dp_m=.1)['covered']
