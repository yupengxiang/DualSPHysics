"""Explicit Root launch selector; shared strict/runtime bytes and UUID leases stay intact."""
from contextlib import contextmanager

PROFILE='root_live_all_idle_uuid_leased_v1'

def choose_gpu(snapshot,leased_uuids,peak_mib):
    busy={row['uuid'] for row in snapshot['processes']}
    by_index={row['index']:row for row in snapshot['devices']}
    for index in [2,5,6,7,0,1,3,4]:
        device=by_index.get(index)
        if device is None or device['uuid'] in set(leased_uuids)|busy:
            continue
        if device['used_mib']>256:
            continue
        if device['total_mib']-device['used_mib']<peak_mib*1.25+1024:
            continue
        return device
    raise RuntimeError('no currently idle UUID with sufficient memory and free shared lease')

@contextmanager
def install(runtime,request):
    if request.get('root_gpu_selection_profile')!=PROFILE:
        raise ValueError('explicit Root all-idle GPU profile required')
    if request.get('kind') not in {'qualification','production'}:
        raise ValueError('all-idle GPU selector applies only to approved native solver jobs')
    original=runtime.choose_gpu
    runtime.choose_gpu=choose_gpu
    try:
        yield
    finally:
        runtime.choose_gpu=original
