#!/usr/bin/env python3
"""Metadata/XML-only preflight for F5 fresh091 actual GenCase binding."""
from __future__ import annotations
import hashlib,json
import xml.etree.ElementTree as ET
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
CASE="F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1"
GATT="root-stage1-f5-c082s1-solid-fluid-recovery-genuine-gencase-293"
COUNTS={"total_particles":194427,"fixed_particles":158559,"moving_particles":4210,"floating_particles":0,"fluid_particles":31658}
def req(v,m):
 if not v: raise AssertionError(m)
def sha(p):
 h=hashlib.sha256()
 with p.open("rb") as f:
  for b in iter(lambda:f.read(1048576),b""): h.update(b)
 return h.hexdigest()
def main():
 side=json.loads((ROOT/"bindings/actual-gencase-293-binding.json").read_text())
 req(side["schema"]=="ds02.f5.c082s1.actual-gencase-binding.fresh091.v1","sidecar schema")
 req(side["attempt_id"]==GATT and side["case_id"]==CASE and side["actual_counts"]==COUNTS,"actual producer identity/counts")
 req(side["solver_dimension_from_gencase"]==3,"producer dimension")
 receipt=Path(side["files"]["execution_receipt"]["path"]); report=Path(side["files"]["prepared_input_report"]["path"]); xml=Path(side["files"]["generated_xml"]["path"]); bi4=Path(side["files"]["generated_bi4"]["path"])
 req(receipt.is_file() and sha(receipt)==side["files"]["execution_receipt"]["sha256"],"receipt metadata hash")
 req(report.is_file() and sha(report)==side["files"]["prepared_input_report"]["sha256"],"prepared report metadata hash")
 req(xml.is_file(),"generated XML missing")
 req(bi4.is_file(),"generated BI4 missing")
 r=json.loads(receipt.read_text()); p=json.loads(report.read_text())
 req(r["status"]=="completed" and r["returncode"]==0 and r["request"]["attempt_id"]==GATT,"receipt status/identity")
 req(p["actual_total_particles"]==COUNTS["total_particles"] and p["generated_xml_particle_counts"]=={"fixed":158559,"moving":4210,"floating":0,"fluid":31658},"prepared counts")
 req(side["files"]["generated_xml"]["sha256"]==p["xml_sha256"],"XML producer SHA")
 req(side["files"]["generated_bi4"]["sha256"]==p["bi4_sha256"],"BI4 producer SHA")
 xr=ET.parse(xml).getroot(); particles=xr.find("./execution/particles"); req(particles is not None and particles.get("np")==str(COUNTS["total_particles"]),"XML total")
 req(xr.find("./execution/constants/data2d").get("value")=="false","XML 3-D")
 names=("fixed","moving","floating","fluid"); xmlcounts={n:sum(int(x.get("count","-1")) for x in particles.findall(n)) for n in names}; req(xmlcounts=={k:COUNTS[k+"_particles"] for k in names},"XML counts")
 qa=json.loads((ROOT/"bindings/actual-initial-qa-306-binding.json").read_text()); req(qa["schema"]=="ds02.f5.c082s1.actual-initial-qa-binding.fresh091.v1","QA schema"); req(qa["actual_counts"]==COUNTS and qa["gencase_attempt_id"]==GATT,"QA actual binding")
 req(set(qa["files"])=={"gencase_receipt","prepared_input_report","generated_xml","generated_bi4","gencase_output_root","actual_gencase_binding","partvtk","qa054_tool"},"QA worker file contract")
 cov=json.loads((ROOT/"bindings/actual-mk50-coverage-307-binding.json").read_text()); req(cov["schema"]=="ds02.f5.c082s1.initial-mk50-coverage-binding.fresh091.v1","coverage schema"); req(cov["actual_counts"]==COUNTS and cov["gencase_attempt_id"]==GATT,"coverage actual binding")
 req(set(cov["files"])=={"actual_gencase_binding","gencase_receipt","prepared_input_report","generated_xml","gencase_output_root","qa_provenance","official_csv"},"coverage worker file contract")
 for name in ("initial-qa-request.json","central-bed-coverage-request.json","short-native-qualification-request.json","typed-conversion-request-template.json","xmf-request-template.json","short-bed-audit-request.json"):
  d=json.loads((ROOT/"requests"/name).read_text()); req(d["execution_allowed"] is False and d["launch_allowed"] is False and d["full801_authorized"] is False,name+" disabled")
  req(not any("resource-ledger.json" in x for x in d.get("input_files",[])),name+" live ledger")
 for d in (json.loads((ROOT/"requests/initial-qa-request.json").read_text()),json.loads((ROOT/"requests/central-bed-coverage-request.json").read_text())):
  req(set(d["input_files"])==set(d["input_sha256"]),"input hash key closure")
 # Do not open/hash BI4; only check request registration equals official producer metadata.
 for name in ("initial-qa-request.json","central-bed-coverage-request.json"):
  d=json.loads((ROOT/"requests"/name).read_text()); vals=[d["input_sha256"][x] for x in d["input_files"] if x==str(bi4)]; req(vals==[p["bi4_sha256"]],name+" BI4 SHA provenance")
 print(json.dumps({"status":"preflight_pass","actual_counts":COUNTS,"actual_gencase_attempt":GATT,"bi4_opened":False,"bi4_hash_rehashed":False,"initial_qa":"disabled_pending_root_launch","mk50_coverage":"disabled_pending_actual_initial_qa","full801":False},sort_keys=True))
if __name__=="__main__": main()
