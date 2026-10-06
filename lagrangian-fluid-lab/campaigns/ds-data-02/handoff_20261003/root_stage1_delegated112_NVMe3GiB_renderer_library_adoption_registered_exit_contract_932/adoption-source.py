from pathlib import Path
import json,hashlib,subprocess,datetime
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');H=R/'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003';W=Path('/home/jade/.codex/worktrees/ds-data-02-f3/DualSPHysics');S=W/'lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/root_followup_112_f3_fresh110_publication_lifecycle_hardening_v1';O=H/'root_stage1_delegated112_NVMe3GiB_renderer_library_adoption_registered_exit_contract_932';O.mkdir(exist_ok=False);commit='2dec0f58bd4916671ad244f32a01909bc7300e51';rel=S.relative_to(W);sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest();refs=[]
for name in subprocess.check_output(['git','ls-tree','-r','--name-only',commit,'--',str(rel)],cwd=W,text=True).splitlines():
 p=W/name;blob=subprocess.check_output(['git','show',commit+':'+name],cwd=W);assert p.read_bytes()==blob and p.suffix in ['.py','.json','.md'];dst=R/name;dst.parent.mkdir(parents=True,exist_ok=True);assert not dst.exists() or dst.read_bytes()==blob;dst.write_bytes(blob);refs.append({'path':str(dst),'sha256':sha(dst)})
worker=R/rel/'workers/nvme_render_successor.py';src=worker.read_text();assert 'except BaseException' in src and 'post_publish_home_floor_rechecked' in src and 'live_reserved_bytes_excluding_own' in src
# Invoke the reviewed library directly. The delegated CLI always returns0
# even on a rejected publication, so it is deliberately not the runner entry.
entry='''from pathlib import Path
import argparse,json,runpy,sys
p=argparse.ArgumentParser();p.add_argument('--worker',type=Path,required=True);p.add_argument('--request',type=Path,required=True);a=p.parse_args()
q=json.loads(a.request.read_text());library=runpy.run_path(str(a.worker));result=library['execute_request'](q,authorized=True)
summary={k:result.get(k) for k in ['status','reason','returncode','published_output_root','published_bytes','post_publish_home_floor_rechecked']}
print(json.dumps(summary),flush=True)
# A library rejection is a failed registered task, not a completed renderer.
raise SystemExit(0 if result.get('status')=='completed' and result.get('post_publish_home_floor_rechecked') is True else 1)
'''
compile(entry,str(O/'registered_render_entry.py'),'exec');(O/'registered_render_entry.py').write_text(entry)
audit={'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'source_commit':commit,'adopted_byte_exact':True,'adopted_files':refs,'worker':str(worker),'worker_sha256':sha(worker),'library_publication_review':'Own child process group throughout render+publish; BaseException rollback; all recursive metadata/PVSM private paths rejected; verified derived copies; exact total inclpublishreceipt fixedpoint; live ledger lock excludes onlymatched own reservation; postrename Home500GiB recheck and rollback; 24GiB NVMe/100GiB floor and Home3GiB hardcap. Generic family/frame dimensions supplied by actualmanifest.','source_CLI_always_zero_on_rejected_result_not_used':True,'registered_entry':str(O/'registered_render_entry.py'),'registered_entry_sha256':sha(O/'registered_render_entry.py'),'registered_task_success_only_on_library_completed_and_postpublish_floor_pass':True,'old_source112_unmodified':True,'Root920_completed_first_not_rerun':True,'scientific_payload_not_read_or_hashed':True,'science_launches':0,'case_credit':0};(O/'actual112-library-and-entry-adoption-review.json').write_text(json.dumps(audit,indent=2)+'\n');(O/'adoption-source.py').write_bytes(Path(__file__).read_bytes());print({'adopted112_files':len(refs),'registered_entry_status_fixed':True,'library_worker_sha256':sha(worker)})
