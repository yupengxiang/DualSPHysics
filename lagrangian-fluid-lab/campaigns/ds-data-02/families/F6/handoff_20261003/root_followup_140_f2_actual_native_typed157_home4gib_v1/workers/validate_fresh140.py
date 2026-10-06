#!/usr/bin/env python3
"""Fresh140 source-only metadata validator.

This validator does not open native solver data, H5, BI4, CSV, DAT, VTK, or
Run.out. It validates the actual Root812/Root804/Root809 JSON/XML metadata,
request closure, disabled flags, and Root974/Root142 tool attestations.
"""
from __future__ import annotations
import argparse, hashlib, json, sys
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
KNOWN_ATTESTATIONS = {
    '/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python': 'a2f33a6e006989270f4340528eb61f8f97366e00a5d1b602ac8672ea44fc56ae',
    '/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_157_nvme_typed_home_cap_publish_cleanup_fix_v1/scripts/nvme_convert_home_capped_v2.py': '37fe7eaff4405e9ba6d9b7f666a53d7c02ee65fc6f30992fc1a8fdb0d8a61b11',
    '/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_157_nvme_typed_home_cap_publish_cleanup_fix_v1/scripts/home_publish_math.py': '89f57c71f29bb8c47f5949aa7e5902e16378cf75a2ae8338cabc019ee3ffc268',
    '/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py': '5098262e26dc5560487760181466b0a93a0e66239e5e54047dce5e761ae67a60',
    '/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py': '81bdd60e5de4fec362807043ab632864405f1667a0658560fb9349025aab75ec',
    '/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_home_floor_inventory_dispatch_142/launch.py': '708c4c83d22257f7b59bad93cd19915fb66a199a2a5b1291d6ada71bb467ea76',
    '/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_home_floor_inventory_dispatch_142/root_home_floor_inventory_policy.py': '2649eedbcf4816f8d2fa7b2182828ea8b3ce107ef47f25c56780d29c5138def5',
    '/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump': 'b8ac8cf4aff68ffd089da6cf3ef19dfd0c6473121475f4c198b720a0ddaa8b2e',
    '/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64': '62630430902484f4aede017108313673fe6414f40fb59b6ae7f14ac23219db00',
}
FORBIDDEN = {'.h5', '.bi4', '.csv', '.dat', '.vtk', '.vtu'}
SAFE = {'.json', '.xml', '.py', '.md'}

def sha(p: Path):
    h = hashlib.sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda: f.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()

def load(p): return json.loads(Path(p).read_text())
def fail(msg): raise AssertionError(msg)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--report', default=None); args=ap.parse_args()
    manifest=load(PKG/'F2_STAGE1_FRESH140_ACTUAL_NATIVE_TYPED157_MANIFEST.json')
    selected=manifest['selected_cases']; assert len(selected)==12
    assert manifest['family_id']=='F2' and manifest['fresh_id']=='fresh140'
    results=[]
    for case in selected:
        reqp=PKG/'requests/typed'/(case+'-typed157-home4gib-disabled.json')
        ownerp=PKG/'owners'/(case+'-actual-native-typed157-owner.json')
        assert reqp.exists() and ownerp.exists(), case
        req=load(reqp); owner=load(ownerp)
        assert req['schema']=='ds02.runner-request.v2'
        assert req['case_id']==case and req['family_id']=='F2'
        for k in ('disabled','source_only'):
            assert req[k] is True, (case,k)
        for k in ('launch','launch_allowed','execution_allowed','solver_allowed','conversion_allowed','arrays_allowed','array_edit_allowed'):
            assert req[k] is False, (case,k)
        assert req['cpu_task_kind']=='conversion' and req['cpu_threads']==2
        assert req['estimated_storage_bytes']==4294967296
        assert req['home_publish_cap_bytes']==4294967296 and req['home_min_free_bytes']==536870912000
        assert req['expected_frames']==401 and req['expected_dimension']==3 and req['expected_particles']==418104
        assert req['expected_counts']=={'data2d':False,'solver_dimension':3,'total_particles':418104,'fixed_particles':372840,'moving_particles':24150,'floating_particles':0,'fluid_particles':21114,'xml_particle_counts':{'fixed':372840,'moving':24150,'floating':0,'fluid':21114}}
        assert req['canonical_physical_binding_sha256'] is None and req['actual_converter_physical_condition_scope_sha256'] is None
        assert req['future_output_hashes']=={'typed_h5_sha256':None,'conversion_report_sha256':None,'typed_receipt_sha256':None,'xmf_manifest_sha256':None,'render_manifest_sha256':None}
        assert req['source_agent_did_not_read_or_hash_science_payloads'] is True
        assert req['source_arrays_read_or_hashed_by_source_agent'] is False
        assert req['input_sha256_required'] is True
        assert set(req['input_files'])==set(req['input_sha256'])
        assert set(req['input_files'])==set(req['input_sha256_categories'])==set(req['input_sha256_provenance'])
        for s in req['input_files']:
            p=Path(s); suf=p.suffix.lower()
            assert suf not in FORBIDDEN, (case,'forbidden input',s)
            if s in KNOWN_ATTESTATIONS:
                assert req['input_sha256'][s]==KNOWN_ATTESTATIONS[s]
            else:
                assert suf in SAFE and p.is_file(), (case,'missing metadata',s)
                assert sha(p)==req['input_sha256'][s], (case,'stale hash',s)
        for entry in req['future_input_files']:
            assert entry['sha256'] is None and entry.get('producer_only') is True
        assert all(v is None for v in req['future_input_sha256'].values())
        assert req['owner_metadata']==str(ownerp)
        assert req['owner_metadata_sha256']==sha(ownerp)
        assert owner['canonical_physical_binding_sha256'] is None
        assert owner['future_conversion_report_sha256'] is None and owner['future_trajectory_h5_sha256'] is None
        assert owner['scientific_payloads_read_or_hashed_by_owner_builder'] is False
        assert owner['geometry']['dimension']==3 and owner['density_kg_m3']==1000 and owner['gravity_m_s2']==[0,0,-9.81]
        nr=load(req['actual_native_dependency']['receipt']); assert (nr.get('status'),nr.get('returncode'))==('completed',0)
        assert req['actual_native_dependency']['receipt_sha256']==sha(Path(req['actual_native_dependency']['receipt']))
        qa=load(req['actual_initial_qa_dependency']['report']); assert qa['status']=='pass'
        assert all(bool(v) for v in qa['checks'].values())
        assert req['actual_initial_qa_dependency']['csv_sha256'] is None and req['actual_initial_qa_dependency']['csv_read_or_hashed_here'] is False
        prep=load(req['prepared_input_report']); assert prep['actual_total_particles']==418104
        assert prep['generated_xml_particle_counts']=={'fixed':372840,'moving':24150,'floating':0,'fluid':21114}
        assert sha(Path(req['generated_xml']))==req['generated_xml_sha256']
        results.append({'case_id':case,'status':'pass','input_count':len(req['input_files']),'future_input_count':len(req['future_input_files'])})
    report={'schema':'ds02.f2.fresh140.validation.v1','status':'pass','selected_count':len(results),'cases':results,'scientific_payload_read_or_hashed':False,'future_hashes_all_null':True}
    if args.report:
        Path(args.report).write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print(json.dumps(report,indent=2,sort_keys=True))
    return 0
if __name__=='__main__':
    try: raise SystemExit(main())
    except Exception as exc:
        print(f'fresh140 validation FAILED: {exc}', file=sys.stderr); raise
