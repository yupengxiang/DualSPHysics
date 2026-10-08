"""Root metadata binding of the immutable delegated dp-only GenCase probe."""
from pathlib import Path
import hashlib
import json
import subprocess

ROOT = Path(__file__).resolve().parents[5]
STAGE = ROOT / 'lagrangian-fluid-lab/campaigns/ds-data-02/stage2'
REFERENCE = Path('/home/jade/.codex/worktrees/ds-data-02-stage2-reference/DualSPHysics')

def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1048576), b''):
            h.update(b)
    return h.hexdigest()

def main():
    old = STAGE / 'requests/stage2-mass-geometry-repair-v1/f1_s1_spatial_repair_dp0p009000.json'
    r = json.loads(old.read_text())
    original = Path(r['source_binding']['current_definition']['path'])
    candidate = STAGE / 'reference/stage2_mass_geometry_repair_inputs_v1/F1_S1/dp0p009000/F1_S1_SPATIAL_REPAIR_DP0p009000_Def.xml'
    assert original.read_bytes().count(b'<definition dp="0.01"') == 1
    assert candidate.read_bytes() == original.read_bytes().replace(b'<definition dp="0.01"', b'<definition dp="0.009"')
    # Preserve the delegated proposal; bind every remapped root file afresh.
    def remap(value):
        if isinstance(value, str):
            return value.replace(str(REFERENCE), str(ROOT))
        if isinstance(value, list):
            return [remap(x) for x in value]
        if isinstance(value, dict):
            return {remap(k): remap(v) for k,v in value.items()}
        return value
    r = remap(r)
    r['attempt_id'] = 'f1-s1-spatial-repair-dp0p009000-v1-root-001'
    r['input_files'].extend([str(old), str(Path(__file__).resolve()), str(Path(r['command'][0]).parent / 'DsphConfig.xml')])
    r['input_files'] = sorted(set(r['input_files']))
    r['input_hashes'] = {p: sha(p) for p in r['input_files']}
    for key in ['candidate_definition']:
        rec = r['source_binding'][key]
        p = Path(rec['path']); s = p.stat()
        rec.update(bytes=s.st_size, mtime_ns=s.st_mtime_ns, sha256=sha(p))
    rec = r['source_binding']['definition_semantics']['candidate_def']
    p = Path(rec['path']); s = p.stat()
    rec.update(bytes=s.st_size, mtime_ns=s.st_mtime_ns, sha256=sha(p))
    r.update(canonical_ready=True, launch_allowed=True, execution_allowed=True,
             launch_disabled=False, launch_owner='root', primary_launch_owner='root')
    r['resource_guard'].update(launch_disabled=False, parent_v6_review_required=False,
                               root_review='exact dp-only bytes, root static closure, official DsphConfig bound; scientific gates unchanged')
    r['forward_binding'] = {'delegated_request_path': str(old), 'delegated_request_sha256': sha(old),
                            'source_definition_sha256': sha(original), 'candidate_sha256': sha(candidate),
                            'only_definition_dp_changed': True, 'solver_launch': False,
                            'continuous_target_status': 'UNKNOWN_OVERLAP_VOID_CELL_CENTER_CROP',
                            'root_binder_sha256': sha(__file__)}
    r['launch_commit'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    out = STAGE / 'requests/stage2-mass-geometry-repair-v1-root/f1_s1_spatial_repair_dp0p009000_root_001.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('x') as f:
        json.dump(r, f, ensure_ascii=False, indent=2); f.write('\n')
    print(json.dumps({'status': 'ROOT_GENCAS_METADATA_BOUND_ONLY', 'request': str(out), 'sha256': sha(out), 'inputs': len(r['input_files'])}))

if __name__ == '__main__':
    main()
