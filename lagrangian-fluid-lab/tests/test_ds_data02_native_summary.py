import csv
import json
import pytest
from scripts.ds_data02_native_summary import read_runparts, summarize


def history(path, last_population):
    keys = ['TimeStep [s]', 'NpSim', 'NpNew', 'NpOut', 'NpOutPos', 'NpOutRho', 'NpOutMov', 'NpfSim', 'NpbSim', 'DtMin [s]', 'DtMax [s]', 'Steps']
    with path.open('w') as stream:
        writer = csv.writer(stream, delimiter=';')
        writer.writerow(keys)
        writer.writerows([[0, 20, 0, 0, 0, 0, 0, 10, 10, 0, 0, 0],
                         [.1, 18, 0, 2, 1, 1, 0, 8, 10, .001, .002, 75],
                         [.2, last_population, 0, 0, 0, 0, 0, 8, 10, .001, .002, 75]])


def test_last_interval_zero_does_not_erase_prior_native_exclusions(tmp_path):
    p = tmp_path / 'RunPARTs.csv'
    history(p, 18)
    result = read_runparts(p)
    assert result['excluded_interval_sums'] == dict(NpOut=2, NpOutPos=1, NpOutRho=1, NpOutMov=0)
    assert result['internal_steps'] == 150 and result['saved_frames'] == 3


def test_inconsistent_native_population_account_is_rejected(tmp_path):
    p = tmp_path / 'RunPARTs.csv'
    history(p, 20)
    with pytest.raises(ValueError, match='population account'):
        read_runparts(p)


def test_native_npf_counter_does_not_count_floating_as_fluid(tmp_path):
    history(tmp_path / 'RunPARTs.csv', 18)
    (tmp_path / 'Run.out').write_text('**3D-Simulation parameters:\nCaseNfixed=10\nCaseNmoving=0\nCaseNfloat=2\nCaseNfluid=8\nExcluded particles: 2\n')
    receipt = tmp_path / 'execution-receipt.json'
    receipt.write_text(json.dumps(dict(status='completed', returncode=0, request=dict(case_id='synthetic-floating', attempt_id='test'), command=['synthetic'], gpu_seconds=0)))
    result = summarize(receipt)['facts']
    assert result['initial_fluid_particles'] == 8
    assert result['initial_floating_particles'] == 2
    assert result['initial_native_npf_particles'] == 10
    assert result['final_fluid_particles'] is None
