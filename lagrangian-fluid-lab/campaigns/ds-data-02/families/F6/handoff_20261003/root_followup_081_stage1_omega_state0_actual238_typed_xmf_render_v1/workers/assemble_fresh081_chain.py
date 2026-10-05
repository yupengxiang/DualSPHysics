#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROV = ROOT / "metadata/actual-root238-state0-provenance.json"

def load(p): return json.loads(Path(p).read_text())
def sha(p):
    h=hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda:f.read(1024*1024), b""): h.update(b)
    return h.hexdigest()

prov=load(PROV)
assert prov["aggregate_execution_receipt"]["status"] == "completed"
assert prov["aggregate_execution_receipt"]["returncode"] == 0
assert prov["aggregate_summary"]["all_cases_passed"] is True
assert len(prov["cases"]) == 8
assert prov["per_case_execution_receipts"] == "absent by design; do not invent them"
errors=[]; records=[]
for sub in ("typed/requests", "xmf/requests", "render/requests"):
  for p in sorted((ROOT/sub).glob("*.json")):
    x=load(p); records.append((x.get("case_id"), sub, str(p)))
    for k in ("disabled", "launch", "launch_allowed", "execution_allowed"):
      if x.get(k) is not ({"disabled":True,"launch":False,"launch_allowed":False,"execution_allowed":False}[k]): errors.append(f"{p}: bad {k}")
    if x.get("future_hashes_null") is False: errors.append(f"{p}: future_hashes_null false")
    if x.get("expected_native_contract",{}).get("dimension") != 3: errors.append(f"{p}: dimension")
    if x.get("expected_native_contract",{}).get("vector_shape") != [417505,3]: errors.append(f"{p}: vector shape")
    if x.get("state0_execution_receipt_scope") != "one aggregate Root238 execution receipt; no per-case execution receipts exist": errors.append(f"{p}: receipt scope")
    for k,v in x.get("future_input_sha256",{}).items():
      if v is not None: errors.append(f"{p}: future hash non-null {k}")
    if set(x.get("input_files",[])) != set(x.get("input_sha256",{})):
      errors.append(f"{p}: input closure")
    for raw in x.get("input_files",[]):
      q=Path(raw)
      if q.suffix.lower() in {".bi4",".ibi4",".h5",".csv"}: errors.append(f"{p}: raw scientific static input {q}")
      if not q.exists(): errors.append(f"{p}: missing static input {q}")
      elif q.is_file() and sha(q) != x["input_sha256"][raw]: errors.append(f"{p}: hash mismatch {q}")
    actual=x.get("actual_state0",{})
    if actual.get("audit_status") != "pass": errors.append(f"{p}: state0 not pass")
    if actual.get("per_case_execution_receipt") is not None: errors.append(f"{p}: invented per-case receipt")
    if x.get("root_actual_launch_entry") != "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_home_floor_inventory_dispatch_142/launch.py": errors.append(f"{p}: wrong root entry")
if len(records) != 24: errors.append(f"request count {len(records)}")
if errors:
  raise SystemExit("\n".join(errors))
out={"schema":"ds02.f6.fresh081.metadata-only-assembler-report.v1","requests":len(records),"cases":8,"actual_root238":"aggregate completed/0; all eight per-case audits pass","root_entry":"Root142 CPU audit/conversion","per_case_execution_receipts_invented":False,"future_hashes_null":True,"scientific_arrays_read":False,"jobs_started":False,"shared_mutations":False,"vector_shape":"417505 3","mass_policy":{"physical_rigid_mass_kg":128.0,"native_support_mass_kg":256.0,"solver_interaction_masspart_kg":0.015625,"normalization":"none"}}
print(json.dumps(out,indent=2,sort_keys=True))
report=ROOT/"metadata/metadata-only-assembler-report.json"
report.write_text(json.dumps(out,indent=2,sort_keys=True)+"\n")
