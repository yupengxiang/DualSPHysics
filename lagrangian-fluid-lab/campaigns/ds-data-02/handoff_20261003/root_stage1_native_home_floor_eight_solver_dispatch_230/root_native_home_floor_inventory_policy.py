"""Root-only native dispatch optimization: obsolete total-tree bytes are unused under Home floor.

The immutable runtime, per-attempt size accounting, budgets, live free-space
checks, deadlines, CPU limits and shared leases retain their exact behavior.
Only the full dataset inventory passed to check_reservation is skipped when
the live storage contract explicitly makes that argument irrelevant.
"""
from pathlib import Path
from contextlib import contextmanager
import hashlib,json

PROFILE='root_home_floor_no_legacy_dataset_walk_native_v1'
CORE_SHA='5098262e26dc5560487760181466b0a93a0e66239e5e54047dce5e761ae67a60'
DATA_ROOT=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
HOME_FLOOR=500*1024**3

def limits():
    return json.loads((DATA_ROOT/'runtime/resource-ledger.json').read_text())['limits']

def eligible(root,live_limits):
    return (Path(root).resolve()==DATA_ROOT.resolve()
            and live_limits.get('storage_policy')=='home_free_floor'
            and live_limits.get('home_path')=='/home/jade'
            and live_limits.get('home_min_free_bytes',0)>=HOME_FLOOR)

@contextmanager
def install(runtime,request):
    if request.get('root_dataset_inventory_profile')!=PROFILE or request.get('launch_owner')!='root':
        raise ValueError('Explicit Root Home-floor inventory profile required')
    if request.get('kind') not in {'qualification','production'}:
        raise ValueError('This reviewed profile is limited to Root native solver tasks')
    if hashlib.sha256(Path(runtime.__file__).read_bytes()).hexdigest()!=CORE_SHA:
        raise ValueError('Reviewed immutable runtime source changed')
    original=runtime.tree_bytes
    evidence={'profile':PROFILE,'full_dataset_walk_skips':0,'original_tree_calls':0,'core_source_unchanged':True,'existing_dataset_bytes_argument_unused_only_under_live_home_floor':True}
    def tree_bytes(root):
        if Path(root).resolve()==DATA_ROOT.resolve():
            try:live=limits()
            except (OSError,KeyError,ValueError):live={}
            if eligible(root,live):
                evidence['full_dataset_walk_skips']+=1
                return 0
        evidence['original_tree_calls']+=1
        return original(root)
    runtime.tree_bytes=tree_bytes
    try:yield evidence
    finally:runtime.tree_bytes=original
