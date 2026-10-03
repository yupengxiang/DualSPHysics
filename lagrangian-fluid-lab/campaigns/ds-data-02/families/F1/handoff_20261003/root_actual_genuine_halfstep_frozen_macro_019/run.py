import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[6]/"scripts"))
from ds_data02_f1_eccentric_three_dp_evidence import compare_pair,sha256
p=argparse.ArgumentParser();p.add_argument("--binding",required=True);p.add_argument("--output",required=True);a=p.parse_args()
b=json.loads(Path(a.binding).read_text());f=json.loads(Path(b["frozen"]).read_text())
assert f["H0_m"]==.3 and f["continuous_initial_mass_kg"]==80.4 and f["macro_budget_fraction"]==.05
t=json.loads(Path(b["time_registration"]).read_text());assert t["time_macro_budget_fraction"]==.01 and t["integration_share"]==.2 and t["full_window_s"]==[0,1.6]
for key in ("clone_receipt","native_receipt"):
 r=json.loads(Path(b[key]).read_text());assert r["status"]=="completed" and r["returncode"]==0
clone=json.loads(Path(b["clone_report"]).read_text());assert clone["initial_bi4_byte_identical"] is True and clone["physical_condition_sha256"]==b["physical_condition_sha256"]
assert clone["only_xml_changes"]=={"CFLnumber":[.2,.1],"CoefDtMin":[.05,.025]}
cases={};bindings={}
for c in b["cases"]:
 r=json.loads(Path(c["receipt"]).read_text());assert r["status"]=="completed" and r["returncode"]==0
 o=json.loads(Path(c["observation"]).read_text());assert len(o["rows"])==1601 and o["rows"][0]["time_s"]==0 and o["rows"][-1]["time_s"]>=1.6
 assert o["physical_condition_sha256"]==b["physical_condition_sha256"] and o["quantiles"]==[.05,.5,.95] and o["continuous_initial_mass_kg"]==80.4
 assert abs(o["numerical_initial_mass_kg"]-80.4)/80.4<=f["initial_mass_budget_fraction"]
 cases[c["role"]]={"case_id":c["case_id"],"observation":o,"initial_mass_kg":o["numerical_initial_mass_kg"],"initial_mass_relative_error":o["initial_mass_relative_error"]}
 bindings[c["role"]]={"observation_sha256":sha256(Path(c["observation"])),"receipt_sha256":sha256(Path(c["receipt"])),"geometry_sha256":o["geometry_sha256"],"physical_condition_sha256":o["physical_condition_sha256"],"native_window_s":[o["rows"][0]["time_s"],o["rows"][-1]["time_s"]]}
assert len({c["observation"]["coordinate_frame"] for c in cases.values()})==1
pairs={}
for x,y in [("halfstep","nominal")]:
 z=compare_pair(cases[x],cases[y],cadence=.001,max_offset=f["max_time_offset_s"],H0=f["H0_m"],continuous_mass=f["continuous_initial_mass_kg"],macro_budget=t["time_macro_budget_fraction"])
 assert z["time_alignment"]["common_frame_count"]==1601 and abs(z["series"]["time_s"][-1]-1.6)<1e-12
 pairs[x+"_vs_"+y]=z
out={"schema":"ds02.f1.full-thick-dbc-genuine-halfstep-frozen-macro-comparison.v1","physical_window_s":[0,1.6],"bindings":bindings,"pairs":pairs,"frozen_sha256":sha256(Path(b["frozen"])),"time_registration_sha256":sha256(Path(b["time_registration"])),"time_budget_fraction":t["time_macro_budget_fraction"],"claim_boundary":{"q_n":"not_granted","production_approval":"none","mass_normalization":"none","operator":"unchanged compare_pair; frozen COM/coordinate-quantiles/KE with preregistered integration allocation 1%; velocity and mass differences descriptive","geometry_identity":"byte-identical discrete initial BI4, same continuum mother condition","temporal_or_event_convergence":"full-window integration macro comparison only; transport event convergence and spatial Q-N remain ungranted"}}
Path(a.output).write_text(json.dumps(out,indent=2,allow_nan=False)+"\n")
