import argparse,json,subprocess,importlib.util
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--binding',required=True);p.add_argument('--output-dir',required=True);a=p.parse_args();b=json.loads(Path(a.binding).read_text());out=Path(a.output_dir);out.mkdir(exist_ok=False)
s=importlib.util.spec_from_file_location('actual_endpoint_omega_audit',b['audit_worker']);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
results=[]
for c in b['cases']:
 d=out/c['case_id'];d.mkdir();command=[b['floating_info'],'-dirdata',c['native_data'],'-first:0','-last:1','-onlymk:60','-savemotion:1','-csvsep:0','-savedata',str(d/'FloatingInfo')]
 subprocess.run(command,cwd=d,check=True)
 csvs=list(d.glob('*.csv'));assert len(csvs)==1,csvs
 r=m.audit(csvs[0],Path(c['xml']),Path(c['owner']),Path(c['solver_receipt']),max_rows=4,omega_tolerance=m.OMEGA_TOLERANCE_DEFAULT)
 r['official_export_command']=command;(d/'state0-omega-audit.json').write_text(json.dumps(r,indent=2)+'\n');assert r['status']=='pass',r['checks'];results.append({'case_id':c['case_id'],'status':r['status'],'expected':r['expected_angular_velocity_rad_s'],'observed':r['observed_state0_angular_velocity_rad_s']})
(out/'two-endpoint-omega-summary.json').write_text(json.dumps({'schema':'ds02.root.actual.f6.endpoint-state0-omega.v1','cases':results,'all_cases_passed':True,'q_n':'not_granted','precision_status':'not_accepted','independent_case_increment':0},indent=2)+'\n')
print(json.dumps({'all_cases_passed':True,'cases':results}),flush=True)
