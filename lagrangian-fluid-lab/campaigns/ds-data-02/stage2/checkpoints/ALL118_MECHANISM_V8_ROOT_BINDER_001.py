"""Bind delegated all118 probe to root v8 guards without pre-lease source reads."""
from pathlib import Path
import hashlib
import json
import subprocess

ROOT = Path(__file__).resolve().parents[5]
STAGE = ROOT / 'lagrangian-fluid-lab/campaigns/ds-data-02/stage2'

def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1048576), b''):
            h.update(b)
    return h.hexdigest()

def main():
    old = STAGE / 'requests/omission-mechanism-probe-v2/omission-mechanism-probe-v2-request.json'
    manifest = STAGE / 'requests/omission-mechanism-probe-v2/omission-mechanism-probe-v2-manifest.json'
    r = json.loads(old.read_text()); m = json.loads(manifest.read_text())
    assert m['selected_case_counts'] == {'F2': 48, 'F4': 22, 'F6': 48}
    assert m['selected_native_id_count'] == 1328
    assert len(m['selected_case_keys']) == len(set(m['selected_case_keys'])) == 118
    hashes = r['input_sha256']
    for p,h in m['input_sha256'].items():
        assert hashes[p] == h
        q = Path(p)
        assert q.is_file() and q.suffix.lower() not in {'.h5', '.hdf5', '.obi4'}
        assert not (q.name.startswith('Part_') and q.suffix == '.bi4')
    old_manifest = Path(r['command'][r['command'].index('--manifest') + 1])
    assert sha(old_manifest) == sha(manifest) == hashes[str(old_manifest)]
    script = ROOT / 'lagrangian-fluid-lab/scripts/ds_data02_stage2_omission_mechanism_probe_v2.py'
    assert sha(script) == sha(r['command'][1])
    strace = Path('/usr/bin/strace')
    guards = [ROOT / ('lagrangian-fluid-lab/scripts/' + name) for name in
              ['ds_data02_stage2_dispatch_v8.py', 'ds_data02_strict_dispatch_v8.py',
               'ds_data02_runtime_v8.py', 'ds_data02_runtime_v6.py', 'ds_data02_runtime_v2.py']]
    for p in [script, manifest, old, Path(__file__).resolve(), strace, *guards]:
        hashes[str(p)] = sha(p)
    r['input_files'] = sorted(hashes)
    r['attempt_id'] = 'omission-mechanism-probe-v2-primary-001-v8-root'
    r['worktree_root'] = str(ROOT); r['cwd'] = str(ROOT)
    r['command'][1] = str(script)
    r['command'][r['command'].index('--manifest')+1] = str(manifest)
    r['command'] = [str(strace), '-f', '-qq', '-e', 'trace=open,openat,openat2',
                    '-o', '{attempt_root}/os-open.log', *r['command']]
    r['shared_runtime_version'] = 'v8'
    for key,path in [('runtime_binding',guards[2]),('dispatch_binding',guards[0]),('strict_dispatch_binding',guards[1])]:
        r[key] = {'path':str(path), 'sha256':sha(path)}
    r['forward_root_binding'] = {
        'original_request':str(old), 'original_request_sha256':sha(old),
        'source_manifest_sha256':sha(manifest), 'worker_sha256':sha(script),
        'source_content_hashing_before_parent_reservation':False,
        'full_source_hashing':'expected metadata reused; actual v8 pre/post validation occurs after reservation',
        'single_outer_strace':True, 'native_ids':1328, 'cases':118,
        'base_runtime_v2_bound':True, 'physical_fate':'UNKNOWN', 'dynamics':'UNKNOWN'}
    r['launch_commit'] = subprocess.check_output(['git','rev-parse','HEAD'], cwd=ROOT, text=True).strip()
    out = STAGE / 'requests/omission-mechanism-probe-v2-root/omission-mechanism-probe-v2-primary-001-v8-root.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('x') as f:
        json.dump(r,f,ensure_ascii=False,indent=2); f.write('\n')
    print(json.dumps({'status':'ROOT_V8_METADATA_BOUND_ONLY','request':str(out),'sha256':sha(out),'input_files':len(hashes),'case_count':118,'native_ids':1328}))

if __name__ == '__main__':
    main()
