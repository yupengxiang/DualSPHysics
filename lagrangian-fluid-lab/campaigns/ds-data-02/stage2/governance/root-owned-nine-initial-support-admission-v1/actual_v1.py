"""Admit the actual nine-product support diagnostic after ROOT709.

Only the reserved child reads production VTK/BI4. Bounded report closure
counts failed diagnostics explicitly and never upgrades native mass or Q.
"""
from pathlib import Path
import argparse
import datetime
import fcntl
import importlib
import importlib.util
import json
import os
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
S = HERE.parents[1]
LAB = S.parents[2]
D = Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
PY = '/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python'
PACK = S/'requests/three-sentinel-initial-support-primary-prepared-710-001'
SOURCE = PACK/'initial-support-request-v2-root709-bound.json'
MANIFEST = PACK/'initial-support-manifest-v2-root709-bound.json'
QP = S/'requests/three-sentinel-initial-support-v2-v10-root-forward-710-001.json'
PILOT = S/'requests/scientific-field-h5-v3-v10-actual-pilot-root-346-001.json'
INDEPENDENT = S/'checkpoints/ROOT710_NINE_INITIAL_SUPPORT_SOURCE_VERIFICATION_V5.json'
UNIT = 'ds02-three-sentinel-initial-support-v2-root-710'
spec = importlib.util.spec_from_file_location('support_bounded_helpers', S/'governance/root-owned-scientific-field-pilot-admission-v1/serial_v4.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
sha, load, ref, new, state = helper.sha, helper.load, helper.ref, helper.new, helper.state

def seal():
    q, m, pilot = load(SOURCE), load(MANIFEST), load(PILOT)
    independent = load(INDEPENDENT)
    assert independent['status'] == 'READY_FOR_PARENT_GUARDED_OWNER_GRID_INITIAL_SUPPORT_V2'
    assert not independent['errors'] and not independent['waiting']
    assert independent['request']['sha256'] == sha(SOURCE)
    assert independent['manifest']['sha256'] == sha(MANIFEST)
    assert len(m['cases']) == 9 and len(q['deferred_input_records']) == 36
    assert not q['source_closure_missing']
    for p, h in q['input_sha256'].items():
        assert sha(p) == h, p
    q.update(attempt_id='root710-three-sentinel-initial-support-v2-actual-001',
        cwd=str(LAB), worktree_root=str(LAB.parent), omp_threads=1, cpu_threads=1,
        max_wall_seconds=900, max_memory_bytes=4294967296, estimated_peak_memory_bytes=4294967296,
        estimated_storage_bytes=536870912, runtime_binding=pilot['runtime_binding'],
        interpreter_binding=pilot['interpreter_binding'], execution_allowed=True, launch_disabled=False, source_only=False)
    q['command'].insert(1, '-B')
    q['manifest_contract'] = ref(MANIFEST)
    q['storage_scope'] = {'schema':'ds02.storage-scope.v2', 'estimated_storage_bytes':536870912,
        'home_storage_bytes':536870912, 'external_storage_bytes':0, 'external_headroom_bytes':0,
        'home_headroom_bytes':134217728, 'worker_scratch_bytes':402653184,
        'source_copy_bytes':0, 'read_io_excluded_from_storage':True}
    extras = [Path(__file__), SOURCE, MANIFEST, INDEPENDENT, PILOT,
        S/'governance/root-owned-scientific-field-pilot-admission-v1/serial_v4.py',
        S/'governance/root-owned-lifecycle-continuation-v1/root_common_verification.py',
        S/'governance/root-owned-lifecycle-continuation-v1/root_cpu_verification_footer.py',
        LAB/'scripts/ds_data02_stage2_terminal_cpu_delta_reconciler_v6.py',
        LAB/'scripts/ds_data02_batch_runner.py', Path(pilot['interpreter_binding']['resolved_path'])]
    extras += [Path(v['path']) for v in q['runtime_binding'].values()]
    q['input_files'] = list(dict.fromkeys(q['input_files']+list(map(str, extras))))
    q['input_hashes'] = q['input_sha256'] = {p:sha(p) for p in q['input_files']}
    for r in q['deferred_input_records']:
        p = Path(r['path'])
        assert p.is_file() and not p.is_symlink() and str(p) not in q['input_files']
        st, expected = p.stat(), r.get('stat') or r.get('stat_after')
        assert expected is not None, r
        normalized = {'device':expected.get('device',expected.get('st_dev')),
            'inode':expected.get('inode',expected.get('st_ino')), 'bytes':expected['bytes'],
            'mtime_ns':expected['mtime_ns'], 'ctime_ns':expected['ctime_ns']}
        assert {'device':st.st_dev,'inode':st.st_ino,'bytes':st.st_size,
                'mtime_ns':st.st_mtime_ns,'ctime_ns':st.st_ctime_ns} == normalized, r
    q['root_nine_initial_support_admission'] = {'source_request':ref(SOURCE),
        'manifest':ref(MANIFEST), 'source_verification':ref(INDEPENDENT),
        'root_product_content_read':False, 'actual_product_count':36,
        'scientific_Q_credit':0, 'native_mass':'UNKNOWN', 'continuous_owner':'UNKNOWN'}
    sys.path.insert(0, str(LAB/'scripts'))
    from ds_data02_runtime_v8 import _light_validate
    _light_validate(q, data_root=D)
    new(QP,q)
    print(json.dumps({'event':'SEALED_NINE_ACTUAL_INITIAL_SUPPORT_PARENT', 'request':ref(QP),
        'deferred_product_bytes':sum(r['stat']['bytes'] for r in q['deferred_input_records']),
        'root_product_read':False}), flush=True)

def launch():
    q, ledger = load(QP), load(D/'runtime/resource-ledger.json')
    assert not ledger['reservations']
    assert datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(seconds=990) < datetime.datetime.fromisoformat(ledger['deadline_utc'])
    assert sum(r.get('cpu_core_seconds',0) for r in ledger['charges'])+900 < ledger['limits']['cpu_core_seconds']
    disk = os.statvfs(ledger['limits']['home_path'])
    assert disk.f_bavail*disk.f_frsize-q['estimated_storage_bytes'] >= ledger['limits']['home_min_free_bytes']
    assert not (D/'families'/q['family_id']/q['case_id']/q['attempt_id']).exists()
    for p,h in q['input_sha256'].items(): assert sha(p)==h,p
    code = 'import sys,os,json;sys.path.insert(0,'+repr(str(LAB/'scripts'))+');from ds_data02_runtime_v10_git_bound import run_request;r=run_request('+repr(str(QP))+',data_root='+repr(str(D))+',parent_pid=os.getppid());print(json.dumps(r));raise SystemExit(0 if r["status"]=="completed" else 1)'
    argv = ['systemd-run','--user','--unit='+UNIT,'--working-directory='+str(LAB),
        '--property=Type=exec','--property=RemainAfterExit=yes','--property=RuntimeMaxSec=960',
        '--property=TimeoutStopSec=45','--property=KillMode=mixed','--property=CPUAccounting=yes',
        '--property=MemoryAccounting=yes','--property=MemoryMax=4294967296']
    argv += ['--setenv='+k+'=1' for k in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS']]
    subprocess.run(argv+[PY,'-B','-I','-c',code],check=True)
    while True:
        u = state(UNIT)
        if u['SubState']!='running': break
        print(json.dumps({'event':'RUNNING_NINE_ACTUAL_INITIAL_SUPPORT_PARENT',
            'cpu_seconds':int(u['CPUUsageNSec'])/1e9}),flush=True)
        time.sleep(10)
    assert u['SubState']=='exited' and u['MainPID']=='0' and u['Result']=='success',u

def verify():
    common = S/'governance/root-owned-lifecycle-continuation-v1/root_common_verification.py'
    ctx = {'__file__':str(common),'__name__':'root_actual_nine_initial_support_scope'}
    exec(common.read_text(),ctx)
    ctx.update(sha=sha,load=load)
    q,b,r,p = ctx['common'](QP)
    report = b/'report/initial-support-v2.json'
    actual, manifest = load(report), load(MANIFEST)
    assert actual['schema']=='ds02.stage2.three-sentinel-owner-grid-initial-support-audit.v2'
    assert actual['status']=='COMPLETE_PARTIAL_OWNER_GRID_INITIAL_SUPPORT_V2_HEADER_709_BOUND'
    assert actual['manifest']['path']==str(MANIFEST) and actual['manifest']['sha256']==sha(MANIFEST)
    assert actual['header_binding']==manifest['header_binding'] and actual['xml_fallback'] is False
    assert actual['scientific_scope']['scientific_credit']==0
    assert all(actual['scientific_scope'][k]=='UNKNOWN' for k in ['QI','QN','QE','native_mass','continuous_owner'])
    by_key = {v['row_key']:v for v in actual['cases']}
    assert len(by_key)==len(actual['cases'])==9
    failed=[]
    for source in manifest['cases']:
        key = source['sentinel_id']+':'+source['grid_label']
        v = by_key[key]
        if v['status']=='FAILED_INITIAL_SUPPORT_DIAGNOSTIC':
            assert isinstance(v['reason'],str)
            failed.append({'row_key':key,'reason':v['reason']})
            continue
        assert v['status']=='PASS_INITIAL_SUPPORT_DIAGNOSTIC'
        for role in ['fluid_vtk','bound_vtk','native_bi4']:
            guard = v['deferred_payload_guards'][role]
            assert guard['path']==source[role]['path']
            assert len(guard['sha256_pre'])==64 and guard['sha256_pre']==guard['sha256_post']
            assert guard['stat_pre']==guard['stat_post']
        assert v['native_header']['status']=='UNKNOWN_NATIVE_HEADER_FIELDS_NOT_EXPOSED_BY_DECODER'
        assert v['native_header']['source_sha256']==v['deferred_payload_guards']['native_bi4']['sha256_pre']
    counts = actual['case_counts']
    assert counts['FAILED']==len(failed) and counts['PASS_OR_DIAGNOSTIC']==9-len(failed)
    p.update(status='VERIFIED_ACTUAL_NINE_INITIAL_SUPPORT_DIAGNOSTIC_METADATA_CLOSURE_NO_SCIENTIFIC_Q',
        report=str(report),report_sha256=sha(report),manifest=str(MANIFEST),manifest_sha256=sha(MANIFEST),
        source_request=ref(SOURCE),source_verification=ref(INDEPENDENT),
        initial_support_diagnostic_success_count=9-len(failed),initial_support_diagnostic_failed_rows=failed,
        actual_diagnostic_case_count=9,root_product_content_read=False,
        continuous_owner_equivalence='UNKNOWN',native_mass='UNKNOWN',scientific_Q_credit=0)
    footer = (S/'governance/root-owned-lifecycle-continuation-v1/root_cpu_verification_footer.py').read_text().replace(
        '1073741824',str(q['max_memory_bytes'])).replace('F7_S1_SOURCE_SUPPORT_ACTUAL_SCOPE_ROOT_VERIFICATION_137.json',
        'NINE_GENCASE_INITIAL_SUPPORT_ACTUAL_ROOT_VERIFICATION_710.json')
    ctx.update(q=q,b=b,r=r,p=p,qp=QP,num='710',name='three-sentinel-initial-support-v2',subprocess=subprocess,importlib=importlib)
    exec(footer,ctx)
    assert state(UNIT)['SubState']=='dead'
    proof = S/'checkpoints/NINE_GENCASE_INITIAL_SUPPORT_ACTUAL_ROOT_VERIFICATION_710.json'
    new(S/'checkpoints/ROOT710_ACTUAL_NINE_INITIAL_SUPPORT_HANDOFF_V1.json',{
        'schema':'ds02.stage2.root-nine-initial-support-actual-handoff.v1','actual_proof':ref(proof),
        'successful_support_diagnostics':9-len(failed),'failed_support_diagnostics':failed,
        'native_mass':'UNKNOWN','continuous_owner':'UNKNOWN','scientific_Q_credit':0,
        'goal_complete':False,'goal_status':'ACTIVE_FULL_SEVEN_ITEMS'})

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['prepare','run','verify'])
    args=parser.parse_args()
    if args.action=='prepare': seal()
    elif args.action=='verify': verify()
    else:
        with (D/'runtime/root-owned-nine-initial-support-v1.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            launch()
            verify()
