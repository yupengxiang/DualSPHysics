import json
import sys
from pathlib import Path

import h5py
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from ds_data02_f7_reference_labels_v1 import observe


def test_recrossings_aperture_and_exclusion_remain_distinct(tmp_path):
    config = {'frame_kind': 'fixed_solver_frame', 'coordinate_frame': 'test',
              'source_regions': [{'id': 'left', 'bounds': [[-2, 0], [-1, 1], [0, 1]]}],
              'destination_regions': [{'id': 'left', 'bounds': [[-2, 0], [-1, 1], [0, 1]]},
                                      {'id': 'right', 'bounds': [[0, 2], [-1, 1], [0, 1]]}],
              'events': [{'id': 'exchange', 'axis': 0, 'value': 0.,
                          'aperture_bounds': [[-.5, .5], [0, 1]]}]}
    source, output = tmp_path / 'source.h5', tmp_path / 'labels.h5'
    pos = np.zeros((4, 3, 3));pos[:, :, 2] = .5
    pos[:, :, 0] = np.array([-1., 1., -1., 1.])[:, None]
    pos[:, 1, 1] = .75  # crosses the plane outside the finite aperture
    valid = np.ones((4, 3), dtype=bool);valid[2:, 2] = False
    pos[2:, 2] = np.nan
    with h5py.File(source, 'w') as h:
        h.attrs['coordinate_frame'] = 'test'
        for name, value in {'time': np.arange(4.), 'position': pos, 'valid': valid,
                            'mass': np.ones((4, 3)), 'type': np.full((4, 3), 3),
                            'particle_id': [10, 20, 30], 'particle_zone': [0, 0, 0]}.items():
            h.create_dataset(name, data=value)
    result = observe(source, output, config, particle_chunk=2)
    assert result['event_crossing_counts'] == [4]
    assert result['final_native_exclusion_mass_kg'] == 1.
    with h5py.File(output) as h:
        assert h['total_crossing_count'][:, 0].tolist() == [3, 0, 1]
        assert h['cyclic_recrossing_count'][:, 0].tolist() == [2, 0, 0]
        assert h['final_category'][:].tolist() == [2, 2, -1]
        assert h['all_observed_crossings']['direction'].tolist() == [1, -1, 1, 1]
        assert h['all_observed_crossings']['idp'].tolist() == [10, 10, 10, 30]
        assert h.attrs['q_n_status'] == 'not_assessed'
