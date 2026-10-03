"""Verify the actual full-window F2 dense native saving allocation."""
import argparse,importlib.util,json
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--binding',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
if a.output.exists():raise FileExistsError(a.output)
b=json.loads(a.binding.read_text());spec=importlib.util.spec_from_file_location('native_counter_audit',b['source_auditor']);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);result=m.audit(b['case']);budget=json.loads(Path(b['budget_review']).read_text())['frozen_save_allowance_s']
result.update(schema='ds02.F2.actual-native-dense-saving-allocation.v1',frozen_save_allowance_s=budget,actual_native_maximum_halfwidth_s=result['maximum_save_halfwidth_s'],within_registered_native_saving_allocation=result['maximum_save_halfwidth_s']<=budget,q_n_status='not_assessed',production_approval='none',limitations=['Native saving allocation alone does not establish convergence of event labels or transport.','Unknown native exclusion fates are retained.'],source_binding=b)
a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'maximum_native_halfwidth_s':result['maximum_save_halfwidth_s'],'within_registered_native_saving_allocation':result['within_registered_native_saving_allocation']}))
