"""Read real external windows and reject invalid accesses without altering data."""
import argparse, json, hashlib
from pathlib import Path
import numpy as np
from lagrangebench_v2_loader import read_window, LagrangeBenchError
p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--output',required=True);a=p.parse_args()
results=[]
for split,n in [('train',10001),('valid',5001),('test',5001)]:
 for start in [0,n//2,n-2]:
  w=read_window(a.root,split,'00000',start,start+2)
  assert w['position'].shape==(2,2708,2) and np.isfinite(w['position']).all()
  results.append({'split':split,'start':start,'stop':start+2,'shape':list(w['position'].shape),'position_sha256':hashlib.sha256(w['position'].tobytes()).hexdigest(),'particle_types':np.unique(w['particle_type']).tolist()})
negatives=[]
for label,args in [('out_of_bounds',('train','00000',10000,10002)),('unknown_split',('absent','00000',0,2)),('unsafe_identity',('train','../00000',0,2))]:
 try:read_window(a.root,*args)
 except LagrangeBenchError as e:negatives.append({'case':label,'rejected':True,'reason':str(e)})
 else:raise AssertionError(label+' accepted')
out=Path(a.output);out.parent.mkdir(parents=True,exist_ok=True)
with out.open('x') as f:json.dump({'status':'passed','windows':results,'negative_checks':negatives,'scope':'raw external 2D fields only; no physical identity or missing-field synthesis'},f,indent=2)
