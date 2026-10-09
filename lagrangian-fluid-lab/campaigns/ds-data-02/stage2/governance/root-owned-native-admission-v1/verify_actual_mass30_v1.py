"""Verify a ROOT322--326 mass diagnostic and close the original parent fee."""
from pathlib import Path
import hashlib
import importlib
import subprocess
import sys

HERE = Path(__file__).resolve().parent
LAB = HERE.parents[4]
S = LAB / 'campaigns/ds-data-02/stage2'
PYTHON = '/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python'
COUNTS = {322: 1, 323: 8, 324: 8, 325: 8, 326: 5}


def sha(path):
    path = Path(path)
    assert path.suffix.lower() not in {'.h5', '.hdf5', '.bi4', '.obi4', '.ibi4', '.vtk', '.vtu', '.jsonl'}
    before = path.stat()
    assert before.st_size <= 10485760
    raw = path.read_bytes()
    after = path.stat()
    assert (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
    return hashlib.sha256(raw).hexdigest()


def main():
    assert len(sys.argv) == 3
    qp = Path(sys.argv[1]).absolute()
    num = int(sys.argv[2])
    assert num in COUNTS
    common = S / 'governance/root-owned-lifecycle-continuation-v1/root_common_verification.py'
    context = {'__file__': str(common), '__name__': 'root_mass30_actual_v1'}
    exec(common.read_text(), context)
    context['sha'] = sha
    q, base, receipt, proof = context['common'](qp)
    assert q['family_id'] == 'infra' and q['root_canonical_binding']['namespace'] == num
    manifest = Path(q['manifest_contract']['path'])
    assert sha(manifest) == q['manifest_contract']['sha256']
    report = base / 'native-typed-mass-impact-v6.json'
    verifier = LAB / 'scripts/ds_data02_stage2_verify_native_typed_mass_impact_v6.py'
    independent = S / f'checkpoints/ROOT{num}_MASS_IMPACT_INDEPENDENT_VERIFICATION_V6.json'
    assert not independent.exists()
    subprocess.run([PYTHON, '-B', str(verifier), 'verify', '--manifest', str(manifest), '--result', str(report), '--output', str(independent)], cwd=LAB, check=True)
    verified = context['load'](independent)
    assert verified['schema'] == 'ds02.stage2.native-typed-mass-impact-verification.v6'
    assert verified['status'] == 'PASS_SOURCE_IDENTITY_STAT_ONLY'
    counts = verified['counts']
    assert counts['cases'] == COUNTS[num] and counts['completed'] + counts['failed'] == COUNTS[num]
    assert not any(verified['read_policy'][k] for k in ['deferred_jsonl_content_opened', 'h5_content_opened', 'native_payload_content_opened'])
    assert all(verified['claim_boundary'][k] == 'UNKNOWN' for k in ['physical_mass_flux', 'physical_fate', 'dynamics', 'QI', 'QN', 'QE'])
    proof.update(status='VERIFIED_ACTUAL_V6_SELECTED_TYPED_MASS_CASE_TERMINALS_NO_PHYSICAL_Q',
                 report=str(report), report_sha256=sha(report), manifest=str(manifest), manifest_sha256=sha(manifest),
                 independent_verification=str(independent), independent_verification_sha256=sha(independent),
                 independent_verifier=str(verifier), independent_verifier_sha256=sha(verifier),
                 case_verifications=verified['case_verifications'], verified_counts=counts,
                 root_deferred_payload_content_read=False, new_native_cause_credit=0, new_native_join_credit=0,
                 scientific_mass_scope='selected typed fluid/type3 per-ID initial mass exact-or-null; no case-total fallback',
                 physical_fate_flux_dynamics='UNKNOWN', scientific_Q_credit=0, failed_cases_grant_mass_credit=False)
    footer = (S / 'governance/root-owned-lifecycle-continuation-v1/root_cpu_verification_footer.py').read_text()
    footer = footer.replace('1073741824', str(q['max_memory_bytes'])).replace('F7_S1_SOURCE_SUPPORT_ACTUAL_SCOPE_ROOT_VERIFICATION_137.json', f'NATIVE_TYPED_MASS_IMPACT_ACTUAL_ROOT_VERIFICATION_{num}.json')
    context.update(q=q, b=base, r=receipt, p=proof, qp=qp, num=str(num), name='native-typed-mass-impact-v6', subprocess=subprocess, importlib=importlib)
    exec(footer, context)


if __name__ == '__main__':
    main()
