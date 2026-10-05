#!/usr/bin/env python3
from __future__ import annotations
import argparse,ast,json
from pathlib import Path
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--worker',type=Path,required=True); ap.add_argument('--binding-dir',type=Path,required=True); a=ap.parse_args(); text=a.worker.read_text(encoding='utf-8')
 if 'Path(case["prefix"]) + ".xml"' in text or 'Path(case["prefix"]) + ".bi4"' in text: raise SystemExit('path concatenation bug remains')
 t=ast.parse(text); ck=set(); bk=set()
 for n in ast.walk(t):
  if isinstance(n,ast.Subscript) and isinstance(n.slice,ast.Constant) and isinstance(n.slice.value,str):
   if isinstance(n.value,ast.Name) and n.value.id=='case': ck.add(n.slice.value)
   if isinstance(n.value,ast.Name) and n.value.id=='binding': bk.add(n.slice.value)
 missing=[]
 for p in sorted(a.binding_dir.glob('*.json')):
  d=json.loads(p.read_text()); missing.extend([f'{p.name}:case:{k}' for c in d.get('cases',[]) for k in ck if k not in c]); missing.extend([f'{p.name}:binding:{k}' for k in bk if k not in d])
 if missing: raise SystemExit(json.dumps({'passed':False,'missing':missing}))
 print(json.dumps({'passed':True,'binding_count':len(list(a.binding_dir.glob("*.json"))),'case_keys':sorted(ck),'binding_keys':sorted(bk),'path_expression_bug':False,'scientific_arrays_read':False},sort_keys=True))
if __name__=='__main__': main()
