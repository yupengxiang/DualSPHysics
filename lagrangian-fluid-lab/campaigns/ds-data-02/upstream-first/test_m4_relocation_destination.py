from copy import deepcopy
import importlib.util
from pathlib import Path
import sys

P = Path(__file__).resolve().parent
sys.path.insert(0, str(P))
import run_m4_relocation_queue_v2 as queue


def test_completed_preparation_does_not_capture_future_output_root():
    case = 'UF_F1_MDBC_DP010_H050'
    wrong = '/data/nas/example/' + case + '/m4-relocation-preparation-001/relocated'
    request = {'attempt_id': 'm4-actual-validation-001', 'case_id': case,
               'source_bundle': {'production_validation': {'portable': True}},
               'command': ['python', 'worker.py', 'run', '--relocated-bundle', wrong,
                           '--output', '{attempt_root}/m4-actual-validation/results'],
               'destination_contract': {'relocated_bundle': wrong},
               'input_files': ['immutable_source_receipt.json']}
    source_inputs = deepcopy(request['input_files'])
    fixed = queue.bind_future_destination(Path('/data/nas/example') / case, request)
    destination = fixed['command'][fixed['command'].index('--relocated-bundle') + 1]
    assert destination == '{attempt_root}/m4-actual-validation/relocated/' + case
    final_root = '/data/nas/example/' + case + '/m4-actual-validation-001'
    assert Path(destination.replace('{attempt_root}', final_root)).is_relative_to(final_root)
    assert fixed['input_files'] == source_inputs
