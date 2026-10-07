#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = [
    Path('README.md'),
    Path('manifest.json'),
    Path('metadata/actual1101-readiness.json'),
    Path('metadata/role-provenance.json'),
    Path('scripts/validate_fresh227.py'),
]

def sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()

def fail(msg: str):
    raise SystemExit('fresh227 validation FAILED: ' + msg)

m = json.loads((ROOT/'manifest.json').read_text())
if m.get('schema') != 'ds02.f5.fresh227.manifest.v1': fail('manifest schema')
files = m.get('files')
if not isinstance(files, list): fail('manifest files')
paths = {x.get('path') for x in files}
if paths != {str(x) for x in EXPECTED if x.name != 'manifest.json'}: fail('manifest file set')
for item in files:
    p = ROOT / item['path']
    if not p.is_file(): fail('missing ' + item['path'])
    if item.get('sha256') != sha(p): fail('hash ' + item['path'])
    if item.get('size_bytes') != p.stat().st_size: fail('size ' + item['path'])

r = json.loads((ROOT/'metadata/actual1101-readiness.json').read_text())
if r.get('schema') != 'ds02.f5.fresh227.f3.original1101.metadata-readiness.v1': fail('readiness schema')
if r.get('scientific_family') != 'F3' or r.get('assigned_family') != 'F5': fail('family roles')
if r.get('case_id') != 'F3_STAGE1_DP006_P1200_AY0390': fail('case id')
if r.get('physical_case_id') != 'F3_TWOAXIS_P1200_AY0390_STAGE1_FIRST48_PITCH_VARIANT': fail('physical id')
if r.get('counts_and_time', {}).get('frames') != 836 or r.get('counts_and_time', {}).get('particles') != 179208: fail('expected scope')
if r.get('counts_and_time', {}).get('solver_dimension') != 3: fail('3d')
if r.get('scope_roles', {}).get('native_source_plan_condition_sha256') != {'present': False, 'value': None}: fail('native condition mask')
if r.get('scope_roles', {}).get('native_source_plan_physical_condition_sha256') != {'present': False, 'value': None}: fail('native physical mask')
if r.get('scope_roles', {}).get('xmf_source_plan_condition_sha256', {}).get('present') is not True: fail('XMF condition presence')
if r.get('scope_roles', {}).get('xmf_source_plan_condition_sha256', {}).get('value') != '7560a18fa29742681ee567b06567ed4052da8ceb138b601e94b5223df22660f5': fail('XMF condition value')
if r.get('scope_roles', {}).get('xmf_source_plan_physical_condition_sha256') != {'present': False, 'value': None}: fail('XMF physical mask')
rt = r.get('runtime_snapshot', {})
receipt = rt.get('execution_receipt', {})
if receipt.get('status') != 'running' or receipt.get('returncode') is not None or receipt.get('terminal') is not False or receipt.get('published') is not False: fail('live receipt must remain pending')
if rt.get('no_restart') is not True or rt.get('controller_wait_is_not_completed_render') is not True: fail('runtime boundary')
fut = r.get('future_terminal_and_visual_gate', {})
if fut.get('main_own_qi_executed') is not False or fut.get('main_own_qi_proof_sha256') is not None: fail('future QI state')
if fut.get('future_render_report_sha256') is not None or fut.get('future_publish_receipt_sha256') is not None: fail('future render hashes')
if fut.get('case_credit') != 0 or fut.get('Q_N') != 0 or fut.get('Q_E') != 0: fail('credit')
if r.get('boundary', {}).get('science_payload_read') is not False or r.get('boundary', {}).get('science_payload_hash_by_source') is not False: fail('payload boundary')

p = json.loads((ROOT/'metadata/role-provenance.json').read_text())
if p.get('schema') != 'ds02.f5.fresh227.f3.original1101.role-provenance.v1': fail('role schema')
if p.get('native_plan_namespace', {}).get('source_plan_condition_sha256') != {'present': False, 'value': None}: fail('role native condition')
if p.get('native_plan_namespace', {}).get('source_plan_physical_condition_sha256') != {'present': False, 'value': None}: fail('role native physical')
if p.get('xmf_plan_namespace', {}).get('source_plan_condition_sha256', {}).get('value') != '7560a18fa29742681ee567b06567ed4052da8ceb138b601e94b5223df22660f5': fail('role XMF condition')
if p.get('xmf_plan_namespace', {}).get('source_plan_physical_condition_sha256') != {'present': False, 'value': None}: fail('role XMF physical')
if p.get('source_boundary', {}).get('science_payload_read') is not False or p.get('source_boundary', {}).get('science_payload_hash') is not False: fail('role payload boundary')

for pth in (ROOT/'metadata').rglob('*'):
    if pth.is_file():
        low = pth.read_text(errors='ignore').lower()
        for suffix in ('.h5', '.bi4', '.ibi4', '.csv', '.dat', '.vtk', '.png'):
            if suffix in low: fail(f'payload suffix leaked in {pth.relative_to(ROOT)}: {suffix}')
print('fresh227 validation PASS: F3 original1101 metadata readiness, upstream roles closed, render pending, metadata-only')
print('package=' + str(ROOT))
