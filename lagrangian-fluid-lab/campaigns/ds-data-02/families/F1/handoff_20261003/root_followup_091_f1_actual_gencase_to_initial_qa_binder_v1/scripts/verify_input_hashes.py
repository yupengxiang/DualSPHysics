#!/usr/bin/env python3
"""Strict non-science input hash checker; producer digests are never rehashed for science suffixes."""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
SCIENCE={'.bi4','.h5','.hdf5','.csv','.dat','.vtk','.vtu','.npy','.npz'}
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('receipt'); a=ap.parse_args(); d=json.loads(Path(a.receipt).read_text()); errs=[]
 for label,mp in [('request',d.get('request',{}).get('input_sha256',{})),('launch',d.get('input_hashes_at_launch',{})),('after',d.get('input_hashes_after_run',{}))]:
  for raw,h in mp.items():
   p=Path(raw)
   if p.suffix.lower() in SCIENCE: continue
   if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=h: errs.append(f'{label}:{p}')
 print(json.dumps({'receipt':str(Path(a.receipt)),'errors':errs,'passed':not errs,'science_payloads_read_or_hashed':False},indent=2))
 return 0 if not errs else 2
if __name__=='__main__': raise SystemExit(main())
