import copy
import json
import shutil
import h5py
from test_core_cfd_dataset import _trajectory
from scripts.core_reproduction_check import compare


def test_cross_host_comparison_keeps_identity_and_invalid_state_failures(tmp_path):
    left,right=tmp_path/'a.h5',tmp_path/'b.h5'
    _trajectory(left);shutil.copyfile(left,right)
    assert compare(left,right,expected_frames=2)['passed']
    assert not compare(left,right,expected_frames=3)['passed']
    with h5py.File(right,'r+') as f:f['position'][1,0,0]+=.01
    assert compare(left,right,expected_frames=2)['first_mismatch_frame']['position']==1
    shutil.copyfile(left,right)
    with h5py.File(right,'r+') as f:f['valid'][1,0]=False
    assert compare(left,right,expected_frames=2)['first_mismatch_frame']['valid']==1
    shutil.copyfile(left,right)
    with h5py.File(right,'r+') as f:f['particle_id'][0]=77
    assert 'exact_mismatch:particle_id' in compare(left,right,expected_frames=2)['errors']


def test_score_comparison_preserves_failure_and_physics_differences(tmp_path):
    import json
    from scripts.core_reproduction_check import compare_scores
    a,b=tmp_path/'a.json',tmp_path/'b.json'
    physics={'expected_frames':2,'completed_frames':2,
             'mass_error_abs_max_kg':0.,'kinetic_energy_error_abs_max_j':0.,
             'validity_mismatch_frames':0,'changed_particle_mass_frames':0,
             'wall_chord_statuses':['checked_static_saved_chords'],
             'wall_chord_particle_count':0,'wall_chord_mass_kg':0.}
    case={'expected_frames':2,'length_m':1.,'speed_mps':1.,'failure_category':None,
          'first_failure_frame':None,'frames_predicted':2,'frames_executed':2,
          'frames_expected':2,'executed':True,'position_rmse':[.1,.2],
          'velocity_rmse':[.1,.2],'physics':{'summary':physics}}
    report={'model_kind':'mlp','cases':{'case':case}}
    a.write_text(json.dumps(report));b.write_text(json.dumps(report))
    assert compare_scores(a,b,expected_frames=2)['passed']
    assert not compare_scores(a,b,expected_frames=3)['passed']
    case['physics']['summary']['wall_chord_particle_count']=1
    b.write_text(json.dumps(report));assert not compare_scores(a,b,expected_frames=2)['passed']
    case['failure_category']='nonfinite_prediction'
    b.write_text(json.dumps(report))
    assert any(error.startswith('case_metadata_mismatch:case')
               for error in compare_scores(a,b,expected_frames=2)['errors'])


def test_score_comparison_rejects_truncated_denominator_and_missing_physics(tmp_path):
    import json
    from scripts.core_reproduction_check import compare_scores
    a,b=tmp_path/'a.json',tmp_path/'b.json'
    summary={'expected_frames':2,'completed_frames':2,
             'mass_error_abs_max_kg':0.,'kinetic_energy_error_abs_max_j':0.,
             'validity_mismatch_frames':0,'changed_particle_mass_frames':0,
             'wall_chord_statuses':['checked_static_saved_chords'],
             'wall_chord_particle_count':0,'wall_chord_mass_kg':0.}
    row={'expected_frames':2,'length_m':1.,'speed_mps':1.,'failure_category':None,
         'first_failure_frame':None,'frames_predicted':2,'frames_executed':2,
         'frames_expected':2,'executed':True,'position_rmse':[.1,.2],
         'velocity_rmse':[.1,.2],'physics':{'summary':summary}}
    report={'model_kind':'mlp','cases':{'case':row}}
    a.write_text(json.dumps(report));b.write_text(json.dumps(report))
    assert compare_scores(a,b,expected_frames=2)['passed']
    row['position_rmse']=[.1]
    a.write_text(json.dumps(report));b.write_text(json.dumps(report))
    result=compare_scores(a,b,expected_frames=2)
    assert not result['passed'] and any('invalid_score_denominator' in e for e in result['errors'])
    row['position_rmse']=[.1,.2]
    row['physics']={'summary':{'wall_chord_particle_count':0}}
    a.write_text(json.dumps(report));b.write_text(json.dumps(report))
    result=compare_scores(a,b,expected_frames=2)
    assert not result['passed'] and any('physics_summary' in e for e in result['errors'])


def test_score_comparison_requires_exact_failure_metadata_and_physics_counts(tmp_path):
    import json
    from scripts.core_reproduction_check import compare_scores
    a,b=tmp_path/'a.json',tmp_path/'b.json'
    summary={'expected_frames':3,'completed_frames':1,
             'mass_error_abs_max_kg':0.,'kinetic_energy_error_abs_max_j':0.,
             'validity_mismatch_frames':0,'changed_particle_mass_frames':0,
             'wall_chord_statuses':['checked_static_saved_chords'],
             'wall_chord_particle_count':0,'wall_chord_mass_kg':0.}
    row={'expected_frames':3,'length_m':1.,'speed_mps':1.,
         'failure_category':'nonfinite_prediction','first_failure_frame':2,
         'frames_predicted':1,'frames_executed':1,'frames_expected':3,'executed':True,
         'position_rmse':[.1,None,None],'velocity_rmse':[.1,None,None],
         'physics':{'summary':summary}}
    report={'model_kind':'mlp','cases':{'case':row}}
    a.write_text(json.dumps(report));b.write_text(json.dumps(report))
    assert compare_scores(a,b,expected_frames=3)['passed']
    row['physics']['summary']['completed_frames']=0
    b.write_text(json.dumps(report))
    result=compare_scores(a,b,expected_frames=3)
    assert not result['passed'] and any('completed_frame_mismatch' in e or 'physics_metric_mismatch' in e for e in result['errors'])
    row['physics']['summary']['completed_frames']=1
    row['first_failure_frame']=3
    b.write_text(json.dumps(report))
    result=compare_scores(a,b,expected_frames=3)
    assert not result['passed']


def test_score_comparison_keeps_unexecuted_setup_failure_in_full_denominator(tmp_path):
    import json
    from scripts.core_reproduction_check import compare_scores
    a,b=tmp_path/'a.json',tmp_path/'b.json'
    summary={'expected_frames':2,'completed_frames':0,
             'mass_error_abs_max_kg':None,'kinetic_energy_error_abs_max_j':None,
             'validity_mismatch_frames':0,'changed_particle_mass_frames':0,
             'wall_chord_statuses':[],'wall_chord_particle_count':0,'wall_chord_mass_kg':0.}
    row={'expected_frames':2,'length_m':1.,'speed_mps':1.,
         'failure_category':'rollout_setup_error','first_failure_frame':1,
         'frames_predicted':0,'frames_executed':0,'frames_expected':2,'executed':False,
         'position_rmse':[None,None],'velocity_rmse':[None,None],
         'physics':{'summary':summary}}
    report={'model_kind':'mlp','cases':{'case':row}}
    a.write_text(json.dumps(report));b.write_text(json.dumps(report))
    result=compare_scores(a,b,expected_frames=2)
    assert result['passed']
    assert result['cases']['case']['left']['selection_score']==1.


def test_score_failure_metadata_and_registered_scores_fail_closed(tmp_path):
    from scripts.core_reproduction_check import compare_scores

    summary = {'expected_frames': 3, 'completed_frames': 3,
               'mass_error_abs_max_kg': 0., 'kinetic_energy_error_abs_max_j': 0.,
               'validity_mismatch_frames': 0, 'changed_particle_mass_frames': 0,
               'wall_chord_statuses': ['checked_static_saved_chords'],
               'wall_chord_particle_count': 0, 'wall_chord_mass_kg': 0.}
    row = {'expected_frames': 3, 'length_m': 1., 'speed_mps': 1.,
           'failure_category': None, 'first_failure_frame': None,
           'frames_predicted': 3, 'frames_executed': 3, 'frames_expected': 3,
           'executed': True, 'position_rmse': [.1, .2, .3],
           'velocity_rmse': [.1, .2, .3], 'selection_score': .2,
           'physics': {'summary': summary}}

    def write_pair(left_row, right_row):
        left = tmp_path / 'left.json'
        right = tmp_path / 'right.json'
        report = {'model_kind': 'mlp', 'cases': {'case': left_row}}
        left.write_text(json.dumps(report))
        report = {'model_kind': 'mlp', 'cases': {'case': right_row}}
        right.write_text(json.dumps(report))
        return compare_scores(left, right, expected_frames=3)

    assert write_pair(row, copy.deepcopy(row))['passed']

    missing_frame = copy.deepcopy(row)
    missing_frame.update(failure_category='nonfinite_prediction', frames_predicted=1,
                         frames_executed=1, first_failure_frame=None,
                         position_rmse=[.1, None, None], velocity_rmse=[.1, None, None])
    missing_frame['physics']['summary']['completed_frames'] = 1
    result = write_pair(missing_frame, copy.deepcopy(missing_frame))
    assert not result['passed'] and any('missing_first_failure_frame' in e for e in result['errors'])

    complete_with_failure = copy.deepcopy(row)
    complete_with_failure.update(failure_category='spurious_failure', first_failure_frame=1)
    result = write_pair(complete_with_failure, copy.deepcopy(complete_with_failure))
    assert not result['passed'] and any('completed_failure_category' in e for e in result['errors'])

    inconsistent_counts = copy.deepcopy(row)
    inconsistent_counts['frames_executed'] = 2
    result = write_pair(inconsistent_counts, copy.deepcopy(inconsistent_counts))
    assert not result['passed'] and any('frames_executed' in e for e in result['errors'])

    inconsistent_prefix = copy.deepcopy(missing_frame)
    inconsistent_prefix['frames_predicted'] = inconsistent_prefix['frames_executed'] = 2
    result = write_pair(inconsistent_prefix, copy.deepcopy(inconsistent_prefix))
    assert not result['passed'] and any('frames_predicted' in e for e in result['errors'])

    out_of_range_score = copy.deepcopy(row)
    out_of_range_score['selection_score'] = 1.1
    result = write_pair(out_of_range_score, copy.deepcopy(out_of_range_score))
    assert not result['passed'] and any('invalid_selection_score' in e for e in result['errors'])

    nonfinite_score = copy.deepcopy(row)
    nonfinite_score['selection_score'] = float('nan')
    result = write_pair(nonfinite_score, copy.deepcopy(nonfinite_score))
    assert not result['passed'] and any('invalid_json' in e for e in result['errors'])


def test_hdf5_failure_metadata_is_diagnostic_and_fail_closed(tmp_path):
    left, right = tmp_path / 'left.h5', tmp_path / 'right.h5'
    _trajectory(left)
    shutil.copyfile(left, right)
    with h5py.File(right, 'r+') as handle:
        handle.attrs['failure_category'] = 'nonfinite_prediction'
    result = compare(left, right, expected_frames=2)
    assert not result['passed']
    assert any('missing_first_failure_frame:right' in error for error in result['errors'])

    shutil.copyfile(left, right)
    with h5py.File(right, 'r+') as handle:
        handle.attrs['finite_prefix_frames'] = 2
        handle.attrs['failure_category'] = 'spurious_failure'
        handle.attrs['first_failure_frame'] = 1
        handle.attrs['frames_predicted'] = 2
        handle.attrs['frames_executed'] = 2
        handle.attrs['selection_score'] = float('inf')
    result = compare(left, right, expected_frames=2)
    assert not result['passed']
    assert any('completed_failure_category:right' in error for error in result['errors'])
    assert any('invalid_selection_score:right' in error for error in result['errors'])


def test_trajectory_comparison_rejects_shared_invalid_identity_and_one_sided_nonfinite(tmp_path):
    import numpy as np
    left,right=tmp_path/'a.h5',tmp_path/'b.h5'
    _trajectory(left);shutil.copyfile(left,right)
    with h5py.File(right,'r+') as f:
        f['mass'][0]=np.nan
    result=compare(left,right,expected_frames=2)
    assert not result['passed'] and 'invalid_mass_axis:right' in result['errors']
    shutil.copyfile(left,right)
    with h5py.File(left,'r+') as f:
        f['position'][1,0,0]=np.nan
    with h5py.File(right,'r+') as f:
        f['valid'][1,0]=False
    result=compare(left,right,expected_frames=2)
    assert not result['passed']
    assert any('nonfinite_valid_state:left:position:1' in error for error in result['errors'])
    shutil.copyfile(left,right)
    with h5py.File(left,'r+') as f:
        f['valid'][1,:]=False
    shutil.copyfile(left,right)
    result=compare(left,right,expected_frames=2)
    assert not result['passed'] and any('no_active_particles:left:1' in error for error in result['errors'])
    shutil.copyfile(left,right)
    with h5py.File(left,'r+') as f:
        f['particle_id'][1]=f['particle_id'][0]
    result=compare(left,right,expected_frames=2)
    assert not result['passed'] and 'duplicate_identity:left' in result['errors']


def test_trajectory_comparison_keeps_registered_tolerances(tmp_path):
    import numpy as np
    left,right=tmp_path/'a.h5',tmp_path/'b.h5'
    _trajectory(left);shutil.copyfile(left,right)
    with h5py.File(right,'r+') as f:
        f['position'][1,0,0] += 0.5e-5
        f['velocity'][1,0,0] += 0.5e-4
    assert compare(left,right,expected_frames=2)['passed']
    with h5py.File(right,'r+') as f:
        f['position'][1,0,0] += 2e-5
    assert not compare(left,right,expected_frames=2)['passed']
