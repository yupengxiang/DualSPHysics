"""Close one actual V6 native join parent using frozen scientific consumers."""
from pathlib import Path
import argparse
import hashlib
import importlib
import json
import subprocess
import sys

HERE = Path(__file__).resolve().parent
LAB = HERE.parents[4]
S = LAB / 'campaigns/ds-data-02/stage2'
COUNTS = {312: 7, 315: 8, 317: 8, 318: 8, 319: 8, 320: 8, 321: 6}


def read(path):
    path = Path(path)
    assert path.suffix.lower() not in {'.h5', '.hdf5', '.bi4', '.obi4', '.ibi4', '.vtk', '.vtu', '.jsonl'}
    before = path.stat()
    assert path.is_file() and before.st_size <= 10485760
    raw = path.read_bytes()
    after = path.stat()
    assert (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
    return raw


def sha(path):
    return hashlib.sha256(read(path)).hexdigest()


def load(path):
    assert Path(path).suffix.lower() == '.json'
    return json.loads(read(path))


def new(path, value):
    assert not path.exists()
    raw = (json.dumps(value, indent=2, ensure_ascii=False) + '\n').encode()
    assert len(raw) <= 10485760
    path.write_bytes(raw)


def main(num, request_path, scope_path, plan_path):
    assert num in COUNTS
    common_path = S / 'governance/root-owned-lifecycle-continuation-v1/root_common_verification.py'
    assert Path.cwd() == LAB
    assert (Path('/home/jade/Projects/DualSPHysics-data/ds-data-02/runtime/resource-ledger.json')).stat().st_size <= 10485760
    context = {'__file__': str(common_path), '__name__': 'root_v6_join_actual_v1'}
    exec(read(common_path).decode(), context)
    context.update(sha=sha, load=load)
    q, base, receipt, proof = context['common'](request_path)
    for key, path in [('fresh_native_admission_scope', scope_path), ('fresh_lifecycle_terminal_plan', plan_path)]:
        assert q[key]['path'] == str(path) and q[key]['sha256'] == sha(path)
    assert len(q['physical_case_ids']) == COUNTS[num]
    manifest = Path(q['manifest_contract']['path'])
    assert sha(manifest) == q['manifest_contract']['sha256']
    report = base / ('root312-f4-native-extract-v2.json' if num == 312 else 'generic-native-extract.json')
    sys.path.insert(0, str(LAB / 'scripts'))
    import ds_data02_stage2_verify_generic_native_join_v6 as verifier
    import ds_data02_stage2_normalize_v6_verified_native_join_v2 as normalizer
    verified = verifier.verify(scope_path, manifest, request_path, report, plan_path, S / 'CURRENT336.json')
    assert verified['status'] == 'VERIFIED_GENERIC_OR_ROOT312_WORKER_OUTPUT_ALL_CASES'
    assert not verified['failures'] and len(verified['case_verifications']) == COUNTS[num]
    for key, path in [('request', request_path), ('manifest', manifest), ('report', report)]:
        assert verified[key]['path'] == str(path) and verified[key]['sha256'] == sha(path)
    assert not any(verified['read_policy'][k] for k in ['typed_jsonl_content_opened', 'h5_content_opened', 'bi4_content_opened', 'obi4_content_opened'])
    for row in verified['case_verifications']:
        assert Path(row['case_output']['path']).is_relative_to(base)
        assert Path(row['native_csv']['path']).is_relative_to(base)
    proof.update(report=str(report), report_sha256=sha(report), manifest=str(manifest), manifest_sha256=sha(manifest))
    terminal_refs, terminal_docs = normalizer._load_terminal_refs(proof)
    identity = normalizer._load_v6_identity(verified, terminal_refs, terminal_docs)
    rows = normalizer.v1.normalize_rows(verified)
    normalizer._validate_case_output_roots(verified, rows, identity['output_root'])
    assert {r['physical_case_id'] for r in rows} == set(q['physical_case_ids'])
    independent = S / f'checkpoints/ROOT{num}_NATIVE_JOIN_INDEPENDENT_VERIFICATION_V6.json'
    new(independent, verified)
    proof.update(status='VERIFIED_ACTUAL_V6_GENERIC_NATIVE_CASE_JOINS_NO_PHYSICAL_Q',
                 report=str(report), report_sha256=sha(report), manifest=str(manifest), manifest_sha256=sha(manifest),
                 case_verifications=rows, actual_completed_physical_cases=len(rows), failed_physical_cases=0, failed_cases=[],
                 independent_verification=str(independent), independent_verification_sha256=sha(independent),
                 independent_verifier=str(Path(verifier.__file__).resolve()), independent_verifier_sha256=sha(verifier.__file__),
                 row_normalizer=str(Path(normalizer.__file__).resolve()), row_normalizer_sha256=sha(normalizer.__file__),
                 v6_producer_identity={'request': identity['refs']['request'], 'manifest': identity['refs']['manifest'],
                                      'report': identity['refs']['report'], 'case_ids': identity['case_ids'],
                                      'case_outputs_under_terminal_output_root': True},
                 fresh_native_admission_scope=q['fresh_native_admission_scope'],
                 fresh_lifecycle_terminal_plan=q['fresh_lifecycle_terminal_plan'],
                 new_original118_cause_bound_physical_cases=0, new_original118_typed_native_joins=len(rows),
                 root_deferred_payload_content_read=False, native_cause_credit='DEFERRED_TO_STRICT_ROLLING_SCOPE_ADMISSION',
                 physical_fate_flux_dynamics='UNKNOWN', next='Admit exact completed rows against strict CURRENT336 alias-aware rolling scope; full goal ACTIVE')
    footer = read(S / 'governance/root-owned-lifecycle-continuation-v1/root_cpu_verification_footer.py').decode()
    footer = footer.replace('1073741824', str(q['max_memory_bytes'])).replace('F7_S1_SOURCE_SUPPORT_ACTUAL_SCOPE_ROOT_VERIFICATION_137.json', f'GENERIC_NATIVE_JOIN_V6_ACTUAL_ROOT_VERIFICATION_{num}.json')
    context.update(q=q, b=base, r=receipt, p=proof, qp=request_path, num=str(num), name='generic-native-join-v6', subprocess=subprocess, importlib=importlib)
    exec(footer, context)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('namespace', type=int)
    parser.add_argument('--request', type=Path, required=True)
    parser.add_argument('--scope', type=Path, required=True)
    parser.add_argument('--plan', type=Path, required=True)
    args = parser.parse_args()
    main(args.namespace, args.request.absolute(), args.scope.absolute(), args.plan.absolute())
