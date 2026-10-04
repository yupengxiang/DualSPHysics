"""Explicit Root eight-solver policy; core file bytes, other guards and UUID leases preserved."""
from contextlib import contextmanager
import hashlib
import inspect
import ast
from pathlib import Path

PROFILE = 'root_live_all_idle_uuid_leased_eight_solver_v2'
CORE_SHA = '5098262e26dc5560487760181466b0a93a0e66239e5e54047dce5e761ae67a60'

def choose_gpu(snapshot, leased_uuids, peak_mib):
    excluded = set(leased_uuids) | {row['uuid'] for row in snapshot['processes']}
    by_index = {row['index']: row for row in snapshot['devices']}
    for index in [2, 5, 6, 7, 0, 1, 3, 4]:
        device = by_index.get(index)
        if device is None or device['uuid'] in excluded or device['used_mib'] > 256:
            continue
        if device['total_mib'] - device['used_mib'] < peak_mib * 1.25 + 1024:
            continue
        return device
    raise RuntimeError('no currently idle UUID with sufficient memory and free shared lease')

def make_reservation_checker(runtime):
    observed = hashlib.sha256(Path(runtime.__file__).read_bytes()).hexdigest()
    if observed != CORE_SHA:
        raise RuntimeError('reviewed immutable core source changed')
    original = inspect.getsource(runtime.check_reservation)
    before = 'if len(active) >= 4:'
    after = 'if len(active) >= 8:'
    if original.count(before) != 1:
        raise RuntimeError('expected one reviewed initial solver-cap predicate')
    effective = original.replace(before, after, 1)
    ast.parse(effective)
    local_namespace = {}
    exec(compile(effective, '<Root explicit eight-solver resource policy>', 'exec'), runtime.__dict__, local_namespace)
    return local_namespace['check_reservation'], {
        'core_file_sha256': observed,
        'original_function_sha256': hashlib.sha256(original.encode()).hexdigest(),
        'effective_function_sha256': hashlib.sha256(effective.encode()).hexdigest(),
        'only_change': {'before': before, 'after': after},
        'other_source_bytes_identical': True,
        'core_file_modified': False,
    }

@contextmanager
def install(runtime, request):
    if request.get('root_gpu_selection_profile') != PROFILE or request.get('root_solver_concurrency_cap') != 8:
        raise ValueError('explicit Root eight-solver resource profile required')
    if request.get('launch_owner') != 'root' or request.get('kind') not in {'qualification', 'production'}:
        raise ValueError('profile is reserved for Root native solver requests')
    if request.get('kind') == 'production' and request.get('visual_stage_profile') != 'stage1_visual':
        raise ValueError('production requires the explicit approved visual-stage profile')
    checker, evidence = make_reservation_checker(runtime)
    expected = request.get('root_effective_reservation_function_sha256')
    if expected != evidence['effective_function_sha256']:
        raise ValueError('effective reservation policy source digest does not match request')
    old_choose, old_check = runtime.choose_gpu, runtime.check_reservation
    runtime.choose_gpu, runtime.check_reservation = choose_gpu, checker
    try:
        yield evidence
    finally:
        runtime.choose_gpu, runtime.check_reservation = old_choose, old_check
