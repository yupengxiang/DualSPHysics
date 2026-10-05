#!/usr/bin/env python3
"""Metadata-only AST/schema audit for the fresh093 GenCase QA worker."""
from __future__ import annotations
import argparse,ast,json
from pathlib import Path
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--worker',type=Path,required=True); ap.add_argument('--binding-dir',type=Path,required=True); a=ap.parse_args()
 tree=ast.parse(a.worker.read_text(encoding='utf-8')); ck=set(); bk=set()
 for n in ast.walk(tree):
  if isinstance(n,ast.Subscript) and isinstance(n.slice,ast.Constant) and isinstance(n.slice.value,str):
   if isinstance(n.value,ast.Name) and n.value.id=='case': ck.add(n.slice.value)
   if isinstance(n.value,ast.Name) and n.value.id=='binding': bk.add(n.slice.value)
 missing=[]; cases=sorted(a.binding_dir.glob('*.json'))
 for p in cases:
  d=json.loads(p.read_text(encoding='utf-8'))
  missing.extend([f'{p.name}:case:{k}' for c in d.get('cases',[]) for k in ck if k not in c])
  missing.extend([f'{p.name}:binding:{k}' for k in bk if k not in d])
 if missing: raise SystemExit(json.dumps({'passed':False,'missing':missing},sort_keys=True))
 print(json.dumps({'passed':True,'case_keys':sorted(ck),'binding_keys':sorted(bk),'binding_count':len(cases),'scientific_arrays_read':False},sort_keys=True))
if __name__=='__main__': main()
