#!/usr/bin/env python3
"""Metadata-only fresh088 contract test; no BI4/CSV/H5 is opened."""
from pathlib import Path
import hashlib,json,py_compile,tempfile
B=Path(__file__).resolve().parents[1]
def load(n):return json.loads((B/n).read_text())
def sha(p):
 h=hashlib.sha256();
 with Path(p).open("rb") as f:
  for x in iter(lambda:f.read(1024*1024),b""):h.update(x)
 return h.hexdigest()
def main():
 q=load("initial-qa-binding.json"); d=load("fluid-lattice-cohort-diagnostic-binding.json"); c=load("central-bed-coverage-binding.json")
 assert "attempt_id" not in q
 assert q["qa_attempt_id"]=="root-stage1-f5-c082r1-voidfill-actual-native-initial-qa-281"
 assert q["gencase_attempt_id"]=="root-stage1-f5-c082r1-official-void-fill-genuine-gencase-265"
 assert q["qa_attempt_id"]!=q["gencase_attempt_id"]
 assert q["actual_counts"]["fluid_particles"]==27942
 assert q["execution_policy"]["execution_allowed"] is False and q["execution_policy"]["launch_allowed"] is False
 assert q["files"]["actual_gencase_binding"]["sha256"] == sha(B/"actual-gencase-binding.json")
 assert d["diagnostic_attempt_id"]=="root-stage1-f5-c082r1-actual-cohort-yindex-diagnostic-282"
 assert d["actual_gencase_attempt_id"]=="root-stage1-f5-c082r1-inward-analytic-bed-genuine-gencase-234"
 assert d["actual_gencase"]["actual_counts"]["fluid_particles"]==31658
 assert d["actual_candidate_gencase"]["actual_counts"]["fluid_particles"]==27942
 assert d["execution_policy"]["execution_allowed"] is False and d["execution_policy"]["launch_allowed"] is False
 assert d["source_y_index_contract"]["correct_nearest_y_index_range"]==[-7,7]
 assert c["gencase_attempt_id"]==q["gencase_attempt_id"] and c["depends_on_initial_qa_attempt"]==q["qa_attempt_id"]
 assert c["execution_policy"]["execution_allowed"] is False and c["execution_policy"]["launch_allowed"] is False
 for req_name in ("initial-qa-request.json", "central-bed-coverage-request.json", "fluid-lattice-cohort-diagnostic-request.json"):
  req=load(req_name); assert req["execution_allowed"] is False and req["launch_allowed"] is False
  for raw in req.get("input_files", []):
   path=Path(raw)
   if path.resolve().is_relative_to(B) and path.is_file():
    assert req["input_sha256"].get(raw), f"missing local source hash: {raw}"
 # Serialize/deserialize the required binding contract, independent of any science payload.
 with tempfile.NamedTemporaryFile("w+",suffix=".json") as f:
  json.dump({"qa_attempt_id":q["qa_attempt_id"],"gencase_attempt_id":q["gencase_attempt_id"],"actual_gencase":d["actual_gencase"],"diagnostic_attempt_id":d["diagnostic_attempt_id"]},f); f.flush(); x=json.load(open(f.name)); assert x["actual_gencase"]["attempt_id"]==d["actual_gencase_attempt_id"]
 for p in (B/"workers/initial_qa_worker.py",B/"workers/direct_partvtk_initial_mk50_coverage.py",B/"workers/diagnose_r1_fluid_lattice_text_rounding.py"):py_compile.compile(str(p),doraise=True)
 assert "fresh087" not in (B/"workers/initial_qa_worker.py").read_text()
 assert "fresh087" not in (B/"workers/direct_partvtk_initial_mk50_coverage.py").read_text()
 assert "fresh087" not in (B/"workers/diagnose_r1_fluid_lattice_text_rounding.py").read_text()
 print("fresh088 binding contract checks passed; no generated arrays opened")
if __name__=="__main__":main()
