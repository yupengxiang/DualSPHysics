from pathlib import Path
import json,hashlib
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');H=R/'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003';old=next(H.glob('root*_856'));O=H/'root_stage1_F4_actual856_completed6_preserved_remaining16_CPU24_12GiB_admission_successor_923';O.mkdir(exist_ok=False)
load=lambda p:json.loads(Path(p).read_text()); sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
progress=load(old/'actual-progress.json');assert len(progress['results'])==6
complete={}
for row in progress['results']:
 rp=Path(row['actual_receipt']);r=load(rp);assert (r['status'],r['returncode'])==('completed',0);rr=rp.parent/'render/paraview-full-animation-report.json';a=load(rr);assert a['frames']==a['source_frames']==1201 and a['all_frames_rendered'];complete[row['case_id']]={'receipt':str(rp),'receipt_sha256':sha(rp),'report':str(rr),'report_sha256':sha(rr)}
cfg=load(old/'controller-config.json');queue=[p for p in cfg['queue'] if load(p)['case_id'] not in complete];assert len(queue)==16
cfg['queue']=queue;cfg['preserved_actual856_completed6']=complete;cfg['source_controller_config']={'path':str(old/'controller-config.json'),'sha256':sha(old/'controller-config.json')};cfg['retirement_proof']=str(O/'metadata-only-original856-retirement-proof.json');cfg['Home_additional_headroom_bytes']=2*1024**3
(O/'controller-config.json').write_text(json.dumps(cfg,indent=2)+'\n')
s=(old/'batch-controller.py').read_text().replace(str(old),str(O)).replace('-16*1024**3>=','-2*1024**3>=').replace("+'-CPU-capacity-repair1-root856'","+'-CPU-admission-successor-root923'")
s=s.replace("queue=cfg['queue'];rows=[]", "assert load(cfg['retirement_proof'])['same_metadata_handle_retired'];assert len(cfg['preserved_actual856_completed6'])==6;queue=cfg['queue'];rows=[]")
s=s.replace("'original_already_completed0':2", "'original_already_completed0':8").replace("'new_requested':22", "'new_requested':16").replace("'completed0':2+", "'completed0':8+").replace("'actual_full1201_render_pass_count':2+", "'actual_full1201_render_pass_count':8+")
s=s.replace("Path(__file__),L/'.venv/bin/python'", "Path(__file__),O/'controller-config.json',Path(cfg['retirement_proof']),L/'.venv/bin/python'")
(O/'batch-controller.py').write_text(s);compile(s,str(O/'batch-controller.py'),'exec')
(O/'preparation-source.py').write_bytes(Path(__file__).read_bytes());print({'root':str(O),'source_sha256':sha(O/'batch-controller.py'),'preserved6':len(complete),'future16':len(queue),'source_856_unchanged':True})
