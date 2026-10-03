"""Bind four completed GenCase products to fresh shared-runner native QA requests."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
LAB = HERE.parents[5]
ROOT = LAB.parent
OWNER = HERE.parent / 'f5_surface_first_coarse_medium_028'
OLD_ROOT = '/home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics'
OFFICIAL = Path('/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux')

def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()

def write(path, data):
    path.write_text(json.dumps(data, indent=2) + '\n')

def rebind(value):
    if isinstance(value, str):
        return value.replace(OLD_ROOT, str(ROOT))
    if isinstance(value, list):
        return [rebind(v) for v in value]
    if isinstance(value, dict):
        return {k: rebind(v) for k, v in value.items()}
    return value

def prepare():
    proof = []
    for name in ['runup_dp050', 'weir_dp050', 'runup_dp025', 'weir_dp025']:
        initial = rebind(json.loads((OWNER/name/'initial-manifest.json').read_text()))
        receipt = Path(initial['gencase_receipt'])
        actual = json.loads(receipt.read_text())
        assert actual['status'] == 'completed' and actual['returncode'] == 0
        assert actual['solver_dimension_from_gencase'] == 3
        assert actual['fluid_particles'] == initial['expected_fluid_particles']
        initial['gencase_receipt_sha256'] = digest(receipt)
        initial['total_particles'] = actual['total_particles']
        write(HERE/(name+'-initial-manifest.json'), initial)
        for kind, filename in [('coverage','coverage-input.json'), ('lineage','lineage-manifest.json')]:
            write(HERE/(name+'-'+filename), rebind(json.loads((OWNER/name/filename).read_text())))
        proof.append({'case_id': initial['case_id'], 'actual_receipt': str(receipt), 'actual_receipt_sha256': digest(receipt), 'total_particles': actual['total_particles'], 'fluid_particles': actual['fluid_particles'], 'dimension': 3})
    write(HERE/'review.json', {'schema':'ds02.f5.root-spatial-native-review.v1', 'at_utc':datetime.now(timezone.utc).isoformat(), 'actual_gencase':proof, 'approval':'Only initial identity/mass, finite coverage, original fluid/piston/physical-input preservation audits. GPU remains conditional on all actual checks.', 'cost_bound':'Four initial audits 4 threads x 600s plus eight coverage/lineage audits 4 threads x 300s: at most 5.3334 core-hours; 6 GiB conservative Home output.', 'owner_source_commit':'c6cb8b06', 'qualification':'none', 'scientific_thresholds_unchanged':True, 'prepared_hashes_replaced_with_actual_bindings':True})
    for name in ['runup_dp050', 'weir_dp050', 'runup_dp025', 'weir_dp025']:
        initial = json.loads((HERE/(name+'-initial-manifest.json')).read_text())
        prefix = Path(initial['generated_prefix'])
        for kind in ['initial','coverage','lineage']:
            r = rebind(json.loads((OWNER/name/(kind+'-request.json')).read_text()))
            r.update(attempt_id='root-'+name.replace('_','-')+'-surface-first-'+kind+'-030', worktree_root=str(ROOT), max_wall_seconds=600 if kind=='initial' else 300, launch_allowed=True, purpose='Actual completed GenCase native '+kind+' audit; no numerical or production approval.')
            manifest = HERE/(name+('-initial-manifest.json' if kind=='initial' else '-coverage-input.json' if kind=='coverage' else '-lineage-manifest.json'))
            old_config = str(OWNER/name/('initial-manifest.json' if kind=='initial' else 'coverage-input.json' if kind=='coverage' else 'lineage-manifest.json'))
            r['command'] = [str(manifest) if v==old_config else v for v in r['command']]
            inputs = [Path(v) for v in r['input_files'] if v!=old_config]
            inputs += [manifest, HERE/'review.json', Path(__file__), prefix.with_suffix('.xml'), prefix.with_suffix('.bi4'), Path(initial['gencase_receipt'])]
            if kind == 'initial':
                inputs += [LAB/'scripts/ds_data02_f5_commensurate_dp_reference_010.py', LAB/'scripts/ds_data02_native_labels.py']
            if kind == 'coverage':
                inputs += [LAB/'scripts/ds_data02_native_labels.py', LAB/'scripts/ds_data02_f7_initial_native_audit_v1.py', LAB/'scripts/f8_r008_safe_bi4_decoder_v1.py', LAB/'campaigns/ds-data-02/families/F2/f2_handoff_20261002_native_mass_audit.py']
            if kind == 'lineage':
                m = json.loads(manifest.read_text())
                inputs += [Path(v) for k,v in m.items() if k in ['old_definition','new_definition','old_bed','new_bed','old_motion','new_motion','old_receipt','new_receipt']]
                for key in ['old_prefix','new_prefix']:
                    p = Path(m[key]); inputs += [p.with_suffix('.xml'), p.with_name(p.name+'_Fluid.vtk'), p.with_name(p.name+'_Bound.vtk')]
            r['input_files'] = list(dict.fromkeys(str(p) for p in inputs))
            r['input_sha256'] = {str(p):digest(p) for p in r['input_files']}
            write(HERE/(name+'-'+kind+'-request.json'), r)
    print('Prepared 12 actual native audit requests; no scientific code executed.')

if __name__ == '__main__':
    prepare()
