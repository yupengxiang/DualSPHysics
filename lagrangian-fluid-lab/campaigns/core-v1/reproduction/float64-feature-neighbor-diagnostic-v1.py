import sys, json, hashlib, time
from pathlib import Path
import numpy as np
import h5py

repo = Path('/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab')
bundle = repo/'campaigns/core-v1/reproduction/ada-identical-h200-bundle-v3'
# Fresh process imports are intentionally from the frozen bundle only.
sys.path.insert(0, str(bundle/'code'))
from scripts.core_dataset import CoreDataset
from scripts.core_contract import State
from scripts import core_models

manifest = bundle/'dataset.json'
dataset = CoreDataset(manifest, bundle)
case_id = 'F3_DEV_08_a0p953125'
known = dataset.known_inputs(case_id)
times = dataset.times(case_id)
h5_paths = {
    'ada': repo/'campaigns/core-v1/reproduction/float64-full835-collected/ada/float64-rollout.h5',
    'h200': repo/'campaigns/core-v1/reproduction/float64-full835-collected/h200/float64-rollout.h5',
}
frames = [0,1,2,3,4,5,10,15,20,25,50,75,100,150,200,250,270,275,280,281,282,283,284,285,286,300,350,358,359]
# Freeze identity arrays from the rollout's immutable initial axes, not future states.
with h5py.File(h5_paths['ada'], 'r') as _f0:
    ids = np.asarray(_f0['particle_id'])
    zones = np.asarray(_f0['particle_zone'])
    mass = np.asarray(_f0['mass'][:] if _f0['mass'].ndim == 1 else _f0['mass'][0])
    valid0 = np.asarray(_f0['valid'][0])
h = float(known.numerics['h_m'])
dt = float(times[1] - times[0])
print('bundle', bundle)
print('case', case_id, 'n', len(ids), 'h', h, 'dt', dt)
print('frames', frames)

# Align by H5 metadata and load one frame at a time.
all_out = {'case_id':case_id, 'bundle':str(bundle), 'h':h, 'dt':dt, 'frames':frames, 'hosts':{}}
for host, path in h5_paths.items():
    t0=time.time()
    print('HOST',host,'path',path, flush=True)
    with h5py.File(path, 'r') as f:
        pos_ds=f['position']; vel_ds=f['velocity']; time_ds=f['time']; valid_ds=f['valid']
        assert pos_ds.shape[1:] == (len(ids),3)
        assert vel_ds.shape == pos_ds.shape
        assert np.array_equal(np.asarray(f['particle_id']), ids), 'particle_id mismatch'
        assert np.array_equal(np.asarray(f['particle_zone']), zones), 'zone mismatch'
        assert np.array_equal(np.asarray(f['mass']), mass), 'mass mismatch'
        host_out=[]
        for frame in frames:
            pos=np.asarray(pos_ds[frame], dtype=np.float64)
            vel=np.asarray(vel_ds[frame], dtype=np.float64)
            valid=np.asarray(valid_ds[frame], dtype=bool)
            state=State(float(time_ds[frame]), pos, vel, ids, zones, mass, valid)
            feat, acc=core_models.node_features(state, known, dt)
            neigh, ndiag=core_models.neighbor_table(state, h, limit=64)
            host_out.append({'frame':frame, 'position':pos, 'velocity':vel,
                             'features':np.asarray(feat), 'acceleration':np.asarray(acc),
                             'neighbors':np.asarray(neigh, dtype=np.int64),
                             'neighbor_diagnostics':ndiag})
            print('  ',frame,'feature',feat.shape,'neighbors',neigh.shape, 'elapsed',round(time.time()-t0,2), flush=True)
    all_out['hosts'][host]=host_out

# Compare host snapshots.
def arrdiff(a,b):
    d=np.asarray(a,dtype=np.float64)-np.asarray(b,dtype=np.float64)
    finite=np.isfinite(d)
    if not finite.all():
        return {'max_abs':None,'mean_abs':None,'nonfinite':int((~finite).sum()),'nonzero':int(np.count_nonzero(a!=b))}
    absd=np.abs(d)
    return {'max_abs':float(absd.max(initial=0.0)), 'mean_abs':float(absd.mean()),
            'nonzero':int(np.count_nonzero(a!=b)), 'size':int(d.size)}

def neighbor_diff(na, nb, pos_a, pos_b):
    raw_rows=np.any(na!=nb,axis=1)
    set_rows=[]; order_rows=[]
    first_detail=None
    radius2=(2.0*h)**2
    for i in np.flatnonzero(raw_rows):
        aa=tuple(int(x) for x in na[i] if int(x)>=0)
        bb=tuple(int(x) for x in nb[i] if int(x)>=0)
        if set(aa)!=set(bb):
            set_rows.append(int(i))
            if first_detail is None:
                union=sorted(set(aa)|set(bb))
                # Distances are computed from the actual stored positions, to identify whether
                # the disagreement is close to the registered radius/truncation boundary.
                pa=pos_a[i]; pb=pos_b[i]
                margins=[]
                for j in union:
                    da=float(np.sum((pos_a[j]-pa)**2)); db=float(np.sum((pos_b[j]-pb)**2))
                    margins.append({'id':j,'d2_ada':da,'d2_h200':db,'margin_ada':da-radius2,'margin_h200':db-radius2})
                first_detail={'row':int(i),'ada_neighbors':list(aa),'h200_neighbors':list(bb),
                              'union_radius_margins':margins}
        else:
            order_rows.append(int(i))
    return {'raw_rows':int(raw_rows.sum()), 'set_rows':len(set_rows),
            'order_only_rows':len(order_rows), 'first_set_detail':first_detail,
            'first_raw_row':int(np.flatnonzero(raw_rows)[0]) if raw_rows.any() else None,
            'first_order_only_row':order_rows[0] if order_rows else None}

ada=all_out['hosts']['ada']; h200=all_out['hosts']['h200']
summary=[]
for ia, ib in zip(ada,h200):
    assert ia['frame']==ib['frame']
    frame=ia['frame']
    nd=neighbor_diff(ia['neighbors'],ib['neighbors'],ia['position'],ib['position'])
    rec={'frame':frame,
         'position':arrdiff(ia['position'],ib['position']),
         'velocity':arrdiff(ia['velocity'],ib['velocity']),
         'features':arrdiff(ia['features'],ib['features']),
         'acceleration':arrdiff(ia['acceleration'],ib['acceleration']),
         'neighbors':nd,
         'feature_diff_rows':int(np.any(ia['features']!=ib['features'],axis=1).sum()),
         'feature_diff_cols':np.flatnonzero(np.any(ia['features']!=ib['features'],axis=0)).tolist(),
         'feature_first_row':int(np.flatnonzero(np.any(ia['features']!=ib['features'],axis=1))[0]) if np.any(ia['features']!=ib['features']) else None}
    summary.append(rec)
    print('SUMMARY',json.dumps(rec, sort_keys=True), flush=True)
all_out['summary']=summary
# Drop full arrays before writing a compact evidence artifact.
for host in list(all_out['hosts']):
    del all_out['hosts'][host]
out_path=Path('/tmp/float64-full835-feature-neighbor-diagnostic-v1.json')
out_path.write_text(json.dumps(all_out, indent=2, sort_keys=True))
print('WROTE',out_path)
