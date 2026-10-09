from pathlib import Path
import json,subprocess,hashlib,math,importlib.util,csv
import sys
HERE=Path(__file__).resolve().parent
COMMON=HERE.parent/'root-owned-lifecycle-continuation-v1/root_common_verification.py'
exec(COMMON.read_text(),globals())
def sha(path):
 path=Path(path);assert path.suffix.lower() not in {'.h5','.hdf5','.bi4','.obi4','.ibi4','.vtk','.jsonl'} and path.stat().st_size<=10485760
 return hashlib.sha256(path.read_bytes()).hexdigest()
def stat(path):
 path=Path(path);z=path.stat();return {'path':str(path),'bytes':z.st_size,'mtime_ns':z.st_mtime_ns,'ctime_ns':z.st_ctime_ns,'st_dev':z.st_dev,'st_ino':z.st_ino}
num=sys.argv[1];family=sys.argv[2];version=int(sys.argv[3]);qp=Path(sys.argv[4]);scope_path=Path(sys.argv[5]);scope_sha=sys.argv[6]
assert family in ['F4','F6'] and num in ['274','308','309'] and version in [1,2]
name=f'generic-native-extract-v{version}-{family.lower()}'
q,b,r,p=common(qp)
bp=b/'generic-native-extract.json';batch=load(bp)
assert batch['status'] in ['COMPLETED_ALL_CASES','COMPLETED_WITH_CASE_FAILURES']
assert batch['counts']['requested']==len(q['physical_case_ids'])
mp=Path(q['manifest_contract']['path']);man=load(mp)
assert sha(mp)==q['manifest_contract']['sha256']
items={x['physical_case_id']:x for x in man['contracts']}
assert len(items)==len(man['contracts']) and set(items)==set(q['physical_case_ids'])
assert sha(scope_path)==scope_sha
scope=load(scope_path);assert set(items)<=set(scope['remaining_cause_not_located_case_ids'])
typedproof=load(man['terminal_proof']['path']);tp={z['physical_case_id']:z for z in typedproof['case_verifications']}
assert len(tp)==len(typedproof['case_verifications'])==len(items) and set(items)==set(tp)
assert typedproof['parent_reservation_released'] and typedproof['repeat_fee_idempotent'] and not typedproof['failed_cases']
assert sha(man['terminal_proof']['path'])==man['terminal_proof']['sha256']
tool=Path('/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTKOut_linux64')
th=sha(tool);assert th==r['input_hashes_at_launch'][str(tool)]=='62630430902484f4aede017108313673fe6414f40fb59b6ae7f14ac23219db00'
verified=[];failed=[]

for outcome in batch['case_results']:
 case=outcome['physical_case_id'];item=items[case];cp=Path(item['path']);c=load(cp);assert sha(cp)==item['sha256']==r['input_hashes_at_launch'][str(cp)]
 if outcome['status']!='COMPLETED':failed.append(outcome);continue
 vp=Path(outcome['output']);assert vp.is_relative_to(b);v=load(vp);assert v['historical_118_membership'] is True;assert v['status']=='COMPLETED_GENERIC_NATIVE_TYPED_SAVED_BRACKET_DIAGNOSTIC_ONLY' and v['physical_case_id']==case;assert all(v['claim_boundary'][k]=='UNKNOWN' for k in ['QI','QN','QE','physical_fate','legal_flux','dynamics','continuous_event_time']);td=c['typed_deferred'];summary=load(td['summary']['path']);assert sha(td['summary']['path'])==td['summary']['sha256']==tp[case]['summary_sha256'];assert td['summary']['path']==tp[case]['summary'];times=summary['timeline']['time_s'];assert len(times)>=2;recs=v['typed'];assert recs['pre_stat']==recs['post_stat']==stat(td['records']['path']);assert recs['sha256']==td['records']['sha256']==tp[case]['records_stat_only']['sha256'];assert recs['rows']==tp[case]['records_stat_only']['rows']==summary['timeline']['particles'];assert v['counts']['typed_targets']==v['counts']['native_rows']==v['counts']['joined']==recs['target_count']==outcome['joined']>0
 ob=v['native']['partout_obi4'];op=c['native_deferred']['partout_obi4']['path'];assert ob['pre_stat']==ob['post_stat']==stat(op) and ob['pre_sha256']==ob['post_sha256'];assert all(ob['pre_stat'][key]==c['native_deferred']['partout_obi4'][key] for key in ['bytes','mtime_ns','ctime_ns','st_dev','st_ino']);assert v['native']['official_tool']['path']==str(tool) and v['native']['official_tool']['returncode']==0
 csvp=Path(v['native']['partout_csv']['pre_stat']['path']);cmd=v['native']['official_tool']['command'];assert cmd==[str(tool),'-dirdata',c['native_deferred']['data_dir']['path'],'-savecsv',str(csvp),'-saveresume',str(csvp.parent/'resume.csv'),'-createdirs:1','-csvsep:1'];assert csvp.is_relative_to(b) and v['native']['partout_csv']['pre_stat']==v['native']['partout_csv']['post_stat']==stat(csvp) and sha(csvp)==v['native']['partout_csv']['sha256'];rawrows=list(csv.DictReader(csvp.open()));native={int(z['Idp']):z for z in rawrows};assert len(rawrows)==len(native)==v['counts']['native_rows'];runref=c['native_deferred']['runparts_csv'];rp=Path(runref['path']);assert sha(rp)==v['native']['runparts']['sha256'];assert v['native']['runparts']['pre_stat']==v['native']['runparts']['post_stat']==stat(rp);run=[]
 with rp.open() as f:
  for row in csv.reader(f,delimiter=';'):
   if not row or not any(x.strip() for x in row) or row[0].startswith('#'):continue
   if not run and row[0]=='Part':header=row;continue
   assert len(row)==len(header)==26;z=dict(zip(header,row));assert int(z['Part'])==len(run);run.append(z)
 observed=[float(z['TimeStep [s]']) for z in run];assert len(run)==len(times) and len(run)==v['native']['runparts']['rows'];assert all(math.isclose(a,c,abs_tol=1e-9) for a,c in zip(times,observed));causes=set();target=v['rows'];assert len(target)==len(native) and len({(z['zone'],z['idp']) for z in target})==len(target);assert {(z['zone'],z['idp']) for z in target}=={(0,i) for i in native}
 for row in target:
  raw=native[row['idp']];f=row['first_missing_frame'];assert 0<f<len(times) and row['first_missing_time_s']==times[f] and row['bracket_s']==[times[f-1],times[f]];assert row['part_out']==int(raw['PartOut'])==f and row['motive_code']==int(raw['Motive']) in [1,2,3];assert row['density_kg_m3']==float(raw['Rhop [kg/m^3]']) and row['position_m']==[float(raw[x]) for x in ['Pos.x [m]','Pos.y [m]','Pos.z [m]']];assert row['identity_key']==[row['zone'],row['idp']] and all(row[k]=='UNKNOWN' for k in ['physical_fate','legal_flux','dynamics']);causes.add({1:'NUMERICAL_POSITION_EXCLUSION',2:'NUMERICAL_DENSITY_EXCLUSION',3:'NUMERICAL_MOVEMENT_EXCLUSION'}[row['motive_code']])
 verified.append({'physical_case_id':case,'family_id':family,'report':str(vp),'report_sha256':sha(vp),'source_contract':str(cp),'source_contract_sha256':sha(cp),'typed_records_stat_SHA_only':td['records'],'typed_summary':td['summary'],'target_fluid_identity_count':len(target),'native_cause_categories':sorted(causes),'saved_frame_matches':len(target),'official_decoder':v['native']['official_tool'],'native_OBI4_stat_SHA_only':ob,'independent_CSV_RunPARTs_identity_motive_brackets_arithmetic_verified':True,'exact_join_rows':target,'new_original118_cause_bound_physical_case':True,'physical_fate_legal_flux_dynamics_Q':'UNKNOWN'})
assert len(verified)==batch['counts']['completed'] and len(failed)==batch['counts']['failed'];p.update(status=f'VERIFIED_ACTUAL_GENERIC_{family}_NATIVE_CAUSE_EXTRACT_V{version}_WITH_EXACT_TYPED_SAVED_FRAME_JOINS_NO_PHYSICAL_CREDIT',report=str(bp),report_sha256=sha(bp),manifest=str(mp),manifest_sha256=sha(mp),actual_completed_physical_cases=len(verified),failed_physical_cases=len(failed),failed_cases=failed,new_original118_cause_bound_physical_cases=len(verified),new_original118_typed_native_joins=len(verified),newly_bound_case_ids=sorted(z['physical_case_id'] for z in verified),target_fluid_identity_count=sum(z['target_fluid_identity_count'] for z in verified),case_verifications=verified,root_native_H5_JSONL_content_read=False,scientific_qualification={'QI':'UNKNOWN','QN':'UNKNOWN','QE':'UNKNOWN'},next='Update exact original118 overlay only with independently verified actual joined cases; preserve case failures/new-attempt recovery; remaining CURRENT lifecycle/reference/splits/products stay ACTIVE')
p['fresh_native_admission_scope']={'path':str(scope_path),'sha256':scope_sha}
footer=(HERE.parent/'root-owned-lifecycle-continuation-v1/root_cpu_verification_footer.py').read_text().replace('1073741824','4294967296').replace('F7_S1_SOURCE_SUPPORT_ACTUAL_SCOPE_ROOT_VERIFICATION_137.json',f'GENERIC_NATIVE_EXTRACT_{family}_V{version}_ACTUAL_ROOT_VERIFICATION_{num}.json');exec(footer,globals())
