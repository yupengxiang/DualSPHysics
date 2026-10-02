"""Full native F4 macro series; preserve source extrema and unknown identities."""
import argparse,json
from pathlib import Path
import h5py,numpy as np
from ds_data02_native_labels import digest

def aggregate(position,velocity,mass,selected):
    p,v,m=position[selected],velocity[selected],mass[selected]
    if len(m)==0:raise ValueError('No valid source mass')
    if not np.isfinite(p).all() or not np.isfinite(v).all() or not np.isfinite(m).all() or np.any(m<=0):raise ValueError('Active native source contains invalid values')
    total=float(m.sum());return [total,*(np.sum(p*m[:,None],axis=0)/total).tolist(),*np.sum(v*m[:,None],axis=0).tolist(),float(.5*np.sum(m*np.sum(v*v,axis=1))),*(p.max(axis=0)-p.min(axis=0)).tolist()]

def series(source,owner,output):
    if output.exists():raise FileExistsError(output)
    before=digest(source);meta=json.loads(owner.read_text());mapping=meta['typed_identity_binding']['fluid_mkfluid_to_native_mk'];binding=meta['physical_binding'];labels=binding['initial_state']['source_labels'];groups={labels['mkfluid:'+k]:v for k,v in mapping.items()};data={key:[] for key in ['all_fluid']+sorted(groups)};unknown=[]
    with h5py.File(source,'r') as h:
        times=h['time'][:];assert times[0]==0 and times[-1]>=1.2 and np.isfinite(times).all() and np.all(np.diff(times)>0);fluid=h['initial_type'][:]==3;mk=h['initial_mk'][:];initial_mass=h['initial_mass'][:];physical=str(h.attrs['physical_condition_sha256']);assert physical==meta['physical_binding_sha256']
        for frame in range(len(times)):
            valid=h['valid'][frame,:].astype(bool);active=fluid & valid;p=h['position'][frame,:].astype(np.float64);v=h['velocity'][frame,:].astype(np.float64);m=h['mass'][frame,:].astype(np.float64);unknown.append(float(initial_mass[fluid & ~valid].sum()));data['all_fluid'].append(aggregate(p,v,m,active))
            for key,marker in groups.items():data[key].append(aggregate(p,v,m,active & (mk==marker)))
    assert digest(source)==before
    result={'schema':'ds02.f4.centered-full-macro-series.v1','source':str(source),'source_sha256':before,'owner':str(owner),'owner_sha256':digest(owner),'physical_binding_sha256':physical,'time_s':times.tolist(),'operators':['active_mass_kg','com_x_m','com_y_m','com_z_m','momentum_x_kg_m_s','momentum_y_kg_m_s','momentum_z_kg_m_s','kinetic_energy_j','source_extreme_spread_x_m','source_extreme_spread_y_m','source_extreme_spread_z_m'],'source_series':data,'unknown_native_exclusion_mass_kg':unknown,'q_n_status':'not_assessed','limitations':['Full source extrema retained; no percentile substitution','Macro curves only; contact, finite-chord transport, reconstruction and independent time/save comparisons separately required']};output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'frames':len(times),'source':str(source),'unknown_mass_final_kg':unknown[-1],'q_n_status':'not_assessed'}))
if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ['source','owner','output']:p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args();series(a.source,a.owner,a.output)
