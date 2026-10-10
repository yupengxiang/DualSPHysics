"""Build a portable metadata review bundle; never open scientific payloads.

Absolute producer paths remain unchanged inside original evidence. INDEX maps
them to bundle members. This is a review package, not a raw replay dataset.
"""
from pathlib import Path
import argparse
import collections
import datetime
import hashlib
import json
import os
import subprocess
import zipfile

HERE = Path(__file__).resolve().parent
S = HERE.parents[1]
LAB = S.parents[2]
ROOT = LAB.parent
DATA = Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
ORIGINAL = Path('/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab')
ATTACH = Path('/home/jade/.codex/attachments/78f8d9a8-699b-4362-9b6b-20e6b8a38887')
MAX_BYTES = 10 * 1024 * 1024
PAYLOAD = {'.h5', '.hdf5', '.bi4', '.obi4', '.ibi4', '.vtk', '.vtu', '.jsonl', '.npy', '.npz', '.bin', '.csv', '.dat'}
SAFE = {'.json', '.md', '.py', '.cpp', '.h', '.xml', '.txt', '.log', '.toml', '.yaml', '.yml', '.sh', '.lock'}

def sha(p):
    p = Path(p)
    assert not p.is_symlink() and p.suffix.lower() not in PAYLOAD
    assert p.stat().st_size <= MAX_BYTES, p
    return hashlib.sha256(p.read_bytes()).hexdigest()

def load(p):
    p = Path(p)
    assert p.suffix == '.json'
    sha(p)
    return json.loads(p.read_text())

def write(p, value):
    p.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')

def selection():
    cp = S / 'checkpoints'
    rows = [
        ('E001', S/'CURRENT336.json', 'Frozen 336-case development catalog'),
        ('E002', cp/'CURRENT336_TYPED_LIFECYCLE_AFTER_ROOT307_V4.json', '335 actual saved-mask cases; alias excluded'),
        ('E003', cp/'ROOT434_ACTUAL_H5_CLOSED_CENSUS_V2.json', '78 actual field scans; no scientific qualification'),
        ('E004', cp/'ORIGINAL118_NATIVE_JOIN_AFTER_ROOT717_INDEPENDENT_STRICT_V5_OVERLAY_V1.json', '117 canonical native causes and joins; physical fate unknown'),
        ('E005', cp/'ROOT708_NINE_ACTUAL_GENCASE_COST_SCOPE_V1.json', 'Nine actual GenCase producers'),
        ('E006', cp/'NINE_GENCASE_NATIVE_HEADER_ACTUAL_ROOT_VERIFICATION_709.json', 'Nine actual header probes; original UNKNOWN preserved'),
        ('E007', cp/'NINE_GENCASE_INITIAL_SUPPORT_ACTUAL_ROOT_VERIFICATION_710.json', 'Six support diagnostics succeed, three F3 rows fail'),
        ('E008', cp/'F1_S2_INTEGRAL_OUTPUT_ACTUAL_ROOT_VERIFICATION_371.json', 'Time/output errors not identifiable from asynchronous pair'),
        ('E009', cp/'NATIVE_TYPED_MASS_IMPACT_ACTUAL_ROOT_VERIFICATION_313.json', 'Seventeen actual mass-impact diagnostics'),
        ('E010', cp/'GEOMETRY_SUPPORT_ACTUAL_ROOT_VERIFICATION_316.json', 'Four actual geometry-support diagnostics'),
        ('E011', cp/'SOURCE_CLOSED_DEVELOPMENT_SPLIT_V25_ACTUAL_INDEPENDENT_VERIFICATION_001.json', 'Development role assignment, no hidden-test credit'),
        ('E012', cp/'FINAL_FAMILY_PRODUCT_V27_ACTUAL_BOUNDED_INDEPENDENT_VERIFICATION_001.json', 'Seven bounded metadata family cards'),
        ('E013', cp/'SEVEN_FAMILY_ACTUAL_LABEL_QUALITY_V3_INDEPENDENT_VERIFICATION_001.json', 'Seven source-bound label artifacts; diagnostic scope'),
        ('E014', cp/'SEVEN_FAMILY_QUALITY_EVALUATOR_V2_STRICT_ACTUAL_INDEPENDENT_VERIFICATION_001.json', 'Actual no-model evaluator; diagnostic scope'),
        ('E015', cp/'ROOT242_FAILED_PORTABLE_ACTUAL_METADATA_CLOSURE_V1.json', 'Failed portable V11, fully charged'),
        ('E016', cp/'ROOT242_V13_FAILED_PORTABLE_ACTUAL_METADATA_CLOSURE_V1.json', 'Failed portable V13, fully charged'),
        ('E017', cp/'ROOT242_V14_FAILED_PORTABLE_ACTUAL_METADATA_CLOSURE_V1.json', 'Failed portable V14, original CURRENT open rejected'),
        ('E018', S/'requests/f2-canonical65-executor-source-720-001.json', 'Canonical65 source request only; not launched'),
        ('E019', S/'requests/f2-canonical65-raw-to-typed-primary-prepared-720-001/f2-s1-canonical65-raw-to-typed-phase-request-v1.json', '401 frames/405 native files; deferred worker hashes'),
        ('E020', S/'requests/three-sentinel-initial-support-primary-prepared-718-001/initial-support-package-v3-f3-source-bound.json', 'F3 initial support repair prepared, not executed'),
        ('E021', S/'reference/stage2_three_sentinel_native_header_reparse_v1.py', 'Retained XML v attribute parser source, not executed'),
        ('E022', S/'reference/stage2_three_sentinel_role_mass_comparability_v1.py', 'Role-mass diagnostic source, not executed'),
        ('E023', S/'reference/stage2_three_sentinel_continuous_owner_contract_v1.py', 'Continuous owner source contract, not production verified'),
        ('E024', cp/'F5_SOURCE_CLIP_CONTINUOUS_MASS_ACTUAL_HARDFAIL_ROOT_VERIFICATION_091.json', 'F5 continuous initial mass hard failure'),
        ('E025', cp/'F5_YHALF_DP010_V7_ACTUAL_INITIAL_SUPPORT_ROOT_VERIFICATION_109.json', 'F5 DP010 support diagnostic'),
        ('E026', cp/'F5_YHALF_DP005_V7_ACTUAL_INITIAL_SUPPORT_ROOT_VERIFICATION_110.json', 'F5 DP005 support diagnostic'),
        ('E027', cp/'F5_YZERO_DP005_V10_ACTUAL_GEOMETRY_MASS_HARDFAIL_ROOT_VERIFICATION_124.json', 'F5 geometry repair still fails mass'),
        ('E028', S/'requests/three-sentinel-owner-grid-v3-primary-source-prepared-001/owner-grid-source-manifest-v3.json', 'Three-sentinel original/coarse/fine source bindings'),
        ('E029', cp/'PORTABLE_REAL_CANCEL_AND_V28_ACTUAL_GRAPH_ROOT_VERIFICATION_001.json', 'Manufactured cancellation and actual metadata graph checks'),
        ('E030', S/'review-source/REVIEW_ZH.md', 'Original October 7 review; evidence, not new authorization'),
        ('E031', cp/'ROOT307_LIFECYCLE_SERIAL_ACTUAL_FULL_GOAL_CONTINUATION_V1.json', 'Last actual saved-mask lifecycle batch closure'),
        ('E032', cp/'F3_S2_COMPACT_SPATIAL_LIFECYCLE_COMPARE_V2_ACTUAL_ROOT_VERIFICATION_240.json', 'Real three-grid compact diagnostics, no dynamic error credit'),
        ('E033', cp/'F6_CONTINUOUS_OWNER_GEOMETRY_AUDIT_V1_ACTUAL_ROOT_VERIFICATION_252.json', 'F6 source drawbox owner diagnostic, native support pending'),
        ('E034', HERE/'CLOSEOUT_TESTS.json', 'Closeout source tests; no new production execution'),
        ('E035', HERE/'RESOURCE_SUMMARY.json', 'Frozen resource ledger and historic unresolved rows'),
        ('E036', HERE/'EXECUTION_CUTOFF.json', 'User-directed hold and termination of five idle waiters'),
    ]
    historical = [
        ('E037','F1_COM_OBSERVER_CALIBRATION_V1_ACTUAL_GAP_ROOT_VERIFICATION_202.json'),
        ('E038','F1_NATIVE_SELECTED_OBSERVER_V5_ACTUAL_ROOT_VERIFICATION_207.json'),
        ('E039','OFFICIAL_WRITER_CALIBRATION_V4_ACTUAL_ROOT_VERIFICATION_217.json'),
        ('E040','F1_S2_QUERY1_ENDPOINT_V4_ACTUAL_ROOT_VERIFICATION_234.json'),
        ('E041','F1_S2_DP020_SAME_CFL_SAVEDT_BOUNDED_ACTUAL_ROOT_VERIFICATION_277.json'),
        ('E042','F1_S2_DP020_HALF_CFL_SAVEDT_BOUNDED_ACTUAL_ROOT_VERIFICATION_278.json'),
        ('E043','ROOT279_NATIVE_SCALAR_RECOVERY_ACTUAL_ROOT_VERIFICATION_362.json'),
        ('E044','F3_DP015_COARSE_EXTERNAL_ACTUAL_NATIVE_ROOT_VERIFICATION_133.json'),
        ('E045','F3_DP006_MIDDLE_EXTERNAL_ACTUAL_NATIVE_ROOT_VERIFICATION_162.json'),
        ('E046','F3_DP003_FINE_EXTERNAL_ACTUAL_NATIVE_ROOT_VERIFICATION_170.json'),
        ('E047','F3_FULL836_NATIVE_STREAM_ACTUAL_LIMITED_ROOT_VERIFICATION_150.json'),
        ('E048','F3_MIDDLE_FULL836_NATIVE_COMPACT_ACTUAL_ROOT_VERIFICATION_177.json'),
        ('E049','F3_FINE_FULL836_NATIVE_COMPACT_ACTUAL_ROOT_VERIFICATION_178.json'),
        ('E050','F4_COMMON_TIME_OUTPUT_MISSING_ROWS_ACTUAL_ROOT_VERIFICATION_152.json'),
        ('E051','F6_OWNER_RIGID_METADATA_V1_ACTUAL_ROOT_VERIFICATION_244.json'),
        ('E052','F7_S1_SOURCE_SUPPORT_ACTUAL_SCOPE_ROOT_VERIFICATION_137.json'),
        ('E053','F2_FINE_V9_ACTUAL_SUPPORT_MASS_CONTROL_ROOT_VERIFICATION_089.json'),
    ]
    rows += [(i,cp/name,'Historical actual scientific diagnostic with scope limited by its proof') for i,name in historical]
    for n in range(155,159):
        matches=list(cp.glob(f'F4*ACTUAL_ROOT_VERIFICATION_{n}.json'))
        assert len(matches)==1
        rows.append((f'E{n-101:03d}',matches[0],'F4 native missing-frame diagnostic only'))
    assert all(p.is_file() for _, p, _ in rows)
    return rows

def validate_actual():
    census = load(S/'checkpoints/ROOT434_ACTUAL_H5_CLOSED_CENSUS_V2.json')
    rows = census['base_actual_rows'] + census['additional_actual_rows']
    assert len(rows) == census['actual_canonical_field_cases_total'] == 78
    assert len({(v['family_id'], v['physical_case_id']) for v in rows}) == 78
    assert census['remaining_executable_count'] == 256
    assert census['missing_case_manifest_unknown_count'] == census['alias_unknown_count'] == 1
    checked = []
    def check(p, expected_sha=None):
        p = Path(p)
        if expected_sha: assert sha(p) == expected_sha, p
        v = load(p)
        assert v['parent_reservation_released'] is True
        assert v.get('parent_actual_prepost_content_hashes_equal') is True
        assert v.get('goal_complete') is False
        assert v.get('repeat_fee_idempotent') is True
        receipt = Path(v['receipt'])
        assert sha(receipt) == v['receipt_sha256'], receipt
        rec = load(receipt)
        assert rec['status'] == 'completed' and rec['returncode'] == 0
        assert rec['input_hashes_at_launch'] == rec['input_hashes_after_run']
        assert sha(v['request']) == v['request_sha256'] == rec['request_sha256']
        assert sha(v['report']) == v['report_sha256']
        for k in ['systemd_evidence', 'terminal_cpu_reconciliation']:
            assert sha(v[k]) == v[k+'_sha256']
        checked.append({'path':str(p), 'sha256':sha(p), 'full_cpu_seconds':v['full_systemd_cpu_seconds']})
        return v
    for row in rows:
        v = check(row['actual_proof']['path'], row['actual_proof']['sha256'])
        assert 'FIELD' in v['status'] and v['scientific_Q_credit'] == 0
    for n in range(711, 718):
        v = check(S/f'checkpoints/GENERIC_NATIVE_JOIN_V6_ACTUAL_ROOT_VERIFICATION_{n}.json')
        assert v['status'] == 'VERIFIED_ACTUAL_V6_GENERIC_NATIVE_CASE_JOINS_NO_PHYSICAL_Q'
    native = load(S/'checkpoints/ORIGINAL118_NATIVE_JOIN_AFTER_ROOT717_INDEPENDENT_STRICT_V5_OVERLAY_V1.json')
    assert native['native_cause_bound_per_fluid_id_cases'] == 117
    assert native['actual_typed_native_saved_frame_join_physical_cases'] == 117
    assert len(native['unresolved_alias_case_ids']) == 1
    assert all(native['claim_boundary'][k] == 'UNKNOWN' for k in ['QI','QN','QE','legal_flux','physical_fate'])
    for n, name in [(709, 'NINE_GENCASE_NATIVE_HEADER'), (710, 'NINE_GENCASE_INITIAL_SUPPORT'), (371, 'F1_S2_INTEGRAL_OUTPUT')]:
        check(S/f'checkpoints/{name}_ACTUAL_ROOT_VERIFICATION_{n}.json')
    ledger = load(HERE/'RESOURCE_LEDGER_SNAPSHOT.json')
    assert not ledger['reservations']
    for row in checked:
        v = load(row['path'])
        assert any(c['id'] == v['parent_charge']['id'] for c in ledger['charges'])
    output = {'schema':'ds02.stage2.closeout-metadata-validation.v1',
        'status':'PASS_BOUNDED_METADATA_CLOSURE_NO_PAYLOAD_REPLAY',
        'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'field_case_count':78, 'field_family_counts':dict(collections.Counter(v['family_id'] for v in rows)),
        'native_canonical_cause_cases':117, 'native_canonical_join_cases':117,
        'closed_proofs':checked, 'new_payload_content_opened':False,
        'scientific_qualification_revalidated':False,
        'important_limit':'Verifies report/receipt/fee bytes and recorded hash equality, not current raw/H5 contents or physical accuracy.'}
    existing=HERE/'CLOSEOUT_VALIDATION.json'
    if existing.exists():
        previous=load(existing)
        assert {k:v for k,v in previous.items() if k!='utc'} == {k:v for k,v in output.items() if k!='utc'}
        output=previous
    else:
        write(existing,output)
    return output

def references(value):
    if isinstance(value, dict):
        for k, v in value.items():
            if isinstance(k, str) and k.startswith('/home/jade/'):
                yield k
            yield from references(v)
    elif isinstance(value, list):
        for v in value: yield from references(v)
    elif isinstance(value, str) and value.startswith('/home/jade/') and '\n' not in value:
        yield value

def expected_references(value):
    if isinstance(value,dict):
        if isinstance(value.get('path'),str) and isinstance(value.get('sha256'),str):
            yield value['path'],value['sha256']
        for k,v in value.items():
            if isinstance(v,str) and v.startswith('/home/jade/') and isinstance(value.get(k+'_sha256'),str):
                yield v,value[k+'_sha256']
            yield from expected_references(v)
    elif isinstance(value,list):
        for v in value: yield from expected_references(v)

def member(p):
    roots = [(ROOT,'repo'), (DATA,'local-data'), (ORIGINAL,'original-source'), (ATTACH,'original-review-attachments')]
    for base, name in roots:
        try: return name+'/'+p.relative_to(base).as_posix()
        except ValueError: pass
    return 'other-local/'+hashlib.sha256(str(p).encode()).hexdigest()[:12]+'/'+p.name

def build(output):
    verification = validate_actual()
    chosen = selection()
    files, excluded, queue, seen = {}, {}, [], set()
    for _, p, _ in chosen: queue.append((p, 0))
    for p in HERE.iterdir():
        if p.is_file() and p.name not in {'EVIDENCE_INDEX.json','BUNDLE_BUILD_RESULT.json'}:
            queue.append((p, 2))
    for p in (S/'review-source').rglob('*'):
        if p.is_file(): queue.append((p, 2))
    for name in ['GOAL_STAGE2_ZH.md','GOAL_ZH.md']:
        queue.append((S.parent/name,2))
    queue += [(ROOT/'AGENTS.md',2), (ROOT/'LICENSE',2)]
    # New joins and all actual field report/receipt/request bindings are included.
    for n in range(711,718):
        for pattern in [f'*{n}*.json']:
            for p in (S/'checkpoints').glob(pattern): queue.append((p,0))
    for p in ATTACH.iterdir():
        if p.suffix in ('.md','.json'): queue.append((p,2))
    while queue:
        p, depth = queue.pop(0)
        p = Path(p)
        if str(p) in seen: continue
        seen.add(str(p))
        if not p.is_file():
            if p.suffix in SAFE: excluded[str(p)] = {'reason':'LOCAL_REFERENCE_NOT_ACCESSIBLE_OR_NOT_FILE'}
            continue
        st = p.stat()
        if p.is_symlink() or p.suffix.lower() in PAYLOAD or st.st_size > MAX_BYTES:
            excluded[str(p)] = {'reason':'DEFERRED_PAYLOAD_SYMLINK_OR_OVER10MIB_NOT_OPENED','bytes':st.st_size}
            continue
        if p.suffix not in SAFE and p.name not in {'LICENSE','SHA256SUMS'}: continue
        # Do not read arbitrary system/account files discovered in a command string.
        if not any(str(p).startswith(str(base)+'/') for base in [ROOT, DATA, ORIGINAL, ATTACH, Path('/home/jade/.codex/worktrees/ds-data-02-stage2-reference/DualSPHysics'),Path('/home/jade/.codex/worktrees/ds-data-02-stage2-consumers/DualSPHysics')]):
            continue
        files[str(p)] = {'original_path':str(p), 'member':member(p), 'bytes':st.st_size, 'sha256':sha(p), 'role':'metadata_or_source_only'}
        if depth < 2 and p.suffix == '.json':
            queue += [(Path(v),depth+1) for v in references(load(p))]
    mismatches=[]
    for record in files.values():
        p=Path(record['original_path'])
        if p.suffix!='.json':continue
        for target,expected in expected_references(load(p)):
            if target in files and len(expected)==64 and files[target]['sha256']!=expected:
                mismatches.append({'referrer':str(p),'path':target,'recorded_sha256':expected,
                    'bundled_current_sha256':files[target]['sha256'],
                    'scope':'historical/context reference mismatch; not silently rebound'})
    index = {'schema':'ds02.stage2.cloud-review-evidence-index.v1',
        'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'evidence_source_commit':load(HERE/'GIT_PRE_REPORT_INVENTORY.json')['evidence_source_commit'],
        'bundle_build_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'root_payload_content_opened':False,
        'portable_raw_replay_bundle':False,
        'coverage_limit':'Bounded metadata and source closure to depth two; excludes native/H5/JSONL/scientific tables and missing local refs. Cloud reviewer cannot independently verify original arrays from this ZIP.',
        'key_evidence':[{'id':i,'description':desc,**files[str(p)]} for i,p,desc in chosen],
        'files':list(files.values()), 'excluded_references':[{'path':p,**v} for p,v in sorted(excluded.items())],
        'historical_context_reference_hash_mismatches':mismatches,
        'metadata_validation_status':verification['status']}
    write(HERE/'EVIDENCE_INDEX.json',index)
    assert not output.exists(), output
    output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        z.write(HERE/'EVIDENCE_INDEX.json','EVIDENCE_INDEX.json')
        for v in sorted(files.values(),key=lambda x:x['member']):
            p=Path(v['original_path']); assert sha(p)==v['sha256'];z.write(p,v['member'])
        for name in ['SUMMARY_REPORT_ZH.md','REVIEW_REQUEST_ZH.md','START_HERE_ZH.md','verify_bundle.py']:
            z.write(HERE/name,name)
    with zipfile.ZipFile(output) as z:
        assert z.testzip() is None
        for v in files.values():
            assert hashlib.sha256(z.read(v['member'])).hexdigest()==v['sha256']
    # The outer ZIP is an export artifact, never a scientific source payload.
    h=hashlib.sha256()
    with output.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    digest=h.hexdigest()
    result={'schema':'ds02.stage2.cloud-review-bundle-export.v1','path':str(output),
        'bytes':output.stat().st_size,'sha256':digest,'file_count':len(files),
        'excluded_reference_count':len(excluded),'crc_and_all_member_sha_verified':True,
        'git_commit_at_build':index['bundle_build_commit'],'scientific_payload_included':False,
        'cloud_review_performed':False}
    write(HERE/'BUNDLE_BUILD_RESULT.json',result)
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--validate-only',action='store_true')
    parser.add_argument('--output',type=Path)
    a=parser.parse_args()
    if a.validate_only:
        v=validate_actual();print(json.dumps({k:v[k] for k in ['status','field_case_count','field_family_counts','native_canonical_join_cases']}))
    else:
        assert a.output is not None
        build(a.output)
