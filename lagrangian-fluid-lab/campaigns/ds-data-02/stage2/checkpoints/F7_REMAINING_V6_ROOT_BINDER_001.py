from pathlib import Path
import json,sys,hashlib
root=Path('/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics');lab=root/'lagrangian-fluid-lab';stage=lab/'campaigns/ds-data-02/stage2';data=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');sys.path.insert(0,str(lab/'scripts'));import ds_data02_stage2_forward_request_v5 as forward
forward.V5_ROLES={'shared_dispatch_v6':'ds_data02_stage2_dispatch_v6.py','shared_strict_dispatch_v6':'ds_data02_strict_dispatch_v6.py','shared_runtime_v6':'ds_data02_runtime_v6.py','shared_runtime_v2':'ds_data02_runtime_v2.py','batch_runner_v6':'ds_data02_batch_runner_v6.py'}
forward.SCHEMA='ds02.stage2.forward-science-request.v6-root-canonical'
binder=stage/'checkpoints/F7_REMAINING_V6_ROOT_BINDER_001.py';assert not binder.exists();binder.write_bytes(Path(__file__).read_bytes())
freeze=json.loads((stage/'checkpoints/F7_LEGACY_BATCH_FREEZE_FOR_V6_MIGRATION_001.json').read_text());current={x['attempt_id'] for x in freeze['children_allowed_to_finish']};rows=[];skips=[]
for source in sorted((stage/'requests/science-v4/F7').glob('*.json')):
 old=json.loads(source.read_text());prior_output=data/'families/F7'/old['case_id']/old['attempt_id'];prior_receipt=prior_output/'execution-receipt.json'
 if prior_receipt.exists() and json.loads(prior_receipt.read_text()).get('status')=='completed':skips.append({'source':str(source),'reason':'actual prior terminal completed'});continue
 if old['attempt_id'] in current:skips.append({'source':str(source),'reason':'exact frozen-parent child allowed to finish; no duplicate'});continue
 attempt=old['attempt_id']+'-forward-v6-primary-001';out=stage/'requests/science-v6-remaining/F7'/(attempt+'.json');d=forward.build(source,out,shared_root=root,attempt_id=attempt)
 d['forward_v6']=d.pop('forward_v5');d['forward_runtime_note']='Forward shared v6 with measured input validation and source posthash CPU; exact CURRENT, source controls and H5 expected SHA carried without content reads.'
 for path in [source,binder,lab/'scripts/ds_data02_stage2_forward_request_v5.py',lab/'scripts/ds_data02_batch_runner.py']:
  d['input_files'].append(str(path));d['input_sha256'][str(path)]=forward.sha256_file(path)
 d['input_files']=list(dict.fromkeys(d['input_files']));d['launch_allowed']=True;d['execution_allowed']=True;d['launch_disabled']=False;d['launch_owner']='root';d['worktree_root']=str(root);d['cwd']=str(root)
 d['root_canonical_binding']={'scope':'unfinished exact CURRENT336 F7 only; prior completed and frozen current child excluded','historical_request':str(source),'historical_request_sha256':forward.sha256_file(source),'builder_source':str(binder),'builder_sha256':forward.sha256_file(binder),'H5_content_read_by_builder':False,'mutable_batch_receipt_used_as_scientific_input':False,'runtime_version':'v6','qualification':'UNKNOWN','full_stage2_goal_continues':True}
 d['sha256']=forward.canonical_sha(d);out.write_text(json.dumps(d,ensure_ascii=False,sort_keys=True,indent=2)+'\n');rows.append({'request':str(out),'attempt_id':attempt,'physical_case_id':d['physical_case_id'],'input_count':len(d['input_files'])})
p=stage/'checkpoints/F7_REMAINING_V6_PREPARATION_001.json';assert not p.exists();p.write_text(json.dumps({'schema':'ds02.stage2.f7-remaining-v6-preparation.v1','status':'READY_AFTER_LEGACY_CHILD_AND_PARENT_TERMINALS','prepared_request_count':len(rows),'requests':rows,'excluded':skips,'all_large_hashes_carried_from_immutable_source_request':True,'H5_content_read':False,'no_duplicate_child_case':True,'not_yet_launched':True,'goal_complete':False},ensure_ascii=False,indent=2)+'\n');print('prepared',len(rows),'excluded',len(skips))
