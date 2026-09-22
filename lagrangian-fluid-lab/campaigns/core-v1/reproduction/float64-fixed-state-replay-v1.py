import sys,json,hashlib,importlib.util,time
from pathlib import Path
import numpy as np,h5py,torch
repo=Path('/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab')
bundle=repo/'campaigns/core-v1/reproduction/ada-identical-h200-bundle-v3'
# Load variant source snapshot without importing mutable workspace scripts.
runner=repo/'campaigns/core-v1/runtime/snapshots/ad9f659c202ec64ea5c5da71919992eb4989f4c173e44d95a7782409ee4cbfbf/lagrangian-fluid-lab/scripts/core_cross_host_canary_float64.py'
spec=importlib.util.spec_from_file_location('fixed_state_variant',runner); mod=importlib.util.module_from_spec(spec); sys.modules[spec.name]=mod; spec.loader.exec_module(mod)
mods=mod._load_bundle_modules(bundle)
cm=mods['core_models']; cc=mods['core_contract']; ds=mods['core_dataset'].CoreDataset(bundle/'dataset.json',bundle)
case='F3_DEV_08_a0p953125'; known=ds.known_inputs(case); times=np.asarray(ds.times(case)); dt=float(times[1]-times[0]); frame=257
paths={x:repo/f'campaigns/core-v1/reproduction/float64-full835-collected/{x}/float64-rollout.h5' for x in ('ada','h200')}
with h5py.File(paths['ada']) as f:
 ids=np.asarray(f['particle_id']); zones=np.asarray(f['particle_zone']); mass=np.asarray(f['mass'][:] if f['mass'].ndim==1 else f['mass'][0])
states={}
for host,p in paths.items():
 with h5py.File(p) as f:
  states[host]=cc.State(float(times[frame]),np.asarray(f['position'][frame]),np.asarray(f['velocity'][frame]),ids,zones,mass,np.asarray(f['valid'][frame]))
payload=torch.load(bundle/'models/checkpoint-001.pt',map_location='cpu',weights_only=False)
norm=cm.Normalization.from_dict(payload['normalization'])
model=cm.DualIncrementModel('graph_residual',hidden=64)
model.load_state_dict(payload.get('model_state',payload['state_dict']))
model.eval().to(dtype=torch.float64)
# Repeat exact same state. Capture input arrays and full prediction.
def run(st):
 args,prior,meta=mod.build_inference_inputs(state=st,known=known,dt=dt,core_models=cm,device=torch.device('cpu'),inference_dtype='float64')
 pred,trace=mod.predict_step(state=st,known=known,dt=dt,model=model,normalization=norm,device=torch.device('cpu'),chunk_size=256,core_models=cm,inference_dtype='float64')
 return args,prior,meta,pred,trace
out={'schema':'core.float64_fixed_state_replay.v1','case_id':case,'frame':frame,'device':'cpu','dtype':'float64','model_kind':'graph_residual','dt':dt,'results':{}}
for host in ('ada','h200'):
 t=time.time(); a1,p1,m1,y1,tr1=run(states[host]); a2,p2,m2,y2,tr2=run(states[host]);
 # args[0]=features, args[1]=position, args[2]=neighbors; prior tensor.
 out['results'][host]={
  'repeat_input_metadata_equal':m1==m2,
  'repeat_feature_equal':bool(torch.equal(a1[0],a2[0])),
  'repeat_position_equal':bool(torch.equal(a1[1],a2[1])),
  'repeat_neighbors_equal':bool(torch.equal(a1[2],a2[2])),
  'repeat_prior_equal':bool(torch.equal(p1,p2)),
  'repeat_prediction_equal':bool(np.array_equal(np.column_stack((y1.displacement,y1.delta_velocity)).astype(np.float64),np.column_stack((y2.displacement,y2.delta_velocity)).astype(np.float64))),
  'feature_digest':m1['promoted_features'],'neighbor_digest':m1['neighbors'],'prediction_digest':mod.array_digest(np.column_stack((y1.displacement,y1.delta_velocity))),
  'elapsed_seconds':time.time()-t,
 }
# Compare Ada/H200 state-derived CPU inputs/predictions. This is not a cross-GPU result.
a=out['results']['ada']; b=out['results']['h200'];
argsa,pra,ma,ya,_=run(states['ada']); argsb,prb,mb,yb,_=run(states['h200'])
pa=np.column_stack((ya.displacement,ya.delta_velocity)); pb=np.column_stack((yb.displacement,yb.delta_velocity))
out['cross_state_cpu']={
 'feature_equal':bool(torch.equal(argsa[0],argsb[0])),
 'position_equal':bool(torch.equal(argsa[1],argsb[1])),
 'neighbors_equal':bool(torch.equal(argsa[2],argsb[2])),
 'feature_max_abs':float((argsa[0]-argsb[0]).abs().max().item()),
 'position_max_abs':float((argsa[1]-argsb[1]).abs().max().item()),
 'prediction_max_abs':float(np.max(np.abs(pa-pb))),
 'prediction_nonzero':int(np.count_nonzero(pa!=pb)),
 'neighbor_changed_rows':int(torch.any(argsa[2]!=argsb[2],dim=1).sum().item()),
}
path=repo/'campaigns/core-v1/reproduction/float64-fixed-state-replay-v1.json'; path.write_text(json.dumps(out,indent=2,sort_keys=True)+'\n')
print(json.dumps(out,indent=2,sort_keys=True)); print('path',path,'sha256',hashlib.sha256(path.read_bytes()).hexdigest())
