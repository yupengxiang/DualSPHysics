#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
ARRAY_SUFFIXES={".bi4",".h5",".hdf5",".csv",".npy",".npz",".vtk",".dat"}
def sha(p):
    if p.suffix.lower() in ARRAY_SUFFIXES: raise RuntimeError(f"scientific payload hash forbidden: {p}")
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("request",type=Path); a=ap.parse_args()
    q=json.loads(a.request.read_text()); files=set(q["input_files"]); hashes=set(q["input_sha256"])
    if files != hashes: raise SystemExit("input_files/input_sha256 set mismatch")
    for raw in files:
        p=Path(raw)
        if not p.is_file(): raise SystemExit(f"missing static input: {p}")
        if sha(p) != q["input_sha256"][raw]: raise SystemExit(f"stale static input: {p}")
    if q.get("future_input_sha256") is not None: raise SystemExit("future input digest must be null")
    if not (q.get("disabled") and not q.get("execution_allowed") and not q.get("launch_allowed")): raise SystemExit("request is enabled")
    print(json.dumps({"passed":True,"request":str(a.request),"static_input_count":len(files),"future_input_sha256":None},sort_keys=True))
if __name__ == "__main__": main()
