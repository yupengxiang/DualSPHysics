#!/usr/bin/env python3
"""Static fresh071 contract verifier; never reads BI4/CSV/H5/motion payloads."""
from __future__ import annotations
import ast, hashlib, json, sys
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]

def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()
def load(p): return json.loads(Path(p).read_text())
def req(v,m):
 if not v: raise AssertionError(m)
def ast_keys(path):
 tree=ast.parse(Path(path).read_text()); out=set()
 for node in ast.walk(tree):
  if isinstance(node,ast.Subscript) and isinstance(node.value,ast.Name) and node.value.id in {'case','b'}:
   sl=node.slice
   if isinstance(sl,ast.Constant) and isinstance(sl.value,str): out.add((node.value.id,sl.value))
 return out
def main():
 bind=load(ROOT/'metadata/actual-native-qa-binding.json'); req(bind['launch_allowed'] is False,'binding enabled'); req(len(bind['cases'])==16,'not 16 cases')
 worker=ROOT/'workers/run_f7_first24_native_initial_qa.py'; keys=ast_keys(worker)
 source=worker.read_text()
 literal_strings={node.value for node in ast.walk(ast.parse(source)) if isinstance(node,ast.Constant) and isinstance(node.value,str)}
 required={'case_id','generated_bi4','generated_xml','expected','gencase_receipt','gencase_receipt_sha256','prepared_input_report','generated_definition','generated_motion','source_definition','prepared_definition'}
 req(required <= literal_strings,f'worker/binding contract missing {required-literal_strings}')
 for case in bind['cases']:
  for key in ('gencase_receipt','prepared_input_report','generated_xml','generated_definition','source_definition','prepared_definition'):
   req(Path(case[key]).is_file(),f'{case["case_id"]}: missing {key}')
  req(case['generated_bi4_sha256'] is None,'BI4 hash must remain null')
  rec=load(case['gencase_receipt']); req(rec.get('status')=='completed' and rec.get('returncode')==0,'GenCase not completed/0')
  root=ET.parse(case['generated_xml']).getroot(); req(root.find('./execution/constants/data2d').get('value')=='false','not 3D')
  req(case['expected']['total_particles']==70179,'count contract changed')
 for folder in (ROOT/'requests/native-initial-qa',ROOT/'requests/qualification'):
  for p in folder.glob('*.json'):
   d=load(p); req(d.get('execution_allowed') is False and d.get('launch_allowed') is False,f'{p}: enabled'); req(d.get('future_hashes_null') is True,f'{p}: future hash policy')
   files=set(d.get('input_files',[])); hashes=set(d.get('input_sha256',{})); req(files==hashes,f'{p}: input_files/input_sha256 mismatch')
   for f in files:
    req(Path(f).is_file(),f'{p}: input missing {f}')
    req(sha(f)==d['input_sha256'][f],f'{p}: input hash mismatch {f}')
    req(not f.lower().endswith(('.bi4','.csv','.h5','.dat')),f'{p}: raw payload in input_files {f}')
   req(any(str(x).lower().endswith('.bi4') for x in d.get('future_input_files',[])),f'{p}: BI4 future input absent')
 print(json.dumps({'status':'pass','cases':len(bind['cases']),'worker_case_keys':sorted(literal_strings & required),'request_count':len(list((ROOT/'requests/native-initial-qa').glob('*.json')))+len(list((ROOT/'requests/qualification').glob('*.json'))),'arrays_read':False},indent=2))
if __name__=='__main__': main()
