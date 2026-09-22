import sys,json
from pathlib import Path
import numpy as np,h5py
repo=Path('/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab'); bundle=repo/'campaigns/core-v1/reproduction/ada-identical-h200-bundle-v3'; sys.path.insert(0,str(bundle/'code'))
from scripts.core_dataset import CoreDataset
from scripts.core_contract import State
from scripts import core_models
case='F3_DEV_08_a0p953125'; ds=CoreDataset(bundle/'dataset.json',bundle); known=ds.known_inputs(case)
paths={x:repo/f'campaigns/core-v1/reproduction/float64-full835-collected/{x}/float64-rollout.h5' for x in ('ada','h200')}
with h5py.File(paths['ada']) as f: ids=np.asarray(f['particle_id']); zones=np.asarray(f['particle_zone']); mass=np.asarray(f['mass'][:] if f['mass'].ndim==1 else f['mass'][0]); times=np.asarray(f['time'])
h=float(known.numerics['h_m']); rad2=(2*h)**2
for fr,row,ids_interest in [(255,11603,[9858,11309]),(257,8771,[7029,7069]),(284,7329,[6737,6741])]:
 out={'frame':fr,'row':row,'host':{}}
 for host,p in paths.items():
  with h5py.File(p) as f:
   pos=np.asarray(f['position'][fr]); vel=np.asarray(f['velocity'][fr]); valid=np.asarray(f['valid'][fr])
  st=State(float(times[fr]),pos,vel,ids,zones,mass,valid)
  n,_=core_models.neighbor_table(st,h,limit=64); rown=n[row]
  d2=np.sum((pos-pos[row])**2,axis=1)
  # Include self for easy rank; neighbor rank is rank-1.
  order=np.lexsort((ids,d2))
  rank={int(j):int(k) for k,j in enumerate(order)}
  out['host'][host]={
   'p_v_max':None,
   'neighbors_tail':rown[-5:].tolist(),
   'd2':{str(j):float(d2[j]) for j in ids_interest},
   'rank':{str(j):rank[j] for j in ids_interest},
   'cut64_with_self':float(d2[order[64]]), 'cut65_with_self':float(d2[order[65]]),
   'd2_delta_interest':float(d2[ids_interest[0]]-d2[ids_interest[1]]),
  }
 # state difference
 with h5py.File(paths['ada']) as fa, h5py.File(paths['h200']) as fb:
  pa=np.asarray(fa['position'][fr]); pb=np.asarray(fb['position'][fr]); va=np.asarray(fa['velocity'][fr]); vb=np.asarray(fb['velocity'][fr])
 out['position_diff_max']=float(np.max(np.abs(pa-pb))); out['velocity_diff_max']=float(np.max(np.abs(va-vb)))
 print(json.dumps(out,sort_keys=True))
