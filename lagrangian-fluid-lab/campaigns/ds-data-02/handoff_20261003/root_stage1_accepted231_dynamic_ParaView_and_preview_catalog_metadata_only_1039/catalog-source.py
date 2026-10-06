from pathlib import Path
import json,hashlib,datetime,subprocess,collections
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');H=R/'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003';cpfile=H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_153.json';load=lambda p:json.loads(Path(p).read_text());cp=load(cpfile)
def sha(p):
 p=Path(p);assert p.suffix=='.json';return hashlib.sha256(p.read_bytes()).hexdigest()
ref=lambda p:{'path':str(p),'sha256':sha(p)}
def paths(z,context=''):
 if isinstance(z,dict):
  for k,v in z.items():yield from paths(v,context+'/'+k)
 elif isinstance(z,list):
  for v in z:yield from paths(v,context)
 elif isinstance(z,str) and z.startswith('/'):yield context,z
entries=[];gaps=[]
for dp in cp['accepted_decisions']:
 d=load(dp);refs=list(paths(d));derived=[];seen=set()
 # Some historical decisions expose producer receipts, others refer to one
 # independent closure/visual sidecar. Follow those immutable metadata layers.
 for iteration in range(3):
  add=[]
  for ctx,path in refs:
   p=Path(path)
   if path in seen or p.suffix!='.json' or not p.is_file():continue
   semantic=ctx.lower()
   receipt=p.name=='execution-receipt.json' and any(k in semantic for k in ['xmf','render','animation'])
   sidecar=any(k in semantic for k in ['independent_metadata_closure','physical_visual_sidecar'])
   if not receipt and not sidecar:continue
   seen.add(path);z=load(p)
   if sidecar:add.extend(paths(z,semantic));derived.append({'source':ref(p),'role':'accepted independent metadata closure or delegated visual sidecar'});continue
   if 'returncode' not in z:
    add.extend(paths(z,semantic));derived.append({'source':ref(p),'role':'original metadata receipt alias; follow underlying refs, not treated as execution proof'});continue
   assert (z['status'],z['returncode'])==('completed',0)
   out=Path(z['output_root']);cmd=z.get('command',z['request'].get('command',[]));dirs=[out]
   for flag in ['--output-dir','--output']:
    if flag in cmd:
     val=cmd[cmd.index(flag)+1]
     if '{attempt_root}' in val or val.startswith('/'):
      candidate=Path(val.replace('{attempt_root}',str(out)))
      if candidate.is_dir():dirs.append(candidate)
   # Renderer wrapper output is a regular child directory, discovered from
   # the actual completed producer's output root, rather than a case alias.
   dirs.extend(p for p in out.iterdir() if p.is_dir() and p.name in {'render','xdmf','xmf'})
   for directory in dirs:
    for item in directory.iterdir():
     if item.is_file() and (item.name in {'manifest.json','paraview-full-animation-report.json'} or item.suffix.lower() in {'.xmf','.xdmf'}):add.append((semantic+'/actual_completed_output_inventory',str(item)))
   derived.append({'source':ref(p),'actual_completed_output_root':str(out),'role':'actual producer receipt command/output inventory'})
  refs.extend(add)
 mf=set(p for c,p in refs if Path(p).name=='manifest.json' and ('xmf' in c.lower() or 'manifest' in c.lower()) and Path(p).is_file());xm=set(p for c,p in refs if Path(p).suffix.lower() in {'.xmf','.xdmf'} and Path(p).is_file());rp=set(p for c,p in refs if Path(p).name=='paraview-full-animation-report.json' and Path(p).is_file())
 manifests=[]
 for p in sorted(mf):
  m=load(p);manifests.append({'source':ref(p),'reported_frames':m.get('frames'),'reported_particles':m.get('particles',m.get('expected_particles')),'reported_physical_case_id':m.get('physical_case_id'),'reported_physical_scope':{k:v for k,v in m.items() if ('scope' in k or 'physical_condition' in k) and isinstance(v,(str,int,float,bool,type(None)))}})
  if isinstance(m.get('xdmf'),str) and Path(m['xdmf']).is_file():xm.add(m['xdmf'])
 renders=[];previews=set(p for ctx,p in refs if Path(p).suffix.lower()=='.png' and Path(p).is_file())
 for p in sorted(rp):
  r=load(p)
  if not r.get('all_frames_rendered'):continue
  source_frames=r.get('source_frames')
  assert source_frames is None or source_frames==r['frames']
  for ctx,png in paths(r):
   if Path(png).suffix.lower()=='.png' and Path(png).is_file():previews.add(png)
  renders.append({'source':ref(p),'actual_frames':r['frames'],'source_frames_original_field':source_frames,'original_source_frames_field_absent_not_fabricated':source_frames is None,'all_frames_rendered':True,'actual_times_preserved_exactly':r.get('actual_times_preserved_exactly'),'actual_original_render_schema':r.get('schema')})
 if not xm or not renders:gaps.append({'decision':dp,'dynamic_files':list(xm),'render_reports':list(rp)})
 # The catalog retains semantic roles by reference; it does not recompute a
 # scientific scope, read data arrays, promote precision or alter acceptance.
 entries.append({'family_id':d['family_id'],'case_id':d['case_id'],'physical_case_id':d.get('physical_case_id',d['case_id']),'accepted_decision':ref(dp),'acceptance_scope_sha256_original_role':d['physical_condition_sha256'],'stage1_label':'视觉检查通过、数值精度未验收','q_n_granted':False,'q_e_granted':False,'paraview_dynamic_files':sorted(xm),'dynamic_manifests':manifests,'complete_animation_reports':renders,'preview_png_files':sorted(previews),'preview_files_stat_only_main_no_personal_visual_review':True,'parameter_geometry_motion_state_provenance':{'authoritative_decision':str(dp),'actual_original_evidence_fields_present':[k for k in ['bindings','trajectory_binding','actual_completed_metadata_evidence','scope_separation','physical_scope','physical_condition_hash_semantics','independent_metadata_closure'] if k in d],'references_preserved_no_role_coercion':True},'metadata_resolution_evidence':derived,'historical_negatives_and_uid_unknowns':'Preserved in the original accepted decision and its producer/reviewer evidence; no numerical certification from this catalog.'})
assert len(entries)==231 and not gaps,gaps
assert len({z['physical_case_id'] for z in entries})==231
counts=dict(collections.Counter(z['family_id'] for z in entries));assert counts==cp['accepted_per_family']
O=H/'root_stage1_accepted231_dynamic_ParaView_and_preview_catalog_metadata_only_1039';O.mkdir(exist_ok=False)
def put(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
put(O/'STAGE1_VISUAL_CASE_CATALOG_231.json',{'schema':'ds02.stage1.accepted-independent-case-dynamic-catalog.v1','at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'authoritative_checkpoint':ref(cpfile),'accepted_complete_independent_cases':231,'target_complete_independent_cases':336,'accepted_per_family':counts,'stage1_label':'视觉检查通过、数值精度未验收','main_scientific_payload_IO':False,'additional_scientific_jobs_or_case_credit':0,'entries':entries})
put(O/'actual-catalog231-coverage-review.json',{'authoritative_checkpoint':ref(cpfile),'catalog':ref(O/'STAGE1_VISUAL_CASE_CATALOG_231.json'),'unique_physical_case_count':231,'all231_have_existing_actual_dynamic_file':True,'all231_have_existing_completed_full_animation_report':True,'catalog_resolves_direct_refs_and_original_completed_producer_receipt_command_output_inventory':True,'catalog_entry_paths_discovered_from_actual_producer_metadata_not_case_alias_guessing':True,'older_source_frames_absent_field_preserved':sum(any(z['original_source_frames_field_absent_not_fabricated'] for z in e['complete_animation_reports']) for e in entries),'total_existing_preview_png_references':sum(len(e['preview_png_files']) for e in entries),'acceptance_count_and_roles_unchanged':True,'precision_and_unknown_UID_negatives_preserved_at_authoritative_decision':True,'main_scientific_payload_IO':False,'case_credit':0})
(O/'catalog-source.py').write_bytes(Path(__file__).read_bytes());paths=[str(p.relative_to(R)) for p in O.iterdir() if p.is_file()];subprocess.run(['git','add','--',*paths],cwd=R,check=True);subprocess.run(['git','commit','-q','-m','ds02: catalog231 accepted independent cases with actual ParaView dynamic and full animation entry points','--',*paths],cwd=R,check=True);print({'catalog':str(O/'STAGE1_VISUAL_CASE_CATALOG_231.json'),'cases':231,'counts':counts,'catalog_bytes':(O/'STAGE1_VISUAL_CASE_CATALOG_231.json').stat().st_size,'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()})
