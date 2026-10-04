import argparse,csv,json,hashlib
from pathlib import Path
import numpy as np
from scipy.spatial import cKDTree
p=argparse.ArgumentParser();p.add_argument('--qa',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
qa=json.loads(a.qa.read_text());results=[]
for row in qa['cases']:
 source=Path(row['official_csv']);assert sha(source)==row['official_csv_sha256'];dp=.01 if '_ECC_' in row['case_id'] else .02
 with source.open() as f:
  for line in f:
   h=next(csv.reader([line]))
   if 'Pos.x [m]' in h and 'Type' in h:break
  names=['Pos.x [m]','Pos.y [m]','Pos.z [m]','Type','Idp'];x=np.loadtxt(f,delimiter=',',usecols=[h.index(v) for v in names],ndmin=2)
 assert x.shape==(row['native_particles'],5) and np.isfinite(x).all()
 fluid=x[x[:,3]==3];fixed=x[x[:,3]==0];assert len(fluid)==row['native_fluid'];dist,nearest=cKDTree(fixed[:,:3]).query(fluid[:,:3],k=1)
 imin=int(np.argmin(dist));results.append({'case_id':row['case_id'],'source_csv':str(source),'source_csv_sha256':sha(source),'dp_m':dp,'fluid_count':len(fluid),'fixed_count':len(fixed),'actual_global_min_distance_m':float(dist.min()),'minimum_distance_dp':float(dist.min()/dp),'fluid_counts_below_distance_dp':{str(t):int(np.sum(dist<t*dp)) for t in (1.0,.999999,.9999,.9,.5,.1,1e-6)},'closest_fluid':{'id':int(fluid[imin,4]),'position':fluid[imin,:3].tolist()},'closest_fixed':{'id':int(fixed[nearest[imin],4]),'position':fixed[nearest[imin],:3].tolist()},'source_unchanged':sha(source)==row['official_csv_sha256'],'independent_case_increment':0})
assert not a.output.exists();a.output.write_text(json.dumps({'schema':'ds02.root.actual-native-initial-global-clearance-diagnostic.v1','status':'actual-diagnostic','cases':results,'interpretation':'Global nearest neighbor distances from actual official QA031 CSV. This diagnostic does not relax a gate or accept a case.','precision_accepted':False,'count_increment':0},indent=2)+'\n')
