"""Verify the actual four-sentinel frame-zero diagnostic and parent closure."""
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
    assert path.suffix.lower() not in {'.h5', '.hdf5', '.bi4', '.obi4', '.ibi4', '.vtk', '.vtu', '.jsonl'} and path.stat().st_size <= 10485760
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    qp = Path(sys.argv[1]).absolute()
    common = S / 'governance/root-owned-lifecycle-continuation-v1/root_common_verification.py'
    context = {'__file__': str(common), '__name__': 'root314_actual_frame0_v1'}
    exec(common.read_text(), context)
    context['sha'] = sha
    q, base, receipt, proof = context['common'](qp)
    assert q['family_id'] == 'infra' and q['max_memory_bytes'] == 2147483648
    manifest = Path(q['manifest_contract']['path'])
    assert sha(manifest) == q['manifest_contract']['sha256']
    report = base / 'observer/four_sentinel_frame0_position_support_audit_v2.json'
    verifier = S / 'reference/stage2_four_sentinel_frame0_support_verify_v5.py'
    independent = S / 'checkpoints/ROOT314_FRAME0_INDEPENDENT_VERIFICATION_V5.json'
    assert not independent.exists()
    subprocess.run([PYTHON, '-B', str(verifier), '--verify', '--manifest', str(manifest), '--output', str(report), '--verification-output', str(independent)], cwd=LAB, check=True)
    verified = context['load'](independent)
    assert verified['status'] == 'VERIFIED_ROOT314_FRAME0_WORKER_OUTPUT_V5_EXTERNAL_XML_BRIDGE'
    assert verified['scientific_qualification']['credit'] == 0
    counts = verified['case_counts']
    assert sum(counts.values()) == 4
    actual = context['load'](report)
    assert len(actual['cases']) == 4
    assert all(actual['case_counts'].get(k, 0) == v for k, v in counts.items())
    proof.update(status='VERIFIED_ACTUAL_FOUR_SENTINEL_FRAME0_CASE_TERMINALS_NO_SCIENTIFIC_Q',
                 report=str(report), report_sha256=sha(report), manifest=str(manifest), manifest_sha256=sha(manifest),
                 independent_verification=str(independent), independent_verification_sha256=sha(independent),
                 independent_verifier=str(verifier), independent_verifier_sha256=sha(verifier),
                 case_verifications=actual['cases'], verified_case_counts=counts,
                 source_SHA_basis=verified['sourceSHA_basis'], source_XML_bridges=verified['source_xml_bridges'],
                 root_deferred_payload_content_read=False, failed_and_unknown_cases_preserved=True,
                 historical_F7_identity_not_filled=True, new_native_cause_credit=0, new_native_join_credit=0,
                 scientific_Q_credit=0, continuous_owner_mass_support_dynamics='UNKNOWN')
    footer = (S / 'governance/root-owned-lifecycle-continuation-v1/root_cpu_verification_footer.py').read_text()
    footer = footer.replace('1073741824', str(q['max_memory_bytes'])).replace('F7_S1_SOURCE_SUPPORT_ACTUAL_SCOPE_ROOT_VERIFICATION_137.json', 'FRAME0_SUPPORT_ACTUAL_ROOT_VERIFICATION_314.json')
    context.update(q=q, b=base, r=receipt, p=proof, qp=qp, num='314', name='four-sentinel-frame0-support', subprocess=subprocess, importlib=importlib)
    exec(footer, context)


if __name__ == '__main__':
    main()
