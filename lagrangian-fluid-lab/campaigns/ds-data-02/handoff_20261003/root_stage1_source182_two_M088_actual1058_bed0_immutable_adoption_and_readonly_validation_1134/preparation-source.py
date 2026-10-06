from pathlib import Path
import subprocess,json,hashlib,datetime
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');W=Path('/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics');H=R/'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003'
rel=Path('lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_182_f5_m088_bed_to_render_disabled_v1');commit='c2ce518aee61db9f0381ce3d53223739bee6cb2f';O=H/'root_stage1_source182_two_M088_actual1058_bed0_immutable_adoption_and_readonly_validation_1134';assert not O.exists()
files=subprocess.check_output(['git','ls-tree','-r','--name-only',commit,'--',str(rel)],cwd=R,text=True).splitlines();assert len(files)==13
rows=[]
for f in files:
 data=subprocess.check_output(['git','show',f'{commit}:{f}'],cwd=R);assert (W/f).read_bytes()==data
 p=R/f;assert not p.exists();p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
 rows.append({'path':f,'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)})
before={f:hashlib.sha256((W/f).read_bytes()).hexdigest() for f in files}
v=subprocess.run(['python3',str(W/rel/'scripts/validate_fresh182.py')],capture_output=True,text=True);assert v.returncode==0,v.stderr
assert before=={f:hashlib.sha256((W/f).read_bytes()).hexdigest() for f in files}
assert all(hashlib.sha256((R/r['path']).read_bytes()).hexdigest()==r['sha256'] for r in rows)
O.mkdir();review={'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'source_commit':commit,'source_package':str(W/rel),'adopted_package':str(R/rel),'files':rows,'validator_stdout':v.stdout,'validator_stderr':v.stderr,'validator_returncode':v.returncode,'validator_run_against_original_source':True,'all_source_bytes_unchanged':True,'adopted_git_blob_byte_exact':True,'scientific_payload_IO':False,'case_credit':0,'actual_scope_roles_preserved':True,'visual_acceptance_pending':True}
(O/'source182-byte-exact-adoption-and-readonly-validation.json').write_text(json.dumps(review,ensure_ascii=False,indent=2)+'\n');(O/'preparation-source.py').write_bytes(Path(__file__).read_bytes())
paths=files+[str(p.relative_to(R)) for p in O.iterdir()];subprocess.run(['git','add','--',*paths],cwd=R,check=True);subprocess.run(['git','commit','-q','-m','ds02: adopt two M088 actual bed to render handoffs without altering source bytes','--',*paths],cwd=R,check=True)
print({'files':len(files),'validator':v.stdout,'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip(),'proof':str(O)})
