import pytest
from scripts.ds_data02_time_study import measure


def test_actual_internal_steps_are_separate_from_saved_frames(tmp_path):
    path = tmp_path / 'RunPARTs.csv'
    path.write_text('Part;TimeStep [s];Steps;NpOut;DtMin [s];DtMax [s]\n'
                    '0;0;0;0;0;0\n1;0.01;100;0;0.00007;0.00012\n'
                    '2;0.02;200;0;0.00003;0.00008\n# footer\n')
    result = measure(path)
    assert result['internal_step_count'] == 300
    assert result['saved_frame_count'] == 3
    assert result['native_minimum_dt_s'] == 0.00003
    assert result['median_internal_dt_s'] is None
    path.write_text(path.read_text().replace('2;0.02;200;0;', '2;0.02;200;1;'))
    with pytest.raises(ValueError, match='excluded-particle'):
        measure(path)
