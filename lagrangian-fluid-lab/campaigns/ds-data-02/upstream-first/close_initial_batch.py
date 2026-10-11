"""Record the actual M3 deliverable and audit the unchanged cumulative ledger."""
import datetime, fcntl, hashlib, json, os, sys
from pathlib import Path
P=Path(__file__).resolve().parent
ROOT=P.parents[3]
sys.path.insert(0,str(ROOT/'lagrangian-fluid-lab/scripts'))
import ds_data02_runtime_v6_batch2 as batch
R=Path('/data/nas/jade/Simulation/DualSPHysics/upstream-first/runs')
DATA=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')

def bind(path):
 p=Path(path);assert p.is_file() and not p.is_symlink(),p
 return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size}
def new(path,d):
 assert not path.exists(),path
 path.parent.mkdir(exist_ok=True,parents=True)
 with path.open('x') as f:json.dump(d,f,ensure_ascii=False,indent=2);f.write('\n')
def main():
 entries=[];receipts=[]
 for case,attempt in [('UF_F1_MDBC_DP010_H050','comparison-001'),('UF_F1_MDBC_DP010_H060','comparison-002')]:
  b=R/'F1'/case
  report=json.loads((b/attempt/'comparison/mother-vs-waterdepth-comparison-report.json').read_text())
  scan=json.loads((b/'native-frame-scan-001/frame-identity-scan.json').read_text())
  assert report['status']=='completed_diagnostic_numerical_comparison'
  assert report['coverage_checks']['all_full_common_0_6'] and set(report['metrics'])==set(['H1','H2','H3','H4']+['P'+str(i) for i in range(1,9)])
  assert scan['status']=='verified' and scan['fatal_findings']==[] and scan['coverage']['frame_count']==241
  assert scan['native_exclusions']['final_missing_matches_native_ids']
  artifactpaths=[b/attempt/'comparison/mother-vs-waterdepth-comparison-report.json',b/'native-integrity-001/integrity.json',b/'native-frame-scan-001/frame-identity-scan.json',b/'postprocess-001/observations/postprocess-manifest.json',b/'gencase-001'/f'{case}.xml']
  for a in ['gencase-001','solver-001','native-integrity-001','native-frame-scan-001','postprocess-001',attempt]:
   path=b/a/'execution-receipt.json';d=json.loads(path.read_text());assert d['status']=='completed' and d['returncode']==0
   receipts.append(dict(bind(path),status=d['status']))
  entries.append({'case_id':case,'artifacts':[bind(x) for x in artifactpaths],'physical_difference':report['physical_difference'],'sampling_difference':report['sampling_difference'],'native_exclusions':scan['native_exclusions'],'metrics':report['metrics'],'qualification':'scoped_internal_numerical_transport_diagnostic_only'})
 catalog=json.loads((P/'m3/scope_catalog.json').read_text());mapping=json.loads((P/'m3/upstream-family-map.json').read_text())
 assert catalog['counts']['cases']==336 and len(catalog['cases'])==336 and catalog['counts']['families']==7
 assert len(mapping['families'])==7
 pack={'schema':'ds02.upstream-first.m3-delivery.v1','status':'complete_diagnostic','entries':entries,'mother_acceptance':bind(P/'m3/fine-mother-acceptance-decision.json'),'catalog':bind(P/'m3/scope_catalog.json'),'family_map':bind(P/'m3/upstream-family-map.json'),'failed_comparison_preserved':bind(R/'F1/UF_F1_MDBC_DP010_H060/comparison-001/execution-receipt.json'),'limits':['native numerical identity; no continuous material-trajectory or fate claim','output schedule .025s differs from mother .01s; no sampling-equivalence or event-timing qualification','differences are child vs numerical mother; no experimental-calibration or convergence claim']}
 packpath=P/'M3_DERIVATIVE_PACK.json';new(packpath,pack)
 certificate={'schema':batch.MILESTONE_EVIDENCE_SCHEMA,'milestone':'M3','status':'complete','acceptance_status':'accepted','acceptance_scope':'Two actual single-depth derivatives from scoped-accepted full-event 3D mother, all241frame audits and full H1-H4/P1-P8 comparisons; seven-family map and336case scope catalog. Diagnostic only.','artifacts':[bind(packpath)],'receipts':receipts,'checked_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
 new(P/'milestone-evidence/M3-complete-v1.json',certificate)
 with (DATA/'runtime/resource-ledger.lock').open('a+') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  ledger=json.loads((DATA/'runtime/resource-ledger.json').read_text());assert not ledger['reservations']
  rows=[r for r in ledger['charges'] if batch.v6._upstream_id(r['id'])]
  used=batch._usage(rows)
  limits={'gpu_seconds':86400,'cpu_core_seconds':345600,'new_storage_bytes':50*1024**3}
  assert all(used[k]<=v for k,v in limits.items())
  solvers=[r for r in ledger['attempts'] if batch.v6._upstream_id(r['id']) and r['kind'] in ['qualification','production']];assert len(solvers)<=24
  nasbytes=sum(p.stat().st_size for p in R.rglob('*') if p.is_file() and not p.is_symlink())
  home=os.statvfs('/home/jade');nas=os.statvfs('/data/nas');homefree=home.f_bavail*home.f_frsize;nasfree=nas.f_bavail*nas.f_frsize
  assert Path('/data/nas').is_mount() and homefree>=500*1024**3
  prior=batch._usage(ledger['charges'])
  audit={'schema':batch.COST_AUDIT_SCHEMA,'status':'complete','acceptance_status':'accepted','checked_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'charged_ids':sorted(r['id'] for r in ledger['charges']),'prior_usage':prior,'first_batch_usage':used,'first_batch_limits':limits,'solver_attempts':len(solvers),'solver_attempt_cap':24,'nas_runs_current_bytes':nasbytes,'home_free_bytes':homefree,'nas_free_bytes':nasfree,'historical_bytes_preserved':True,'parent_storage_policy':ledger['limits']['storage_policy'],'reservations':[],'conservative_charge_note':'Mother601frame scan session reconciliation charged the entire3600CPUcore-second reserved ceiling; unobserved exit retained in separate receipt. Failed attempts remain charged.','parent_limits':ledger['limits'],'deadline_utc':ledger['deadline_utc']}
  new(P/'batch2-runtime/M1-M3-cost-audit-v1.json',audit)
 print(json.dumps({'M3':'complete_diagnostic','first_batch_usage':used,'solver_attempts':len(solvers),'parent_usage':prior},indent=2))
if __name__=='__main__':main()
