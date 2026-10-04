"""Evaluate all registered native F5 probes over the complete support."""
import argparse,importlib.util,json
from pathlib import Path
import numpy as np

def module(name,path):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def main():
 p=argparse.ArgumentParser();p.add_argument('--binding',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 if a.output.exists():raise FileExistsError(a.output)
 b=json.loads(a.binding.read_text());r=json.loads(Path(b['preregistration']).read_text());g=module('frozen_gauge',r['native_reader']);t=module('native_telemetry',b['telemetry_reader'])
 assert r['integration_allocation']==.01 and r['physical_scale_H_m']==.4 and r['gauges']==list(g.EXPECTED_GAUGES)
 pairs=[]
 for pair in b['pairs']:
  records={role:t.audit(pair[role]) for role in ['nominal','halfstep']}
  for role,cfl,coef in [('nominal',.2,.05),('halfstep',.1,.025)]:
   assert records[role]['CFLnumber']==cfl and float(records[role]['CoefDtMin'])==coef
  comparisons=[]
  for name in r['gauges']:
   parsed=[g.parse_gauge_csv(pair[role]['gauges'][name],expected_rows=800) for role in ['nominal','halfstep']]
   for x in parsed:
    assert np.isfinite(x['times']).all() and np.isfinite(x['swlz']).all()
    assert np.allclose(x['times'],np.arange(800)*.02,rtol=0,atol=1e-10)
   result=g.compare_two_gauges(*parsed,gauge_name=name,h_ref_m=.4,tol_relative=.01)
   result['within_frozen_time_RMSE']=bool(result['relative_eta_rmse']<=.01)
   result['within_frozen_time_maximum']=bool(result['relative_eta_max_abs']<=.01)
   result['registered_integration_allocation']=.01
   comparisons.append(result)
  pairs.append({'mechanism':pair['mechanism'],'native_telemetry':records,'gauges':comparisons,'all_six_probes_within_allocation':all(x['within_frozen_time_RMSE'] and x['within_frozen_time_maximum'] for x in comparisons)})
 result={'schema':'ds02.f5.actual-full-native-halfstep-all-probes.v1','preregistration':r,'pairs':pairs,'source_binding':b,'q_n_status':'not_granted','production_approval':'none','independent_case_count_increment':0,'causal_boundaries':r['causal_boundaries']}
 with a.output.open('x') as f:json.dump(result,f,indent=2);f.write('\n')
 print(json.dumps({x['mechanism']:x['all_six_probes_within_allocation'] for x in pairs}))
if __name__=='__main__':main()
