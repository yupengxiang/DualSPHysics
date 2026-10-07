"""Strict digest guard for the forward-only Stage2 runtime v3."""
from pathlib import Path

import ds_data02_runtime_v3 as runtime

_base_validate = runtime.validate_request
GUARD_PATH = str(Path(__file__).resolve())


def check_registered_hashes(request, actual):
    declared = [request[key] for key in ('input_sha256', 'input_hashes') if key in request]
    if not declared:
        raise ValueError('Registered expected input digests required')
    expected = {}
    for mapping in declared:
        for name, value in mapping.items():
            key = str(Path(name).resolve())
            if key in expected and expected[key] != value:
                raise ValueError('Conflicting registered input digest: ' + key)
            expected[key] = value
    if GUARD_PATH not in actual or GUARD_PATH not in expected:
        raise ValueError('Strict dispatch v3 guard must be a digest-bound input')
    for name in request['input_files']:
        key = str(Path(name).resolve())
        if key not in expected or key not in actual:
            raise ValueError('Missing registered input digest: ' + key)
        if expected[key] != actual[key]:
            raise ValueError('Input differs from registered digest: ' + key)


def validate_request(request, approval_context=None):
    actual = _base_validate(request, approval_context=approval_context)
    check_registered_hashes(request, actual)
    return actual


def install_guard():
    if runtime.validate_request not in (_base_validate, validate_request):
        raise RuntimeError('Shared validator was unexpectedly replaced')
    runtime.validate_request = validate_request


def run_request(request_path, **kwargs):
    install_guard()
    return runtime.run_request(request_path, **kwargs)


if __name__ == '__main__':
    install_guard()
    raise SystemExit(runtime.main())
