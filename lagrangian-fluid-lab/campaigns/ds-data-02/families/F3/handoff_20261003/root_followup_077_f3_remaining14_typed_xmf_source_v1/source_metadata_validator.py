#!/usr/bin/env python3
"""Validate fresh077 metadata contracts without opening scientific payloads."""
from __future__ import annotations
import hashlib,json
from pathlib import Path
HERE=Path(__file__).resolve().parent
BAD={".bi4",".csv",".h5",".hdf5",".npy",".npz"}
def load(p): return json.loads(Path(p).read_text())
def sha(p):
 p=Path(p)
 if p.suffix.lower() in BAD: raise AssertionError(f"payload hash forbidden: {p}")
 h=hashlib.sha256();
 with p.open("rb") as f:
  for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
 return h.hexdigest()
def main():
 m=load(HERE/"manifest.json"); assert m["case_count"]==14 and m["arrays_read"] is False and m["jobs_started"] is False
 expected={"actual_3d":True,"continuum_reference_mass_kg":14.58,"dimension":3,"event_window_s":[0.0,8.35],"fixed_particles":111708,"fluid_particles":67500,"mass_normalization":"none","mass_policy":"native_massfluid_no_rescaling","moving_particles":0,"native_fluid_mass_kg":14.580000000000002,"save_interval_s":0.01,"saved_frames":836,"total_particles":179208}
 assert m["native_contract"]==expected
 for p in HERE.rglob("*"):
  if p.is_file(): assert p.suffix.lower() not in BAD, p
 for p in sorted((HERE/"owners").glob("*.json")):
  d=load(p); assert d["fresh_id"]=="fresh077" and d["source_only"] and d["native_full836_binding"]["status"]=="completed"
  assert d["native_full836_binding"]["returncode"]==0 and d["native_full836_binding"]["total_particles"]==179208
 for group in (HERE/"requests/typed",HERE/"requests/xmf",HERE/"requests/render"):
  for p in group.glob("*.json"):
   d=load(p); assert d["execution_allowed"] is False and d["launch_allowed"] is False and d["future_outputs"] if "future_outputs" in d else True
 print("fresh077 source contract: PASS")
if __name__=="__main__": main()
