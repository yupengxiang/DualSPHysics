from pathlib import Path
import sys,json,shutil,subprocess
root=Path('/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics');lab=root/'lagrangian-fluid-lab';stage=lab/'campaigns/ds-data-02/stage2';sys.path.insert(0,str(lab/'scripts'));import ds_data02_stage2_forward_request_v5 as f
f.V5_ROLES={'shared_dispatch_v6':'ds_data02_stage2_dispatch_v6.py','shared_strict_dispatch_v6':'ds_data02_strict_dispatch_v6.py','shared_runtime_v6':'ds_data02_runtime_v6.py','shared_runtime_v2':'ds_data02_runtime_v2.py','batch_runner_v6':'ds_data02_batch_runner_v6.py'}
f.SCHEMA='ds02.stage2.forward-diagnostic-request.v6-root-canonical'
binder=stage/'checkpoints/F2_REMOVAL_V6_ROOT_BINDER_001.py';assert not binder.exists();binder.write_bytes(Path(__file__).read_bytes())
source=stage/'requests/f2-s1-fine-native-removal-kinematics-v6-root/f2-s1-fine-native-removal-kinematics-v6-request.json';out=stage/'requests/f2-s1-fine-native-removal-kinematics-v6-root/f2-s1-fine-native-removal-kinematics-v6-primary-001-v6.json';r=f.build(source,out,shared_root=root,attempt_id='f2-s1-fine-native-removal-kinematics-v6-primary-001-v6');r['forward_v6']=r.pop('forward_v5');r['forward_runtime_note']='Root canonical shared v6 measured source pre/post hash diagnostic; actual saved-record event brackets, physical fate/dynamical impact UNKNOWN.'
trace=Path(shutil.which('strace')).resolve();assert trace.is_file();cmd=r['command'];cmd.insert(1,'-B');r['command']=[str(trace),'-f','-e','trace=open,openat','-o','{attempt_root}/os-open-trace-v6.log','--',*cmd]
for p in [trace,source,binder,lab/'scripts/ds_data02_stage2_forward_request_v5.py']:
 r['input_files'].append(str(p));r['input_sha256'][str(p)]=f.sha256_file(p)
r['input_files']=list(dict.fromkeys(r['input_files']));r['launch_commit']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip();r['shared_runtime_version']='v6';r['root_execution']={'single_same_parent_ledger_owner':True,'outer_OS_open_audit':True,'nested_strace':False,'exact_event_integration_time':'UNKNOWN_WITHIN_SAVED_BRACKET','no_cross_time_impulse_or_dynamics_bound':True};r['sha256']=f.canonical_sha(r)
for p in r['input_files']:assert f.sha256_file(p)==r['input_sha256'][p],p
out.write_text(json.dumps(r,ensure_ascii=False,sort_keys=True,indent=2)+'\n');print('READY',out,len(r['input_files']))
