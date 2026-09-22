import json,time
from pathlib import Path
import numpy as np,h5py
from scipy.spatial import cKDTree
repo=Path('/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab')
paths={x:repo/f'campaigns/core-v1/reproduction/float64-full835-collected/{x}/float64-rollout.h5' for x in ('ada','h200')}
with h5py.File(paths['ada'],'r') as f:
 ids=np.asarray(f['particle_id']); n=len(ids); times=np.asarray(f['time'])
h=float(0.01194127788262211); r2=(2*h)**2
# Fast equivalent for non-tie candidates: tree query k=self+64 and stable d2/id sort.
def fast_neighbors(x):
 tree=cKDTree(x); dist,idx=tree.query(x,k=65,distance_upper_bound=2*h,workers=1)
 idx=np.asarray(idx,dtype=np.int64).reshape(n,65); d2=np.asarray(dist,dtype=np.float64).reshape(n,65)**2
 rows=np.arange(n)[:,None]
 valid=(idx<n)&(idx!=rows)
 safe=np.where(valid,idx,0)
 key_id=np.where(valid,ids[safe],np.iinfo(np.int64).max)
 key_d2=np.where(valid,d2,np.inf)
 order=np.lexsort((key_id,key_d2),axis=1)
 take=np.take_along_axis(safe,order[:,:64],axis=1)
 ok=np.take_along_axis(valid,order[:,:64],axis=1)
 return np.where(ok,take,-1)
results=[]; t0=time.time()
with h5py.File(paths['ada'],'r') as fa,h5py.File(paths['h200'],'r') as fb:
 for fr in range(250):
  xa=np.asarray(fa['position'][fr]); xb=np.asarray(fb['position'][fr]);
  na=fast_neighbors(xa); nb=fast_neighbors(xb); raw=np.any(na!=nb,axis=1)
  if raw.any():
   setrows=0; first=None
   for i in np.flatnonzero(raw):
    if set(na[i])!=set(nb[i]): setrows+=1; first=first if first is not None else int(i)
   results.append({'frame':fr,'raw_rows':int(raw.sum()),'set_rows':setrows,'first_row':first})
   print(results[-1],flush=True)
  if fr%25==0: print('progress',fr,round(time.time()-t0,1),flush=True)
print('done',round(time.time()-t0,1),json.dumps(results))
Path('/tmp/neighbor-fast-scan-0-249.json').write_text(json.dumps({'results':results,'note':'fast k=65 scan; exact core_models recheck required for first hits'},indent=2))
