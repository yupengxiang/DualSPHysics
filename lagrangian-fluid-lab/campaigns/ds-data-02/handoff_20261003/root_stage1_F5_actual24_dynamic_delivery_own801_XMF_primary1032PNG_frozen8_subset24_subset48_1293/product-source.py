from pathlib import Path
import json,hashlib,datetime,sys,subprocess,xml.etree.ElementTree as ET
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');H=R/'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003';root=lambda n:next(H.glob(f'root*_{n}'));load=lambda p:json.loads(Path(p).read_text())
def sha(p):
 p=Path(p);assert p.suffix.lower() in {'.json','.xml','.xmf','.png','.py','.md'};return hashlib.sha256(p.read_bytes()).hexdigest()
def ref(p):return {'path':str(p),'sha256':sha(p)}
def put(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
def paths(v):
 if isinstance(v,dict):
  for x in v.values():yield from paths(x)
 elif isinstance(v,list):
  for x in v:yield from paths(x)
 elif isinstance(v,str) and v.startswith('/'):yield v
cpnum,idxroot,outnum=map(int,sys.argv[1:]);cpfile=H/f'ROOT_LIVE_RESUMPTION_CHECKPOINT_{cpnum:03d}.json';cp=load(cpfile);assert cp['accepted_per_family']['F5']==24 and cp['stage1_visual_accepted_complete_independent_cases']==len(cp['accepted_decisions']);ips=list(root(idxroot).glob('full336-current*-actual-final48-delivery-progress-index.json'));assert len(ips)==1;ip=ips[0];idx=load(ip);assert idx['source_authoritative_checkpoint']==ref(cpfile);rows=[r for r in idx['cases'] if r['family_id']=='F5' and r.get('accepted_decision')];final=[r['physical_case_id'] for r in idx['cases'] if r['family_id']=='F5'];assert len(rows)==24 and len(set(final))==len(final)==48;frozen=root(1093)/'FIRST8_PER_FAMILY_STAGE1_SUBSET56.json';eight=[]
for e in load(frozen)['cases_by_family']['F5']:
 assert sha(e['path'])==e['sha256'];d=load(e['path']);eight.append(d['physical_case_id'])
assert len(set(eight))==8 and set(eight)<=set(r['physical_case_id'] for r in rows)<=set(final)
primary=[];legacy=[];nc=0;nk=0;canonical_conditions=[];native_scope_recoveries=[]
for row in rows:
 pid=row['physical_case_id'];ad=row['accepted_decision'];assert sha(ad['path'])==ad['sha256'] and ad['path'] in cp['accepted_decisions'];d=load(ad['path']);assert d['physical_case_id']==pid;allpaths=list(dict.fromkeys(paths(d)));reports=[p for p in allpaths if Path(p).name=='paraview-full-animation-report.json'];mans=[p for p in allpaths if Path(p).name=='manifest.json'];pairs=[]
 for rp in reports:
  rr=load(rp)
  for mp in mans:
   if rr.get('manifest_sha256')==sha(mp):pairs.append((rp,mp))
 assert len(pairs)==1,(pid,pairs);rp,mp=pairs[0];report=load(rp);manifest=load(mp)
 typedreports=[p for p in allpaths if Path(p).name=='conversion-report.json'];candidates=[]
 for tp in typedreports:
  tr=load(tp);nr=tr.get('source_provenance',{}).get('solver_receipt')
  if not nr:continue
  assert sha(nr['path'])==nr['sha256'];nd=load(nr['path'])
  if nd['request'].get('physical_case_id')==pid and (nd['status'],nd.get('returncode'))==('completed',0):candidates.append((tp,nr,nd))
 assert len(candidates)==1,(pid,'native producer candidates',len(candidates));tp,nr,nd=candidates[0];native_scope={'sha256':nd['request']['physical_condition_sha256'],'role':'actual completed native request physical_condition_sha256, bound by own typed producer solver_receipt','actual_native_receipt':nr,'typed_report_authority':ref(tp)};canonical_conditions.append(native_scope['sha256']);assert nd['request']['case_id']==row['case_id'] and d['physical_condition_sha256']==native_scope['sha256']
 if row['native_request_scope']['sha256'] is not None:assert row['native_request_scope']['sha256']==native_scope['sha256']
 else:native_scope_recoveries.append({'physical_case_id':pid,'prior_index_scope_preserved':row['native_request_scope'],'own_completed_native_scope':native_scope})
 xml=Path(manifest['xdmf']);assert sha(xml)==manifest['xdmf_sha256']==report['xdmf_sha256_before']==report['xdmf_sha256_after'];assert report['frames']==report['source_frames']==manifest['frames']==801 and report['all_frames_rendered'] and report['actual_times_preserved_exactly'] and report['native_identity_axis_preserved'] and report['nonfinite_active_states']==0;assert report['source_h5_sha256']==manifest['source_h5_sha256'] and report['source_h5_read_only'];assert manifest['fields']['position']['shape']==manifest['fields']['velocity']['shape']==[801,194427,3]
 grids=ET.parse(xml).findall('.//Grid[@GridType="Uniform"]');times=manifest['actual_time_s'];assert len(grids)==len(times)==801 and times==[float(g.find('Time').get('Value')) for g in grids];assert times[0]==0 and times[-1]>=16 and all(a<b for a,b in zip(times,times[1:]))
 for g in grids:
  assert g.find('Geometry').get('GeometryType')=='XYZ' and g.find('Geometry/DataItem').get('Dimensions')=='194427 3';a=next(a for a in g.findall('Attribute') if a.get('Name')=='velocity');assert a.get('AttributeType')=='Vector' and a.find('DataItem').get('Dimensions')=='194427 3'
 contacts=[Path(p) for p in report['outputs']['contact_sheets']];assert len(contacts)==34 and [p.name for p in contacts]==[f'all_frames_{i:03d}.png' for i in range(34)];keys=[Path(report['outputs']['frames_dir'])/f'frame_{i:04d}.png' for i in range(0,801,100)];assert sorted(p.name for p in Path(report['outputs']['frames_dir']).glob('frame_*.png'))==[f'frame_{i:04d}.png' for i in range(801)]
 pubpath=Path(rp).parent/'render-publish-receipt.json';pub=load(pubpath) if pubpath.exists() else None;published={x['relative_path']:x for x in pub['files_excluding_receipt']} if pub else {}
 if pub:assert pub['status']=='published_after_atomic_rename' and pub['report_sha256_after_rebind']==sha(rp)
 vis=[]
 for p in contacts+keys:
  assert p.is_file();r=ref(p);r['bytes']=p.stat().st_size
  if pub:
   a=published[str(p.relative_to(Path(pub['published_output_root'])))];assert r['sha256']==a['sha256'] and r['bytes']==a['bytes']
  vis.append(r)
 nc+=len(contacts);nk+=len(keys)
 if not pub:legacy.append({'physical_case_id':pid,'actual_render_report':ref(rp),'publish_receipt_field_or_file_present':False,'authority':'Completed case-local render output bound by immutable accepted decision/report; no atomic-publish claim inferred.'})
 primary.append({'family_id':'F5','case_id':row['case_id'],'physical_case_id':pid,'first8':pid in eight,'accepted_decision':ad,'canonical_actual_native_request_scope':native_scope,'source_index_native_scope_snapshot_preserved':row['native_request_scope'],'render_report':ref(rp),'xmf_manifest':ref(mp),'xdmf':ref(xml),'frames':801,'particles':194427,'actual_time_window_s':[times[0],times[-1]],'all801_N3_actual_times_metadata_verified':True,'own_report_manifest_XMF_sha_bindings_verified':True,'actual_manifest_physical_case_id_field':{'present':'physical_case_id' in manifest,'value':manifest.get('physical_case_id')},'actual_manifest_scope_fields':{k:{'present':k in manifest,'value':manifest.get(k)} for k in ['physical_condition_sha256','canonical_physical_condition_sha256','canonical_source_physical_condition_sha256','source_plan_condition_sha256','source_plan_physical_condition_sha256','source_h5_physical_condition_sha256']},'contact_sheets':vis[:34],'navigation_keyframes':vis[34:],'keyframe_selection_note':'Existing case-local frames0..800 step100, bound to the accepted full animation; this product adds navigation references and grants no new personal visual review.','atomic_publish_receipt':ref(pubpath) if pub else None,'source_case_id_reuse_not_independent_identity':True,'original_visual_precision_negatives_and_limits_authority':ad,'new_case_credit':0})
assert len(set(canonical_conditions))==24 and len(primary)==24 and nc==816 and nk==216
O=H/f'root_stage1_F5_actual24_dynamic_delivery_own801_XMF_primary1032PNG_frozen8_subset24_subset48_{outnum}';assert not list(H.glob(f'root*_{outnum}'));O.mkdir();fp=O/'F5-ACTUAL_FIRST24_DYNAMIC_DELIVERY.json';put(fp,{'schema':'ds02.main.F5.actual-first24-dynamic-delivery.v1','at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'family_id':'F5','stable_predecessor_acceptance_authority':ref(cpfile),'source_full336_current_index':ref(ip),'frozen_first8_authority':ref(frozen),'frozen_first8_physical_case_ids':eight,'actual_first24_physical_case_ids':[r['physical_case_id'] for r in rows],'registered_final48_physical_case_ids':final,'actual_first24_count':24,'first8_subset_actual24_subset_registered48':True,'canonical_native_request_conditions_distinct':len(set(canonical_conditions)),'source_index_null_native_scope_recoveries':native_scope_recoveries,'actual_own_primary_rows':primary,'primary_contacts':nc,'primary_navigation_keys':nk,'legacy_direct_render_publish_absence_preserved':legacy,'new_case_credit':0,'new_visual_review':False,'main_scientific_payload_IO':False,'precision_status':'视觉检查通过、数值精度未验收','Q_N':0,'Q_E':0});(O/'README.md').write_text('F5 实际24例动态交付索引，冻结8例包含于实际24例，实际24例包含于注册最终48例。每例独立物理ID、已有验收决定、真实原生输入条件、801帧三维XMF、34张时序拼图和9张导航关键帧均逐一绑定。历史母case_id复用不用于去重；旧直接渲染没有原子发布收据的情况明确保留，不伪造字段。新增导航引用不新增视觉审核或案例credit。保留既有弱响应、几何/精度负例、床面诊断限制与 Q-N/Q-E=0。\n');(O/'product-source.py').write_bytes(Path(__file__).read_bytes());subprocess.run(['git','add','--',str(O.relative_to(R))],cwd=R,check=True);subprocess.run(['git','commit','-q','-m','ds02: deliver F5 actual24 full801 XMF with frozen8 membership and own preview bindings','--',str(O.relative_to(R))],cwd=R,check=True);print({'manifest':ref(fp),'primary_contacts':nc,'primary_keys':nk,'legacy_publish_absences':len(legacy),'new_case_credit':0})
