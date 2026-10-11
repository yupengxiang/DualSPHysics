"""Bind the two completed depth derivatives to existing immutable native auditors."""
import argparse, json, hashlib, re, xml.etree.ElementTree as ET
from pathlib import Path

CAMPAIGN=Path(__file__).resolve().parents[1]
CONVERSION=CAMPAIGN/'m2/upstream_conversion'
RUNS=Path('/data/nas/jade/Simulation/DualSPHysics/upstream-first/runs/F1')
MOTHER='UF_F1_MDBC_DAMBREAK3D'

def bind(path):
 path=Path(path)
 if not path.is_file() or path.is_symlink():raise ValueError(f'not regular: {path}')
 return {'path':str(path),'bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}

def prepare(case,mode):
 root=RUNS/case; solver=root/'solver-001'; gc=root/'gencase-001'
 receipt=json.loads((solver/'execution-receipt.json').read_text())
 if receipt['status']!='completed' or receipt['request']['case_id']!=case:raise ValueError('solver must be completed and case-bound')
 xml=ET.parse(gc/(case+'.xml')).getroot()
 expected=int(xml.find('./execution/particles').attrib['np'])
 params={n.attrib['key']:n.attrib['value'] for n in xml.findall('./execution/parameters/parameter')}
 if float(params['TimeMax'])!=6 or float(params['TimeOut'])!=.025:raise ValueError('unexpected event/output scope')
 found=re.findall(r'Excluded particles\.*:\s*([\d,]+)',(solver/'Run.out').read_text())
 if len(found)!=1:raise ValueError('terminal exclusion count missing/ambiguous')
 excluded=int(found[0].replace(',',''))
 suffix='native-integrity-001' if mode=='exclusions' else 'native-frame-scan-001'
 manifest=json.loads((CONVERSION/'manifests'/f'{MOTHER}-{suffix}.json').read_text())
 request=json.loads((CONVERSION/'requests'/f'{MOTHER}-{suffix}.json').read_text())
 def replace(v):
  if isinstance(v,str):return v.replace(MOTHER,case).replace('/CaseDamBreak3D.xml','/'+case+'.xml')
  if isinstance(v,list):return [replace(x) for x in v]
  if isinstance(v,dict):return {k:replace(x) for k,x in v.items()}
  return v
 manifest=replace(manifest);request=replace(request)
 manifest['reference_role']='m3_physical_derivative_3d'
 manifest['expected'].update(initial_particles=expected,excluded_particles=excluded)
 source_key='source' if mode=='exclusions' else 'sources'
 manifest[source_key]['source_definition']['path']=str(CAMPAIGN/'m3/f1-fine-dp010-t025/input'/f'{case}_Def.xml')
 for key,val in list(manifest[source_key].items()):manifest[source_key][key]=bind(val['path'])
 if mode=='frames':
  integrity=json.loads((root/'native-integrity-001/integrity.json').read_text())
  if integrity['status']!='verified':raise ValueError('native exclusions not verified')
  manifest['expected']['frame_count']=241
 destination=CAMPAIGN/'m3/f1-fine-dp010-t025/audits';destination.mkdir(exist_ok=True)
 mf=destination/f'{case}-{suffix}-manifest.json';rq=destination/f'{case}-{suffix}-request.json'
 if mf.exists() or rq.exists():raise ValueError('refusing existing prepared inputs')
 request['command'][request['command'].index('--manifest')+1]=str(mf)
 request['reference_role']='m3_physical_derivative_3d'
 request['input_files']=[str(mf) if '/manifests/' in x and x.endswith(f'{case}-{suffix}.json') else x for x in request['input_files']]
 oldsource='/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/examples/mdbc/04_Dambreak/CaseDamBreak3D_Def.xml'
 request['input_files']=[manifest[source_key]['source_definition']['path'] if x==oldsource else x for x in request['input_files']]
 request['estimated_storage_bytes']=request['estimated_peak_storage_bytes']=671088640 if mode=='frames' else 67108864
 if mode=='frames':
  request['scan_contract']['frame_count']=241
  request['estimated_deferred_read_bytes']=sum(x.stat().st_size for x in (solver/'data').glob('Part_*.bi4'))
 if 'native_integrity' in request:
  request['native_integrity'].update(expected_initial_particles=expected,expected_excluded_particles=excluded,manifest=str(mf))
 for path in request['input_files']:
  if path!=str(mf) and not Path(path).is_file():raise ValueError(f'missing input: {path}')
 mf.write_text(json.dumps(manifest,indent=2)+'\n');rq.write_text(json.dumps(request,indent=2)+'\n')
 return str(rq)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--case',required=True,choices=['UF_F1_MDBC_DP010_H050','UF_F1_MDBC_DP010_H060']);p.add_argument('--mode',required=True,choices=['exclusions','frames']);a=p.parse_args();print(prepare(a.case,a.mode))
