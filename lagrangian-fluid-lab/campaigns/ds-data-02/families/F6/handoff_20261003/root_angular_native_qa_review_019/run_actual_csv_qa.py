import argparse, importlib.util, json, pathlib, hashlib
p=argparse.ArgumentParser();p.add_argument('--binding',type=pathlib.Path,required=True);p.add_argument('--role',required=True);p.add_argument('--output-root',type=pathlib.Path,required=True);a=p.parse_args()
b=json.loads(a.binding.read_text());r=json.loads(pathlib.Path(b['partvtk_receipt']).read_text())
if r['status']!='completed' or r['returncode']!=0:raise ValueError('Actual official initial extraction required')
s=pathlib.Path(b['csv']);digest=hashlib.sha256(s.read_bytes()).hexdigest()
if digest!=b['csv_sha256']:raise ValueError('Actual CSV binding changed')
a.output_root.mkdir(parents=True,exist_ok=True);link=a.output_root/'initial.csv'
if link.exists() or link.is_symlink():raise FileExistsError('Preserve existing owned output')
link.symlink_to(s)
spec=importlib.util.spec_from_file_location('angular_native_qa',b['evaluator']);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
x=m.run_case_qa(a.role,a.output_root,skip_partvtk_if_exists=True)
(a.output_root/'actual-official-source-binding.json').write_text(json.dumps(b,indent=2)+'\n')
print(json.dumps({'case_id':x['case_id'],'overall_initial_qa_passed':x['overall_initial_qa_passed'],'report':str(a.output_root/'f6_angular_release_initial_qa_report.json')}),flush=True)
