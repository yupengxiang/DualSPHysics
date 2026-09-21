import numpy as np
import pytest

from scripts.finite_wall_audit import bidirectional_face_crossing_events, segment_crossing_events


SPEC = {"container_interior": dict(xmin=0, xmax=1, ymin=0, ymax=1, zmin=0, zmax=.6)}


def test_outward_inward_and_open_rim():
    start = np.array([[.5, .1, .59], [.5, -.1, .59], [.5, .1, .61]])
    end = np.array([[.5, -.1, .59], [.5, .3, .59], [.5, -.1, .61]])
    events = bidirectional_face_crossing_events(start, end, SPEC, .002)
    assert [(e['point_index'], e['direction']) for e in events] == [
        (0, 'outward'), (1, 'inward')]
    assert [e['fraction'] for e in events] == pytest.approx([.5, .25])
    assert all(e['face'] == 'front' for e in events)
    assert len(segment_crossing_events(start, end, SPEC, .002)) == 1


def test_contact_reversal_and_finite_extent():
    start = np.array([[.5, 0, .3], [2, .1, .3]])
    end = np.array([[.5, -.1, .3], [2, -.1, .3]])
    forward = bidirectional_face_crossing_events(start, end, SPEC, 0)
    reverse = bidirectional_face_crossing_events(end, start, SPEC, 0)
    assert len(forward) == len(reverse) == 1
    assert forward[0]['fraction'] == 0
    assert reverse[0]['fraction'] == 1
    assert reverse[0]['direction'] == 'inward'


def test_reject_nonfinite():
    with pytest.raises(ValueError, match='finite'):
        bidirectional_face_crossing_events([[0, 0, float('nan')]], [[0, 0, 0]], SPEC, 0)
