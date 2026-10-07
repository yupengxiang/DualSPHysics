from pathlib import Path
import json,hashlib,xml.etree.ElementTree as ET
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');H=R/'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003';W=Path('/home/jade/.codex/worktrees/ds-data-02-f3/DualSPHysics');P=W/'lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003';load=lambda p:json.loads(Path(p).read_text());root=lambda n:next(H.glob(f'root*_{n}'))
def sha(p):
 p=Path(p);assert p.suffix in {'.json','.xml','.xmf'};return hashlib.sha256(p.read_bytes()).hexdigest()
def ref(p):return {'path':str(p),'sha256':sha(p)}
i=load(P/'root_followup_168_f3_assigned_f6_fulltime_floatinginfo_worker_v1/requests/f6-final48-fulltime-floatinginfo-disabled-request-index.json');coverage=load(P/'root_followup_167_f3_assigned_f6_rigid_state_delivery_coverage_v1/metadata/f6-final48-rigid-state-coverage.json');rows={x['physical_case_id']:x for x in coverage['cases']};last=load(root(1283)/'actual-lastF6-full241-own-UID-N3-state0-scope-readiness-with-quantified3fluid-omissions.json');out=[];errors=[]
for q in i['requests']:
 pid=q['case']['physical_case_id']
 try:
  snapshot=rows[pid]['particle_trajectory_metadata']['actual_manifest_metadata'];sp=snapshot.get('path');sourcepathmissing=bool(sp and not Path(sp).exists())
  def paths(v):
   if isinstance(v,dict):
    for x in v.values():yield from paths(x)
   elif isinstance(v,list):
    for x in v:yield from paths(x)
   elif isinstance(v,str) and v.startswith('/'):yield v
  manifests=[Path(x) for x in paths(rows[pid]) if Path(x).name=='manifest.json' and Path(x).is_file()]
  ad=rows[pid].get('accepted_decision')
  if ad and ad.get('path'):manifests.extend(Path(x) for x in paths(load(ad['path'])) if Path(x).name=='manifest.json' and Path(x).is_file())
  if pid==last['physical_case_id']:manifests.append(Path(next(x['metadata_report']['path'] for x in last['actual_producer_chain'] if x['stage']=='normal_n3_xmf')))
  manifests=list(dict.fromkeys(manifests));matching=[]
  for x in manifests:
   xm=load(x)
   if xm.get('physical_case_id')==pid and xm.get('frames')==241 and xm.get('native_receipt')==q['native']['receipt_path']:matching.append(x)
  assert len(matching)==1,(pid,'actualmanifest candidates',len(manifests),'matches',len(matching));mp=matching[0]
  m=load(mp);tp=Path(m['conversion_report']);assert sha(tp)==m['conversion_report_sha256'];t=load(tp);nr=t['source_provenance']['solver_receipt'];assert sha(nr['path'])==nr['sha256']==q['native']['receipt_sha256'];assert nr['path']==q['native']['receipt_path'];n=load(nr['path']);assert n['request']['physical_case_id']==pid and n['request']['physical_condition_sha256']==q['case']['physical_condition_sha256'] and (n['status'],n['returncode'])==('completed',0)
  assert m['frames']==t['frames']==241 and m['physical_case_id']==pid;times=m['actual_time_s'];assert len(times)==241 and times==[x['time'] for x in t['lifecycle']['frame_summary']];xml=Path(m['xdmf']);assert sha(xml)==m['xdmf_sha256'];grids=ET.parse(xml).findall('.//Grid[@GridType="Uniform"]');assert len(grids)==241 and times==[float(g.find('Time').get('Value')) for g in grids] and times[0]==0 and times[-1]>=12
  out.append({'physical_case_id':pid,'case_id':q['case']['case_id'],'native_receipt':nr,'manifest':ref(mp),'typed_report':ref(tp),'xdmf':ref(xml),'native_times_s':times,'native_time_tolerance_s':1e-6,'tolerance_basis':'Existing official PartVTK metadata six-decimal time rounding contract in Root023 audit_v2.py; explicit tolerance only for FloatingInfo/native time comparison, no resampling or numerical precision claim.','source167_manifest_path_snapshot_present_now':not sourcepathmissing,'source167_missing_path_snapshot':sp if sourcepathmissing else None,'own_completed_manifest_path_recovery_authority':ref(root(1283)/'actual-lastF6-full241-own-UID-N3-state0-scope-readiness-with-quantified3fluid-omissions.json') if sourcepathmissing else None})
 except Exception as e:errors.append({'physical_case_id':pid,'error':repr(e)})
p=Path('/tmp/ds02-F6-fulltime-own-native-time-binding-preflight.json');p.write_text(json.dumps({'cases':out,'errors':errors,'main_scientific_payload_IO':False},indent=2)+'\n');print({'bound':len(out),'error_count':len(errors),'first_errors':errors[:4],'output':str(p)})
