from pathlib import Path
import json,hashlib,argparse
import numpy as np
import h5py
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for c in iter(lambda:f.read(1048576),b''):h.update(c)
 return h.hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('--binding',required=True);p.add_argument('--output',required=True);args=p.parse_args();b=json.loads(Path(args.binding).read_text())
 assert sha(b['trajectory_h5'])==b['trajectory_h5_sha256'];assert sha(b['motion_file'])==b['motion_file_sha256']
 control=np.loadtxt(b['motion_file']);assert control.ndim==2 and control.shape[1]==2 and np.isfinite(control).all() and np.all(np.diff(control[:,0])>0)
 rows=[]
 with h5py.File(b['trajectory_h5'],'r') as f:
  times=np.asarray(f['time']).reshape(-1);assert len(times)==801
  ty=np.asarray(f['type'][0]).reshape(-1);valid=np.asarray(f['valid'][0]).reshape(-1).astype(bool);ids=np.asarray(f['particle_id']).reshape(-1);x0=np.asarray(f['position'][0],dtype=np.float64)
  moving=valid&(ty==1);fluid=valid&(ty==3);assert moving.sum()==4210 and fluid.sum()==31658 and np.unique(ids).size==194427
  prescribed=np.interp(times,control[:,0],control[:,1]);prescribed-=prescribed[0]
  for i,t in enumerate(times):
   x=np.asarray(f['position'][i],dtype=np.float64);va=np.asarray(f['valid'][i]).reshape(-1).astype(bool);types=np.asarray(f['type'][i]).reshape(-1);assert va[moving|fluid].all() and np.all(types[moving]==1) and np.all(types[fluid]==3) and np.isfinite(x[moving|fluid]).all()
   dx=x[moving]-x0[moving];fm=x[fluid];fd=fm-x0[fluid]
   rows.append({'frame':i,'time_s':float(t),'prescribed_dx_m':float(prescribed[i]),'moving_mean_dx_m':float(dx[:,0].mean()),'moving_max_abs_displacement_m':float(np.max(np.linalg.norm(dx,axis=1))),'moving_x_uniform_spread_m':float(np.ptp(dx[:,0])),'moving_yz_abs_change_max_m':float(np.abs(dx[:,1:]).max()),'moving_max_abs_x_minus_prescribed_m':float(np.abs(dx[:,0]-prescribed[i]).max()),'fluid_max_displacement_m':float(np.max(np.linalg.norm(fd,axis=1))),'fluid_x_max_m':float(fm[:,0].max()),'fluid_z_max_m':float(fm[:,2].max()),'fluid_z_min_m':float(fm[:,2].min())})
 report={'schema':'ds02.root.f5.actual-full801-motion-trajectory-diagnostic.v1','status':'completed','diagnostic_only':True,'inputs':b,'control_rows':int(len(control)),'control_time_range_s':[float(control[0,0]),float(control[-1,0])],'control_x_range_m':[float(control[:,1].min()),float(control[:,1].max())],'control_x_peak_to_peak_m':float(np.ptp(control[:,1])),'prescribed_saved_time_peak_to_peak_m':float(np.ptp(prescribed)),'moving_saved_displacement_max_m':max(r['moving_max_abs_displacement_m'] for r in rows),'moving_x_vs_prescribed_error_max_m':max(r['moving_max_abs_x_minus_prescribed_m'] for r in rows),'fluid_saved_displacement_max_m':max(r['fluid_max_displacement_m'] for r in rows),'frames':rows,'science_inputs_read_only':True,'full_visual_runup_event_not_granted':True,'precision_not_granted':True,'case_increment':0}
 out=Path(args.output);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({k:v for k,v in report.items() if k not in ['frames','inputs']}))
if __name__=='__main__':main()
