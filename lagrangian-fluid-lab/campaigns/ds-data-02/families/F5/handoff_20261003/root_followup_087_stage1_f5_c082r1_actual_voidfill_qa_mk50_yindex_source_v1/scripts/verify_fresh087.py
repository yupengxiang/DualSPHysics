#!/usr/bin/env python3
"""Metadata-only verification for fresh087; never opens BI4/CSV/H5 arrays."""
from pathlib import Path
import hashlib,json,py_compile
BASE=Path(__file__).resolve().parents[1]
def load(name): return json.loads((BASE/name).read_text())
def sha(path):
 h=hashlib.sha256();
 with Path(path).open("rb") as f:
  for block in iter(lambda:f.read(1024*1024),b""): h.update(block)
 return h.hexdigest()
def main():
 a=load("actual-gencase-binding.json"); q=load("initial-qa-binding.json"); c=load("central-bed-coverage-binding.json"); d=load("fluid-lattice-cohort-diagnostic-binding.json")
 assert a["status"]=="actual_genuine_gencase_completed_metadata_bound"
 assert a["actual_counts"]=={"total_particles":194427,"fixed_particles":162005,"moving_particles":4480,"floating_particles":0,"fluid_particles":27942,"solver_dimension":3,"xml_particle_counts":{"fixed":162005,"moving":4480,"floating":0,"fluid":27942}}
 assert q["actual_counts"]==a["actual_counts"] and c["actual_counts"]["total_particles"]==194427 and c["actual_counts"]["fluid_particles"]==27942
 assert q["execution_policy"]["execution_allowed"] is False and c["execution_policy"]["execution_allowed"] is False and d["execution_policy"]["execution_allowed"] is False
 assert d["source_y_index_contract"]["correct_nearest_y_index_range"]==[-7,7]
 assert q["files"]["generated_bi4"]["sha256"]=="ea361f560a6b6aa3f10d46ed379efde01a026a46dd3e515b5ebc61b8540064bc"
 for worker in (BASE/"workers/initial_qa_worker.py",BASE/"workers/direct_partvtk_initial_mk50_coverage.py",BASE/"workers/diagnose_r1_fluid_lattice_text_rounding.py"):
  py_compile.compile(str(worker),doraise=True)
 print("fresh087 metadata/source checks passed; no generated arrays opened")
if __name__=="__main__": main()
