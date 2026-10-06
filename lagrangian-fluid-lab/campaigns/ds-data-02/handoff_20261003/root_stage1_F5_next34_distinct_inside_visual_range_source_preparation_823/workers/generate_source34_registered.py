from pathlib import Path
from decimal import Decimal
import argparse,json,hashlib,shutil,os
ap=argparse.ArgumentParser();ap.add_argument('--plan',type=Path,required=True);ap.add_argument('--output-root',type=Path,required=True);ap.add_argument('--report',type=Path,required=True);a=ap.parse_args();plan=json.loads(a.plan.read_text());root=a.output_root;assert not root.exists();root.mkdir(parents=True)
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for block in iter(lambda:f.read(1048576),b''):h.update(block)
 return h.hexdigest()
base=Path(plan['base_motion']);before=sha(base);assert before==plan['base_motion_sha256_producer_attested'];data=[]
for raw in base.read_text().splitlines():
 raw=raw.strip()
 if not raw or raw.startswith(('#',';')):continue
 fields=raw.replace(',',' ').split();assert len(fields)==2;t,x=map(Decimal,fields);assert t.is_finite() and x.is_finite();data.append((t,x))
assert len(data)==641 and data[0][0]==0 and data[-1][0]==16 and all(x[0]<y[0] for x,y in zip(data,data[1:]));out=[];seen=set()
for c in plan['candidates']:
 amp=Decimal(c['amplitude_percent'])/100;ts=Decimal(c['time_percent'])/100;assert Decimal('.85')<=amp<=Decimal('1.15') and Decimal('.8')<=ts<=1;assert (amp,ts) not in seen;seen.add((amp,ts));p=root/c['tag'];(p/'assets').mkdir(parents=True);motion=p/'assets'/c['motion_filename'];lines=[format(t*ts,'f')+'\t'+format(x*amp,'f') for t,x in data];motion.write_text('\n'.join(lines)+'\n');xml=p/(c['case_id']+'_Def.xml');owner=p/'owner.json';assert sha(c['source_xml'])==c['source_xml_sha256'] and sha(c['source_owner'])==c['source_owner_sha256'];shutil.copyfile(c['source_xml'],xml);shutil.copyfile(c['source_owner'],owner);out.append({'tag':c['tag'],'case_id':c['case_id'],'physical_case_id':c['physical_case_id'],'physical_condition_sha256':c['physical_condition_sha256'],'amplitude_scale':float(amp),'time_scale':float(ts),'rows':641,'output_time_first_s':float(data[0][0]*ts),'output_time_last_s':float(data[-1][0]*ts),'motion':{'path':str(motion),'sha256':sha(motion),'bytes':motion.stat().st_size},'definition':{'path':str(xml),'sha256':sha(xml)},'owner':{'path':str(owner),'sha256':sha(owner)},'actual_native_counts':None})
assert len(out)==34 and sha(base)==before;a.report.write_text(json.dumps({'schema':'ds02.f5.next34.registered-source-generation-report.v1','status':'completed','cases':out,'base_motion':{'path':str(base),'sha256_before':before,'sha256_after':sha(base)},'candidate_count':34,'native_control_interpolation':'piecewise linear','geometry_unchanged_from_registered_parent_xml_except_control_and_window':True,'native_GenCase_required_per_condition':True,'independent_case_count_increment':0},indent=2)+'\n')
