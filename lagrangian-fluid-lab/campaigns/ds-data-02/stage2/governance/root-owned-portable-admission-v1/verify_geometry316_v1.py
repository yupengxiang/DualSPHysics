"""Close the four-sentinel actual geometry support diagnostic without owner credit."""
from pathlib import Path
import hashlib
import importlib
import json
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
    context = {'__file__': str(common), '__name__': 'root_geometry316_actual_v1'}
    exec(common.read_text(), context); context['sha'] = sha
    q, base, receipt, proof = context['common'](qp)
    assert q['family_id'] == 'infra'
    manifest = Path(q['manifest_contract']['path'])
    assert sha(manifest) == q['manifest_contract']['sha256']
    report = base / 'report/four_sentinel_gencase_geometry_support_audit_v1.json'
    independent = S / 'checkpoints/ROOT316_GEOMETRY_SUPPORT_INDEPENDENT_VERIFICATION_V2.json'
    assert not independent.exists()
    verifier = S / 'reference/stage2_four_sentinel_gencase_geometry_support_verify_v2.py'
    subprocess.run([PYTHON,'-B',str(verifier),'--verify','--manifest',str(manifest),'--request',str(qp),
                    '--output',str(report),'--verification-output',str(independent)], cwd=LAB, check=True)
    verified = context['load'](independent)
    assert verified['status'] == 'VERIFIED_ROOT316_WORKER_AND_STATIC_REQUEST_CONTRACT'
    assert verified['scientific_qualification']['credit'] == 0
    actual = context['load'](report)
    cases = actual['cases']; assert len(cases) == 4
    proof.update(status='VERIFIED_ACTUAL_ROOT316_FOUR_SENTINEL_VTK_GEOMETRY_SUPPORT_DIAGNOSTIC_NO_OWNER_Q',
                 report=str(report), report_sha256=sha(report), manifest=str(manifest), manifest_sha256=sha(manifest),
                 independent_verification=str(independent), independent_verification_sha256=sha(independent),
                 case_verifications=cases, actual_cases=4, root_deferred_payload_content_read=False,
                 continuous_owner_credit=0, physical_penetration_credit=0, scientific_Q_credit=0)
    footer = (S / 'governance/root-owned-lifecycle-continuation-v1/root_cpu_verification_footer.py').read_text()
    footer = footer.replace('1073741824',str(q['max_memory_bytes'])).replace('F7_S1_SOURCE_SUPPORT_ACTUAL_SCOPE_ROOT_VERIFICATION_137.json','GEOMETRY_SUPPORT_ACTUAL_ROOT_VERIFICATION_316.json')
    context.update(q=q,b=base,r=receipt,p=proof,qp=qp,num='316',name='four-sentinel-geometry-support',subprocess=subprocess,importlib=importlib)
    exec(footer,context)


if __name__ == '__main__':
    main()
