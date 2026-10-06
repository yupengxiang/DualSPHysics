from pathlib import Path
import json,hashlib,subprocess,datetime
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';O=H/'root_stage1_delegated114_bounded_failure_logs_and128_F4_priority10_independent_adoption_944';O.mkdir(exist_ok=False);load=lambda p:json.loads(Path(p).read_text());sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest();put=lambda p,v:Path(p).write_text(json.dumps(v,indent=2)+'\n');refs=[];packages=[]
for fn,cid,prefix in [('F3','c151d5b8','root_followup_114_'),('F6','fd05809b','root_followup_128_')]:
 W=Path('/home/jade/.codex/worktrees/ds-data-02-'+fn.lower()+'/DualSPHysics');S=next((W/'lagrangian-fluid-lab/campaigns/ds-data-02/families'/fn/'handoff_20261003').glob(prefix+'*'));commit=subprocess.check_output(['git','rev-parse',cid],cwd=W,text=True).strip();rel=S.relative_to(W)
 for name in subprocess.check_output(['git','ls-tree','-r','--name-only',commit,'--',str(rel)],cwd=W,text=True).splitlines():
  src=W/name;blob=subprocess.check_output(['git','show',commit+':'+name],cwd=W);assert src.read_bytes()==blob and src.suffix in ['.json','.py','.md'];dst=R/name;dst.parent.mkdir(parents=True,exist_ok=True);assert not dst.exists() or dst.read_bytes()==blob;dst.write_bytes(blob);refs.append({'path':str(dst),'sha256':sha(dst)})
 packages.append({'family':fn,'source_commit':commit,'package':str(R/rel)})
P114=Path(packages[0]['package']);worker=P114/'workers/nvme_render_successor.py';assert sha(worker)=='99551eec102a5cb596780cc30a2454eb5bb3d9697d89f49959bc62bd4ccef81a';s=worker.read_text();assert 'MAX_DIAGNOSTIC_TAIL_BYTES = 16 * 1024' in s and '_renderer_diagnostics(' in s and s.index('_write_json(path, evidence)',s.index('def _write_rejection'))<s.index('_remove_stage(stage_root)',s.index('def _write_rejection'))
entry=O/'registered_render_entry_with_bounded_diagnostics.py';entry.write_text('''from pathlib import Path
import argparse,json,runpy
p=argparse.ArgumentParser();p.add_argument('--worker',type=Path,required=True);p.add_argument('--request',type=Path,required=True);a=p.parse_args();q=json.loads(a.request.read_text());library=runpy.run_path(str(a.worker));result=library['execute_request'](q,authorized=True);summary={k:result.get(k) for k in ['status','reason','returncode','published_output_root','published_bytes','post_publish_home_floor_rechecked','renderer_diagnostics','stage_removed_after_rejection']};print(json.dumps(summary),flush=True);raise SystemExit(0 if result.get('status')=='completed' and result.get('post_publish_home_floor_rechecked') is True else 1)
''');compile(entry.read_text(),str(entry),'exec')
P128=Path(packages[1]['package']);selection=load(P128/'metadata/selection.json');assert len(selection['priority_cases'])==10 and len(selection['fallback_cases'])==5 and not set(selection['priority_cases'])&set(selection['fallback_cases']);cp=load(H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_123.json');ids={load(p).get('physical_case_id',load(p)['case_id']) for p in cp['accepted_decisions']};assert not set(selection['priority_cases']+selection['fallback_cases'])&ids;assert cp['accepted_per_family']['F4']==38;catalog=load(P128/'metadata/case-catalog.json');records=catalog['records'];records=[r for group in records.values() for r in group] if isinstance(records,dict) else records;assert len(records)==15
# The delegated source preparation holds only JSON/XML/PNG reference evidence.
verified=0
allowed={'.json','.xml','.xmf','.py','.md','.png'}
def walk(x):
 global verified
 if isinstance(x,dict):
  if 'path' in x and 'sha256' in x and x['path'] is not None and x['sha256'] is not None:
   p=Path(x['path'])
   if p.suffix.lower() in allowed:assert sha(p)==x['sha256'],str(p);verified+=1
  for v in x.values():walk(v)
 elif isinstance(x,list):
  for v in x:walk(v)
walk(catalog);walk(selection)
proof={'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'packages':packages,'adopted_files':refs,'source_adopted_byte_exact':True,'114_worker_sha256':sha(worker),'source114_review':'Diff from112 changes schema and bounded owned-log diagnostics only. Captures exactargv,pid/pgid,returncode/reason, rawtails<=16KiB each before stagecleanup and rewrites actualcleanup status. Success publication logic unchanged, original112/934 immutable.','new_registered_entry':{'path':str(entry),'sha256':sha(entry),'failure_exit1_success_only_completed_and_postfloorTrue':True,'bounded_failure_details_retained_in_registered_stdout':True},'source128_metadata_refs_verified':verified,'F4accepted':38,'F4priority_remaining':10,'F4fallback':5,'fallback_disabled_and_not_case_credit':True,'actual943_registered_ParaView_child_did_read_H5_via_XMF':True,'943_main_and_orchestrator_payload_IO':False,'943_frame0_success_not_fullcase_pass_or_rootcause_proof':True,'case_credit':0,'scientific_jobs_started':0};put(O/'actual114-and128-adoption-review.json',proof);(O/'adoption-source.py').write_bytes(Path(__file__).read_bytes());print({'adopted_files':len(refs),'metadata_refs_verified':verified,'worker114':sha(worker)})
