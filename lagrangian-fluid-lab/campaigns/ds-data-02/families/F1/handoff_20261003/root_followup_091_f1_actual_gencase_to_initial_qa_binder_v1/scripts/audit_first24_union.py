#!/usr/bin/env python3
"""Check fresh091's physical tuple union without reading scientific payloads."""
from __future__ import annotations
import argparse,json
from pathlib import Path
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('union'); a=ap.parse_args(); d=json.loads(Path(a.union).read_text()); rows=d['rows']; keys=[]
 for r in rows: keys.append((r['mechanism_id'],round(float(r['fluid_depth_m']),12),tuple(round(float(x),12) for x in r['initial_velocity_m_per_s'])))
 dup={str(k):keys.count(k) for k in set(keys) if keys.count(k)>1}; ok=len(rows)==48 and len(set(keys))==48 and not dup
 print(json.dumps({'rows':len(rows),'unique_tuples':len(set(keys)),'duplicates':dup,'passed':ok,'arrays_read':False},indent=2)); return 0 if ok else 2
if __name__=='__main__': raise SystemExit(main())
