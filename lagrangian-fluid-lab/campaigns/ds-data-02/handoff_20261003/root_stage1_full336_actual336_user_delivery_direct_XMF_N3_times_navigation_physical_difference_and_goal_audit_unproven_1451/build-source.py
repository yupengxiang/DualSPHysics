from pathlib import Path
import json,hashlib,datetime,subprocess,math,xml.etree.ElementTree as ET
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');H=R/'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');root=lambda n:next(H.glob(f'root*_{n:03d}'))
load=lambda p:json.loads(Path(p).read_text())
def sha(p):
 p=Path(p);assert p.suffix.lower() in {'.json','.xml','.xmf','.py','.md'};return hashlib.sha256(p.read_bytes()).hexdigest()
ref=lambda p:{'path':str(p),'sha256':sha(p)}
def verify(e):
 dg=sha(e['path']);decl=e.get('sha256') or e.get('declared_sha256');assert decl is None or dg==decl,e['path'];return {'path':e['path'],'sha256':dg,'source_declared_sha256':decl,'source_declared_SHA_field_absent':decl is None}
def put(p,j):
 with Path(p).open('x') as f:json.dump(j,f,ensure_ascii=False,indent=2);f.write('\n')
cpfile=H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_333.json';cp=load(cpfile);ip=root(1450)/'full336-current336-actual-final48-delivery-progress-index.json';idx=load(ip);assert idx['source_authoritative_checkpoint']==ref(cpfile) and cp['stage1_visual_accepted_complete_independent_cases']==336
paths={f:root(1261)/f'{f}-ACTUAL_FINAL48_DELIVERY_8_24_48.json' for f in ['F1','F4','F7']};paths.update(F2=Path(cp['actual_progress']['F2_final48_complete_actual_primary_delivery']['path']),F3=Path(cp['actual_progress']['F3_final48_complete_actual_primary_delivery']['path']),F5=Path(cp['actual_progress']['F5_final48_complete_actual_primary_bed_delivery']['path']),F6=root(1353)/'F6-FINAL48-COMPLETE-PARTICLE-RIGID-ACTUAL-PRIMARY-DELIVERY.json')
families={};cases=[];allids=[];checked=0
for family in ['F1','F2','F3','F4','F5','F6','F7']:
 p=paths[family];product=load(p);pr=ref(p)
 if 'main_independent_verification' in product:verify(product['main_independent_verification'])
 if family in ['F1','F4','F7']:mem={'frozen_first8_physical_case_ids':product['first8_physical_case_ids'],'actual_first24_physical_case_ids':product['first24_physical_case_ids'],'registered_final48_physical_case_ids':product['final48_physical_case_ids']};rk='cases'
 else:
  mem=product['membership'];rk={'F2':'accepted48_actual_primary_rows','F3':'accepted48_actual_primary_rows','F5':'accepted48_actual_primary_bed_rows','F6':'rows'}[family]
  if 'registered_final48_physical_case_ids' not in mem:mem={**mem,'registered_final48_physical_case_ids':mem['final48_physical_case_ids']}
 a,b,c=[mem[k] for k in ['frozen_first8_physical_case_ids','actual_first24_physical_case_ids','registered_final48_physical_case_ids']];assert len(a)==len(set(a))==8 and len(b)==len(set(b))==24 and len(c)==len(set(c))==48 and set(a)<=set(b)<=set(c);allids+=c
 rows=product[rk];assert len(rows)==cp['accepted_per_family'][family];rm={r['physical_case_id']:(i,r) for i,r in enumerate(rows)};assert len(rm)==len(rows) and set(rm)<=set(c);families[family]={'product':pr,'membership':{k:mem[k] for k in ['frozen_first8_physical_case_ids','actual_first24_physical_case_ids','registered_final48_physical_case_ids']},'accepted_actual_primary_cases':len(rows),'pending_cases':48-len(rows),'precision_status':'视觉检查通过、数值精度未验收'}
 for physical in c:
  current=next(r for r in idx['cases'] if r['family_id']==family and r['physical_case_id']==physical);entry={'family_id':family,'physical_case_id':physical,'runtime_case_alias':current['case_id'],'first8_member':physical in a,'first24_member':physical in b,'final48_member':True,'accepted_visual_decision':current.get('accepted_decision'),'precision_status':'视觉检查通过、数值精度未验收' if physical in rm else 'pending personal visual acceptance','Q_N':0,'Q_E':0}
  if physical not in rm:
   assert not current.get('accepted_decision');entry.update(status='completed full-frame integrity; pending delegated personal visual acceptance',actual_completed_fullframe_QI=current.get('actual_full836_QI') or current.get('actual_full801_QI'),primary_delivery=None);cases.append(entry);continue
  i,r=rm[physical];dr=current['accepted_decision'];verify(dr)
  if family in ['F1','F4','F7']:
   xr=r['primary_paraview_xmf'];mr=r['primary_xmf_manifest'];reports=r['primary_full_render_reports'];contacts=r['contact_sheets'];keys=r['key_frames'];accepted=r['accepted_visual_decision']
  elif family=='F6':
   v=r['accepted_visual_metadata'];xr=v['actual_xmf_xml'];mr=v['actual_xmf_manifest'];reports=[v['actual_render_report']];contacts=r['primary_refs']['png']['contacts'];keys=r['primary_refs']['png']['navigation_previews'];accepted=v['accepted_decision']
  else:
   xr=r['ParaView_open_XMF'];md=r['primary_metadata'];mr=md['xmf_manifest' if family=='F5' else 'XMF_manifest'];reports=[md['render_report']];accepted=r['accepted_visual_decision'];contacts=r[{'F2':'contacts17_actual_SHA_verified','F3':'contacts35_actual_SHA_verified','F5':'contacts34_actual_SHA_verified'}[family]];keys=r[{'F2':'navigation9_actual_SHA_verified','F3':'navigation_keys9_actual_SHA_verified','F5':'navigation9_actual_SHA_verified'}[family]]
  assert all(accepted[k]==dr[k] for k in ['path','sha256']);xf=verify(xr);mf=verify(mr);x=load(mf['path']);assert str(x['xdmf'])==xf['path'];xml=ET.parse(xf['path']);grids=xml.findall('.//Grid[@GridType="Uniform"]');times=[float(g.find('Time').get('Value')) for g in grids]
  assert len(grids)==x['frames'] and len(times)>=2 and times[0]==0 and all(math.isfinite(v) for v in times) and all(u<v for u,v in zip(times,times[1:]));assert times==x['actual_time_s']
  for g in grids:
   geom=g.find('Geometry');assert geom.get('GeometryType')=='XYZ' and geom.find('DataItem').get('Dimensions').split()[-1]=='3';vel=next(z for z in g.findall('Attribute') if z.get('Name').lower()=='velocity');assert vel.get('AttributeType')=='Vector' and vel.find('DataItem').get('Dimensions').split()[-1]=='3'
  rrefs=[]
  for e in reports:
   rr=verify(e);j=load(rr['path']);assert j['all_frames_rendered'] and j['frames']==len(times);rrefs.append(rr)
  assert contacts and keys
  for e in contacts+keys:
   f=Path(e['path']);assert f.is_relative_to(D) and f.suffix=='.png' and f.is_file() and not f.is_symlink();assert e.get('sha256') or e.get('declared_sha256') or e.get('producer_sha256');bs=e.get('bytes',e.get('bytes_stat'));assert bs is None or f.stat().st_size==bs
  def pngref(e):return {k:e[k] for k in ['path','sha256','declared_sha256','producer_sha256','bytes','bytes_stat','frame','actual_time_s'] if k in e}
  entry.update(status='accepted actual primary dynamic product',primary_delivery={'product':pr,'row_pointer':f'/{rk}/{i}','open_with_ParaView_XMF':xf,'manifest':mf,'full_animation_reports':rrefs,'frames':len(times),'particles':x['particles'],'actual_time_window_s':[times[0],times[-1]],'all_dynamic_XML_geometry_velocity_N3_and_manifest_times_directly_checked':True,'contacts':[pngref(e) for e in contacts],'navigation_keys':[pngref(e) for e in keys],'scope_initial_QA_rigid_bed_UID_runtime_loss_and_legacy_limits':'Preserved in the exact family product row at row_pointer; hashes are distinct named roles, and missing fields are not backfilled.'});cases.append(entry);checked+=1
assert len(cases)==len(allids)==len(set(allids))==336 and checked==336 and sum(e['primary_delivery'] is None for e in cases)==0
now=datetime.datetime.now(datetime.timezone.utc);O=H/'root_stage1_full336_actual336_user_delivery_direct_XMF_N3_times_navigation_physical_difference_and_goal_audit_unproven_1451';assert not O.exists();O.mkdir();proof=O/'all336-direct-primary-XMF-render-navigation-metadata-proof.json';put(proof,{'at_utc':now.isoformat(),'checkpoint':ref(cpfile),'current_index':ref(ip),'family_products':{f:ref(p) for f,p in paths.items()},'all336_selected_XMF_current_SHA_XML_fulltimes_geometry_velocity_N3_verified':True,'all336_report_frames_and_full_animation_flags_current_verified':True,'published_navigation_PNG_stat_only_current_reverified_no_new_PNG_hash_or_personal_review':True,'prior_main_actual_PNG_SHA_proofs_preserved_in_immutable_family_products':True,'membership_explicit_8_subset24_subset48_verified':True,'physical_parameter_distinction_audit_status':'pending delegated fresh194; unique IDs alone not a physical-distinction certificate','main_scientific_payload_IO':False,'case_credit':0,'Q_N':0,'Q_E':0})
put(O/'DS-DATA-02-ACTUAL-USER-DELIVERY-INDEX.json',{'schema':'ds02.main.actual-user-delivery-index.v1','at_utc':now.isoformat(),'authoritative_checkpoint':ref(cpfile),'main_direct_primary_verification':ref(proof),'target_cases':336,'accepted_actual_primary_cases':336,'pending_personal_cases':0,'actual_primary_file_bindings_complete':True,'delivery_complete':False,'goal_completion_audit_status':'unproven until case-bound physical distinction194 and explicit requirement230 audits are complete','families':families,'cases':cases,'precision_status':'视觉检查通过、数值精度未验收','Q_N':0,'Q_E':0,'new_case_credit':0,'scientific_payload_IO':False})
(O/'README.md').write_text('DS-DATA-02 全336份实际动态主文件入口：七族各48份视觉记录和主文件已经完成。使用 DS-DATA-02-ACTUAL-USER-DELIVERY-INDEX.json 按 family_id/physical_case_id 选择 primary_delivery.open_with_ParaView_XMF.path 在本服务器 ParaView 打开，contacts 和 navigation_keys 查看时序与关键事件，frozen8⊂actual24⊂final48 使用明确成员数组。主进程独立复核所有实际XML的完整时间域、XYZ几何和三分量速度、同案例完整渲染报告及PNG路径stat，原SHA与个人视觉审阅保留在不可变家族产品。特定UID遗漏、runtime原状态未知、历史发布缺失和床面/刚体限制按 product+row_pointer 查询完整原行，不以一个hash覆盖多个角色。视觉检查通过、数值精度未验收，Q-N/Q-E=0；精度、收敛、标签与外部验证待第二阶段。此入口只证明336份实际主文件绑定已齐，不宣告长期GOAL完成：还须将独立物理变化审计194中的不完整签名疑点按真实case-bound参数解决，并完成显式要求审计230。\n')
(O/'build-source.py').write_bytes(Path(__file__).read_bytes());paths0=[str(p.relative_to(R)) for p in O.iterdir()];subprocess.run(['git','add','--',*paths0],cwd=R,check=True);subprocess.run(['git','commit','-q','-m','DS02: deliver all336 actual ParaView primary files preserving physical-distinction and goal audit pending','--',*paths0],cwd=R,check=True);print(json.dumps({'actual_primary_rows':checked,'pending_personal':0,'output':str(O),'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()}))
