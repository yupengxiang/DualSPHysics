#!/usr/bin/env python3
"""Close ROOT313 using independent V5 verification and full parent CPU fees."""
from pathlib import Path
import hashlib
import importlib.util
import json
import subprocess
import sys

HERE = Path(__file__).resolve().parent
LAB = HERE.parents[4]
S = LAB / 'campaigns/ds-data-02/stage2'
PYTHON = '/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python'
PAYLOAD = {'.h5', '.hdf5', '.bi4', '.obi4', '.ibi4', '.vtk', '.vtu', '.jsonl'}


def bounded_sha(path):
    path = Path(path)
    assert path.suffix.lower() not in PAYLOAD and path.stat().st_size <= 10485760
    before = path.stat(); data = path.read_bytes(); after = path.stat()
    assert (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
    return hashlib.sha256(data).hexdigest()


def main():
    assert len(sys.argv) == 2
    qp = Path(sys.argv[1]).absolute()
    common_source = S / 'governance/root-owned-lifecycle-continuation-v1/root_common_verification.py'
    context = {'__name__': 'root_mass313_actual', '__file__': str(common_source)}
    exec(common_source.read_text(), context)
    context['sha'] = bounded_sha
    q, base, receipt, proof = context['common'](qp)
    assert q['family_id'] == 'infra' and q['root_canonical_binding']['namespace'] == 313
    manifest = Path(q['manifest_contract']['path'])
    assert bounded_sha(manifest) == q['manifest_contract']['sha256']
    report = base / 'root313-native-typed-mass-impact.json'
    verifier = LAB / 'scripts/ds_data02_stage2_verify_native_typed_mass_impact_v5.py'
    verified_path = S / 'checkpoints/ROOT313_NATIVE_TYPED_MASS_IMPACT_INDEPENDENT_VERIFICATION_V5.json'
    assert not verified_path.exists()
    subprocess.run([PYTHON, '-B', str(verifier), 'verify', '--manifest', str(manifest), '--result', str(report), '--output', str(verified_path)], cwd=LAB, check=True)
    verified = context['load'](verified_path)
    assert verified['schema'] == 'ds02.stage2.native-typed-mass-impact-verification.v5'
    assert verified['status'] == 'PASS_SOURCE_IDENTITY_STAT_ONLY'
    counts = verified['counts']
    assert counts['cases'] == 17 and counts['completed'] + counts['failed'] == 17
    assert not any(verified['read_policy'][k] for k in ['deferred_jsonl_content_opened', 'h5_content_opened', 'native_payload_content_opened'])
    assert all(verified['claim_boundary'][k] == 'UNKNOWN' for k in ['physical_mass_flux', 'physical_fate', 'dynamics', 'QI', 'QN', 'QE'])
    proof.update(status='VERIFIED_ACTUAL_ROOT313_NATIVE_TYPED_MASS_IMPACT_REPORTED_CASE_TERMINALS_NO_PHYSICAL_Q',
                 report=str(report), report_sha256=bounded_sha(report), manifest=str(manifest), manifest_sha256=bounded_sha(manifest),
                 independent_verifier=str(verifier), independent_verifier_sha256=bounded_sha(verifier),
                 independent_verification=str(verified_path), independent_verification_sha256=bounded_sha(verified_path),
                 case_verifications=verified['case_verifications'], verified_counts=counts,
                 root_deferred_payload_content_read=False, new_native_cause_credit=0, new_native_join_credit=0,
                 scientific_mass_scope='typed fluid/type3 selected per-ID initial mass exact-or-null; saved exclusion impact diagnostic',
                 physical_fate_flux_dynamics='UNKNOWN', failed_cases_grant_mass_credit=False)
    footer = (S / 'governance/root-owned-lifecycle-continuation-v1/root_cpu_verification_footer.py').read_text()
    footer = footer.replace('1073741824', str(q['max_memory_bytes'])).replace('F7_S1_SOURCE_SUPPORT_ACTUAL_SCOPE_ROOT_VERIFICATION_137.json', 'NATIVE_TYPED_MASS_IMPACT_ACTUAL_ROOT_VERIFICATION_313.json')
    context.update(q=q, b=base, r=receipt, p=proof, qp=qp, num='313', name='native-typed-mass-impact', subprocess=subprocess, importlib=importlib)
    exec(footer, context)
    unit = 'ds02-native-typed-mass-impact-root-313'
    state = subprocess.check_output(['systemctl', '--user', 'show', unit, '-p', 'SubState', '-p', 'MainPID'], text=True)
    assert 'SubState=dead' in state and 'MainPID=0' in state


if __name__ == '__main__':
    main()
