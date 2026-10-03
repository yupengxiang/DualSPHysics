"""Root F7 telemetry audit: interval counters, observed controls, no causal waiver."""
import argparse,csv,hashlib,importlib.util,json
from pathlib import Path
import numpy as np

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def parts(path,expected=6001,end=12.):
 with Path(path).open() as f:
  reader=csv.DictReader(f,delimiter=';');rows=[];footer=0
  for r in reader:
   if r.get('Part','').strip().isdigit():rows.append(r)
   else:footer+=1
 assert len(rows)==expected and [int(r['Part']) for r in rows]==list(range(expected)), 'native Parts must be exact and contiguous'
 t=np.array([float(r['TimeStep [s]']) for r in rows]);assert np.isfinite(t).all() and t[0]==0 and t[-1]>=end and np.all(np.diff(t)>0)
 def counts(k):
  a=np.array([int(r[k].replace(',','')) for r in rows],dtype=np.int64);assert np.all(a>=0),k;return a
 steps,clamps,excluded=map(counts,['Steps','DTsMin','NpOut']);assert np.all(steps[1:]>0)
 lo=np.array([float(r['DtMin [s]']) for r in rows[1:]]);hi=np.array([float(r['DtMax [s]']) for r in rows[1:]]);assert np.isfinite(lo).all() and np.isfinite(hi).all() and np.all(lo>0) and np.all(hi>=lo)
 active=int(steps[1:].sum());allsteps=int(steps.sum());allclamps=int(clamps.sum());mean=np.diff(t)/steps[1:]
 return {'frames':len(rows),'full_window_s':[float(t[0]),float(t[-1])],'ignored_non_part_footer_rows':footer,'sum_steps_active_intervals':active,'sum_steps_all_native_rows':allsteps,'initial_row_steps':int(steps[0]),'sum_DT_min_clamps_all_rows':allclamps,'symplectic_floor_incidence_fraction_all_rows':allclamps/(2*allsteps),'symplectic_floor_incidence_fraction_active_intervals':int(clamps[1:].sum())/(2*active),'initial_row_floor_adjustments':int(clamps[0]),'sum_NpOut_interval_counts_all_rows':int(excluded.sum()),'initial_row_NpOut':int(excluded[0]),'dt_global_min_s':float(lo.min()),'dt_global_max_s':float(hi.max()),'active_window_mean_dt_s':float((t[-1]-t[0])/active),'per_save_interval_mean_dt_quantiles_s':{str(p):float(v) for p,v in zip([.05,.5,.95],np.quantile(mean,[.05,.5,.95]))},'quantile_semantics':'save interval duration / its Steps; not distribution of every internal step','denominator_semantics':'Symplectic evaluates floor adjustment twice per integration step; initial native row reported separately; clamp fraction is not solver-time fraction'}

def run(config,output):
 c=json.loads(config.read_text());spec=importlib.util.spec_from_file_location('owner_metadata_readers_v2',c['metadata_helper']);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);result={};digests={}
 for role in ['baseline','variant']:
  row=c[role];rc=m.validate_execution_receipt(Path(row['receipt']));xml=m.parse_xml_controls(Path(row['xml']));log=m.parse_run_out(Path(row['log']));tele=parts(row['parts'])
  assert xml['step_algorithm_code']==2 and log['step_algorithm']=='Symplectic'
  assert log['mode']==xml['mode'], 'native XML/log mode mismatch'
  assert np.isclose(log['cfl_number'],xml['cfl_number'],rtol=1e-6,atol=1e-12)
  if xml['mode']=='fixed':assert np.isclose(log['fixed_dt'],xml['dt_fixed'],rtol=1e-6,atol=1e-12)
  result[role]={'controls':xml,'run_out':log,'telemetry':tele,'receipt_status':rc,'log_vs_active_step_count_matches':log['steps_of_simulation']==tele['sum_steps_active_intervals'],'log_vs_allrow_step_count_difference':None if log['steps_of_simulation'] is None else tele['sum_steps_all_native_rows']-log['steps_of_simulation'],'log_vs_allrow_floor_count_matches':log['dts_adjusted_to_dtmin']==tele['sum_DT_min_clamps_all_rows']}
  for p in row.values():digests[str(p)]=sha(p)
 b=result['baseline']['telemetry'];v=result['variant']['telemetry'];result.update(schema='ds02.f7.root.actual-timestep-audit.v3',active_step_ratio_variant_over_baseline=v['sum_steps_active_intervals']/b['sum_steps_active_intervals'],mean_dt_ratio_baseline_over_variant=b['active_window_mean_dt_s']/v['active_window_mean_dt_s'],interpretation='Measured adaptive/fixed modes and step refinement ratio are descriptive. Fixed-step refinement is not intrinsically invalid. Telemetry alone cannot identify the cause of retained transport divergence or establish convergence. Registered frozen transport/energy budgets remain required.',q_n_status='not_assessed',production_approval='none',source_sha256=digests,negative_paired_transport_report=c['paired_transport_report'],frozen_reference_budget=c['frozen_reference_budget'],owner_v1_v2_errata='v1 denominator and last-row NpOut corrected. v2 footer parsing rejected native footnotes; active/all-row step counts and initial sentinel are now separate. v2 claim that identical integration paradigms are necessary is not adopted. Historical43% spatial KE discrepancy is not negative kinetic energy.')
 for k in ['paired_transport_report','frozen_reference_budget','metadata_helper']:result['source_sha256'][c[k]]=sha(c[k])
 assert not output.exists();output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();run(a.config,a.output)
