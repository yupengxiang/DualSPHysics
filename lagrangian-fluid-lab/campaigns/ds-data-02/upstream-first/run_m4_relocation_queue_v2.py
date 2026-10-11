"""Preserve the first launch and bind future copies to their charged attempt."""
from pathlib import Path

import run_m4_relocation_queue as previous

_execute = previous.execute


def bind_future_destination(run, request):
    """PREP runner expansion must not fix a future output to the PREP root."""
    if request['attempt_id'] != 'm4-actual-validation-001':
        return request
    case = request['case_id']
    if run.name != case or request['source_bundle']['production_validation']['portable'] is not True:
        raise RuntimeError('actual completed source binding is required')
    relocated = '{attempt_root}/m4-actual-validation/relocated/' + case
    output = '{attempt_root}/m4-actual-validation/results'
    for option, value in (('--relocated-bundle', relocated), ('--output', output)):
        index = request['command'].index(option) + 1
        request['command'][index] = value
    request['destination_contract']['relocated_bundle'] = relocated
    request['destination_contract']['validation_output'] = output
    request['root_destination_rebinding'] = {
        'reason': 'prepare runner expands argv placeholders using its own attempt; future outputs are rebound before root grant',
        'all_new_outputs_inside_the_charged_validation_attempt': True,
        'source_bindings_unchanged': True,
    }
    return request


def execute(run, request):
    request = bind_future_destination(run, request)
    request['input_files'].append(str(Path(__file__).resolve()))
    return _execute(run, request)


def main():
    previous.execute = execute
    previous.main()


if __name__ == '__main__':
    main()
