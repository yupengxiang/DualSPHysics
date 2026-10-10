"""Fresh GenCase requests, preserving the old ROOT321 scheduling queue.

Uses the scientific source/control preflight already implemented in V2. Only
bounded control metadata and stat-only forcing records are touched by ROOT.
The independent route is scheduling evidence and confers no native/owner Q.
"""
from pathlib import Path
import importlib.util

HERE=Path(__file__).resolve().parent
S=HERE.parents[1];LAB=S.parents[2]
D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
OLD=S/'governance/root-owned-owner-grid-admission-v2'
ROUTE=S/'checkpoints/ROOT_NINE_GENCASE_INDEPENDENT_SOURCE_DEPENDENCY_V2.json'

def module(path,name):
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value)
    return value

def prepare(source,namespace,predecessor,extras=(),*,dry_run=False):
    old=module(OLD/'prepare_actual_gencase_v2.py','independent_owner_preparation_v2')
    admission=old.module(S/'governance/root-owned-native-admission-v1/continue_after_serial_v1.py','independent_owner_bounded_metadata')
    route=admission.load(ROUTE)
    assert route['status']=='SOURCE_ROUTE_READY_FOR_PARENT_AFTER_FIELDCASE_RESOURCE_RELEASE'
    assert route['dependency_audit']['old_waiter_is_serial_scheduling_only'] is True
    assert route['dependency_audit']['producer_input_stale_barrier_markers']==[]
    assert 700<=namespace<=708
    source_ref=admission.ref(source)
    assert source_ref in [{'path':r['request']['path'],'sha256':r['request']['sha256']} for r in route['producer_requests']]
    preview=old.prepare(source,namespace,predecessor,dry_run=True)
    q=preview['request_preview'];before=q['output_root']
    old_destination=S/f'requests/owner-grid-gencase-v3-root-forward-{namespace}-after321-001.json'
    destination=S/f'requests/owner-grid-gencase-independent-v1-root-forward-{namespace}-001.json'
    assert not destination.exists()
    q['attempt_id']=f'root{namespace}-{q["sentinel_id"].lower()}-{q["grid_label"]}-gencase-independent-v1-001'
    final=q['attempt_id']+'-root-forward-030-001'
    output=D/'families'/q['family_id']/q['case_id']/final
    assert not output.exists()
    q['command']=[arg.replace(str(old_destination),str(destination)).replace(before,str(output)) for arg in q['command']]
    q.update(source_only=False,launch_disabled=False,execution_allowed=True,
        status='READY_ROOT_OWNER_GRID_V3_EXACT_RUNTIME_CLOSURE',output_root=str(output),planned_output_root=str(output))
    q['output']['root']=str(output);q['output']['prefix']=str(output/'generated')
    for product in q['output']['products'].values():product['path']=product['path'].replace(before,str(output))
    q['gencase_receipt_contract']['output_root']=str(output)
    q['root_independent_owner_admission']={'source_dependency_route':admission.ref(ROUTE),
        'actual_predecessor':admission.ref(predecessor),'old_native321_barrier_consumed':False,
        'old_queue_namespaces_preserved':list(range(337,346)),
        'actual_independent_namespace':namespace,'root_native_payload_content_read':False,
        'scientific_Q_credit':0}
    if dry_run:return {'request_preview':q,'root_stat_only_deferred':preview['root_stat_only_deferred']}
    forward=S/'governance/root-owned-lifecycle-continuation-v1/root_forward_metadata.py'
    ctx={'__file__':str(forward),'__name__':'independent_owner_forward'}
    exec(forward.read_text(),ctx);ctx['sha']=admission.sha
    runtime_extras=[LAB/'scripts'/name for name in [
        'ds_data02_runtime_v10_git_bound.py','ds_data02_runtime_v9_git_bound.py',
        'ds_data02_git_launch_state_v1.py','ds_data02_git_launch_state_v2.py','ds_data02_git_launch_state_v3.py',
        'ds_data02_stage2_dispatch_v9.py','ds_data02_strict_dispatch_v9.py']]
    ctx['write'](q,source,destination.name,
        extra=[Path(__file__),OLD/'prepare_actual_gencase_v2.py',
            S/'governance/root-owned-owner-grid-admission-v1/prepare_actual_gencase_v1.py',
            ROUTE,predecessor,*runtime_extras,*extras],deferred=preview['root_stat_only_deferred'])
    actual=admission.load(destination)
    assert actual['attempt_id']==final and actual['output_root']==str(output)
    return destination
