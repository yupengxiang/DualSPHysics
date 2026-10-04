"""Root exact initial-state halfstep cloning with whole-tree undo proof."""
import argparse,importlib.util,json,hashlib,shutil
from pathlib import Path
import xml.etree.ElementTree as E

def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  while c:=f.read(1048576):h.update(c)
 return h.hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('--binding',type=Path,required=True);p.add_argument('--output-dir',type=Path,required=True);a=p.parse_args();b=json.loads(a.binding.read_text())
 if a.output_dir.exists():raise FileExistsError(a.output_dir)
 for role in ['source_solver_receipt','source_gencase_receipt']:
  j=json.loads(Path(b[role]).read_text())
  if j['status']!='completed' or j['returncode']!=0:raise ValueError('Actual original completed0 required')
 source=Path(b['source_prefix']);xml=source.with_suffix('.xml');original=xml.read_bytes()
 if sha(xml)!=b['source_xml_sha256'] or sha(source.with_suffix('.bi4'))!=b['source_bi4_sha256']:raise ValueError('Immutable original state differs')
 s=importlib.util.spec_from_file_location('selected_transformer',b['transformer']);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);new,meta=m.transform_execution_xml_bytes(original)
 before=E.fromstring(original);after=E.fromstring(new);restored=E.fromstring(new)
 cfl=after.find('./execution/constants/cflnumber');params={x.get('key'):x for x in after.findall('./execution/parameters/parameter')}
 if float(cfl.get('value'))!=.1 or float(params['CoefDtMin'].get('value'))!=.025 or any(float(params[k].get('value'))!=0 for k in ['DtFixed','DtIni','DtMin']):raise ValueError('Genuine independent adaptive half control differs')
 restored.find('./execution/constants/cflnumber').set('value',before.find('./execution/constants/cflnumber').get('value'))
 rp={x.get('key'):x for x in restored.findall('./execution/parameters/parameter')};bp={x.get('key'):x for x in before.findall('./execution/parameters/parameter')};rp['CoefDtMin'].set('value',bp['CoefDtMin'].get('value'))
 if E.tostring(restored)!=E.tostring(before):raise ValueError('Whole initial geometry/rigid/EOS/driver fields differ')
 if float(params['TimeMax'].get('value'))!=b['full_window_s'] or float(params['TimeOut'].get('value'))!=b['save_interval_s']:raise ValueError('Full native event window changed')
 a.output_dir.mkdir();copied=[]
 for source_file in source.parent.glob(source.name+'*'):
  if not source_file.is_file():continue
  dst=a.output_dir/source_file.name;expected=sha(source_file)
  if source_file==xml:
   with dst.open('xb') as f:f.write(new)
  else:
   with source_file.open('rb') as f,dst.open('xb') as g:shutil.copyfileobj(f,g,1024**2)
   if sha(dst)!=expected:raise ValueError('Original declared asset changed during copy')
  copied.append({'source':str(source_file),'source_sha256':expected,'target':str(dst),'target_sha256':sha(dst)})
 if sha(a.output_dir/source.with_suffix('.bi4').name)!=b['source_bi4_sha256']:raise ValueError('Initial BI4 differs')
 report={'family_id':b['family_id'],'physical_mother':'exact original BI4/EOS/wholeXMLundo/sourceassets','prefix':str(a.output_dir/source.name),'all_source_assets':copied,'whole_tree_undo_proved':True,'selected_transformer_metadata':meta,'source_solver_receipt':b['source_solver_receipt'],'source_gencase_receipt':b['source_gencase_receipt'],'CFL':.1,'CoefDtMin':.025,'DtFixed':0,'full_window_s':b['full_window_s'],'save_interval_s':b['save_interval_s'],'new_gencase_claim':False,'q_n':'not_granted','production_approval':'none'}
 with (a.output_dir/'clone-report.json').open('x') as f:json.dump(report,f,indent=2);f.write('\n')
 print(json.dumps({'family':b['family_id'],'exact_initial_clone':'completed','wholeXMLundo':'passed'}))
if __name__=='__main__':main()
