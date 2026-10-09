"""Independent actual F6 initial-support record validation and parent CPU close."""
from pathlib import Path
import hashlib
import importlib
import subprocess
import sys

HERE = Path(__file__).resolve().parent
LAB = HERE.parents[4]
S = LAB / 'campaigns/ds-data-02/stage2'
PYTHON = '/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python'


def sha(path):
    path = Path(path)
    assert path.suffix.lower() not in {'.h5','.hdf5','.bi4','.obi4','.ibi4','.vtk','.vtu','.jsonl'} and path.stat().st_size <= 10485760
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    qp = Path(sys.argv[1]).absolute()
    common = S / 'governance/root-owned-lifecycle-continuation-v1/root_common_verification.py'
    context = {'__file__':str(common),'__name__':'root276_actual_support_v8'}
    exec(common.read_text(),context); context['sha'] = sha
    q, base, receipt, proof = context['common'](qp)
    manifest = Path(q['manifest_contract']['path']); assert sha(manifest) == q['manifest_contract']['sha256']
    report = base / 'observer/f6_initial_native_support_audit_v8.json'
    verifier = S / 'reference/stage2_f6_initial_native_support_verify_v4.py'
    independent = S / 'checkpoints/ROOT276_INITIAL_SUPPORT_INDEPENDENT_VERIFICATION_V4.json'
    assert not independent.exists()
    subprocess.run([PYTHON,'-B',str(verifier),'--verify','--manifest',str(manifest),
                    '--output',str(report),'--verification-output',str(independent)],cwd=LAB,check=True)
    verified = context['load'](independent)
    assert verified['status'] == 'VERIFIED_ROOT276_V8_WORKER_PARENT_SHA_BRIDGE_V4'
    counts = verified['worker_output']['case_counts']; assert sum(counts.values()) == 6
    actual = context['load'](report); assert actual['case_counts'] == counts and len(actual['cases']) == 6
    assert verified['scientific_qualification']['credit'] == 0
    proof.update(status='VERIFIED_ACTUAL_ROOT276_V8_INITIAL_SUPPORT_REPORTED_CASE_TERMINALS_NO_SCIENTIFIC_Q',
                 report=str(report),report_sha256=sha(report),manifest=str(manifest),manifest_sha256=sha(manifest),
                 independent_verification=str(independent),independent_verification_sha256=sha(independent),
                 independent_verifier=str(verifier),independent_verifier_sha256=sha(verifier),
                 case_verifications=actual['cases'],verified_case_counts=counts,
                 source_SHA_basis=verified['sourceSHA_basis'],root_deferred_payload_content_read=False,
                 failed_and_unknown_cases_preserved=True,new_native_cause_credit=0,new_native_join_credit=0,
                 scientific_Q_credit=0,initial_support_diagnostics_do_not_qualify_dynamics=True)
    footer = (S / 'governance/root-owned-lifecycle-continuation-v1/root_cpu_verification_footer.py').read_text()
    footer = footer.replace('1073741824',str(q['max_memory_bytes'])).replace('F7_S1_SOURCE_SUPPORT_ACTUAL_SCOPE_ROOT_VERIFICATION_137.json','INITIAL_SUPPORT_V8_ACTUAL_ROOT_VERIFICATION_276.json')
    context.update(q=q,b=base,r=receipt,p=proof,qp=qp,num='276',name='f6-initial-native-support-v8',subprocess=subprocess,importlib=importlib)
    exec(footer,context)


if __name__ == '__main__':
    main()
