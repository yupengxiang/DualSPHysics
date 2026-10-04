#!/usr/bin/env python3
"""Metadata-only fresh064 contract checks."""
import json
from pathlib import Path
HERE=Path(__file__).resolve().parent
NEW=(0.27,0.29,0.30,0.34,0.36,0.37,0.41,0.43,0.44,0.48,0.52,0.54,0.59,0.61,0.67,0.71)
FIRST8=(0.25,0.32,0.39,0.46,0.50,0.57,0.64,0.75)
def load(n): return json.loads((HERE/n).read_text())
m=load("first24-manifest.json")
assert m["source_only"] and not m["execution_allowed"]
assert tuple(m["first8_exact_subset"]["amplitudes_m_s2"])==FIRST8
assert tuple(x["transverse_amplitude_m_s2"] for x in m["new_case_rows"])==NEW
assert not set(NEW).intersection(FIRST8) and len(m["new_case_rows"])==16
assert m["first8_exact_subset"]["case_rows"][4]["case_id"]=="F3_CELL3_LONG_DP006_AY0P50_ADAPTIVE_CFL05_COEF005"
b=load("source-binding.json")
assert tuple(b["new_amplitudes_m_s2"])==NEW and tuple(b["first8_amplitudes_m_s2"])==FIRST8
assert all(x["future_actual_forcing_sha256"] is None for x in b["candidates"])
reqs=[json.loads(p.read_text()) for p in sorted((HERE/"requests").glob("F3_STAGE1_DP006_P1000_AY*.json"))]
assert len(reqs)==16
for r in reqs:
 assert not r["launch_allowed"] and not r["execution_allowed"] and r["production_approval"]=="none"
 assert r["q_n"]=="not_granted" and r["independent_case_count_increment"]==0
 assert r["actual_solver_command"][1]=="-mdbc_noslip:1"
 assert r["actual_solver_command"][-2:]==["-tmax:8.35","-tout:0.01"]
 assert r["physical_condition_sha256"] is None
 assert r["prepared_input_gate"]["forcing_sha256"] is None
prep=load("requests/batch-source-preparation-request.json")
assert not prep["launch_allowed"] and not prep["execution_allowed"]
assert prep["command"][1].endswith("/source_builder.py")
print("fresh064 static contract: PASS (metadata only)")
