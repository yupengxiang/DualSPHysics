import argparse,importlib.util,json,os,tempfile,sys
from pathlib import Path
import h5py,numpy as np
LAB=Path(__file__).resolve().parents[6];sys.path.insert(0,str(LAB/"scripts"))
from ds_data02_f3_nvme_input_audit_v1 import verified_copy
p=argparse.ArgumentParser();p.add_argument("--binding",required=True);p.add_argument("--output",required=True);a=p.parse_args();b=json.loads(Path(a.binding).read_text());out=Path(a.output);assert not out.exists()
cfg=json.loads(Path(b["event_config"]).read_text());cfg2=json.loads(Path(b["half_event_config"]).read_text())
for key in set(cfg)|set(cfg2):
 if key!="geometry_sha256":assert cfg.get(key)==cfg2.get(key)
registration=json.loads(Path(b["time_registration"]).read_text());assert b["event_absolute_budget_s"]==registration["event_time_budget_s"] and b["integration_share"]==registration["integration_share"]==.2
proof=json.loads(Path(b["physical_proof"]).read_text());assert all(x["physical_condition_sha256"]==b["physical_condition_sha256"] for x in proof["bindings"].values())
parent=Path("/tmp/ds-data-02-root-nvme");needed=sum(Path(b[k]["native_labels_h5"]).stat().st_size for k in ["nominal","halfstep"]);z=os.statvfs(parent);assert z.f_bavail*z.f_frsize>=needed+100*2**30
spec=importlib.util.spec_from_file_location("selected_f1_compare",Path(__file__).with_name("selected_guard_fixed.py"));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
with tempfile.TemporaryDirectory(prefix="f1-native-paired-023-",dir=parent) as tmp:
 local={};failure={};native_times={}
 for role in ["nominal","halfstep"]:
  c=b[role];r=json.loads(Path(c["execution_receipt"]).read_text());assert r["status"]=="completed" and r["returncode"]==0
  lr=json.loads(Path(c["label_report"]).read_text());assert lr["closure"]["passed"] and lr["frames"]==1601 and lr["identities"]==1032852 and lr["sha256"]==c["native_labels_sha256"]
  path=Path(tmp)/(role+".h5");verified_copy(Path(c["native_labels_h5"]),path,c["native_labels_sha256"]);local[role]=path
  with h5py.File(path,"r") as h:
   assert h.attrs["source_hdf5_sha256"]==c["expected_source_hdf5_sha256"] and h.attrs["complete"]
   assert json.loads(h.attrs["config_json"])== (cfg if role=="nominal" else cfg2)
   mass=h["initial_fluid_mass_kg"][:];fluid=mass>0;assert len(mass)==1032852 and np.sum(fluid)==643200 and np.all(mass[fluid]==.0001250000059371814)
   assert np.array_equal(h["particle_id"][:],np.arange(1032852)) and np.all(h["particle_zone"][:]==0)
   t=h["time"][:];assert len(t)==1601 and t[0]==0 and 1.6<=t[-1]<=1.6002015 and np.all(np.diff(t)>0)
   assert np.max(np.abs(t-np.arange(1601)*.001))<=.0002015;native_times[role]=[float(t[0]),float(t[-1])]
   failure[role]=h["failure_reason"][:][fluid]
   if role=="nominal":source_labels=h["source_label"][:]
   else:assert np.array_equal(source_labels,h["source_label"][:])
 report=m.compare_nominal_vs_half_labels(local["nominal"],local["halfstep"],b["event_config"],event_absolute_budget_s=b["event_absolute_budget_s"],integration_share=b["integration_share"],expected_nominal_sha256=b["nominal"]["native_labels_sha256"],expected_half_sha256=b["halfstep"]["native_labels_sha256"],physical_condition_sha256=b["physical_condition_sha256"])
 transitions=[]
 for x,y in np.unique(np.column_stack([failure["nominal"],failure["halfstep"]]),axis=0):
  n=int(np.sum((failure["nominal"]==x)&(failure["halfstep"]==y)));transitions.append({"nominal_reason":int(x),"halfstep_reason":int(y),"count":n,"native_mass_kg":n*.0001250000059371814})
 report["actual_failure_reason_transitions"]=transitions;report["actual_native_time_support_s"]=native_times
 report["bindings"]={role:b[role] for role in ["nominal","halfstep"]};report.pop("bounded_resource_evidence",None)
 report["guard_review"]={"same_UID_source_label_exactnativeweights":True,"all23_source_closure_checks_passed":True,"config_scientific_specs_equal":True,"geometry_sha256_metadata_difference_retained":{role:c["geometry_sha256"] for role,c in [("nominal",cfg),("halfstep",cfg2)]},"saved_indices":"same frozen nominal .001 bins; actual timestamps retained; no rescaling of residence or physicaltime","q_n":"not_granted"}
report["private_scratch_removed"]=True;out.write_text(json.dumps(report,indent=2,allow_nan=False)+"\n")
print(json.dumps({"fate_switches":report["fate_switches"]["total_switched_particles"],"q_n":"not_granted"}))
