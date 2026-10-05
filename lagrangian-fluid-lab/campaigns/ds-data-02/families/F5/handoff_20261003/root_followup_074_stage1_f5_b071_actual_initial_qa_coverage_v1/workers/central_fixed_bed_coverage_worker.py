#!/usr/bin/env python3
"""Root-only B071 frame-zero coverage worker wrapper.

The reference worker is the reviewed candidate-B worker from fresh069. This
wrapper binds it to the actual B071 GenCase receipt and refuses execution until
Root supplies a future typed HDF5/XDMF pair. It passes fluid count from the
actual receipt, never from a mother case or a hard-coded expected-fluid flag.
"""
from __future__ import annotations
import argparse, hashlib, importlib.util, json
from pathlib import Path

def sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b): h.update(b)
 return h.hexdigest()
def req(v,msg):
 if not v: raise ValueError(msg)
def load(path,digest,label):
 req(Path(path).is_file(),f'{label} missing: {path}'); req(sha(path)==digest,f'{label} SHA mismatch'); return json.loads(Path(path).read_text())
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--binding',type=Path,required=True); ap.add_argument('--output-dir',type=Path,required=True); args=ap.parse_args()
 b=json.loads(args.binding.read_text()); req(b.get('schema')=='ds02.f5.b071.central-fixed-bed-coverage-binding.v1','unexpected coverage binding schema')
 files=b['files']; receipt=load(Path(files['gencase_receipt']['path']),files['gencase_receipt']['sha256'],'B071 GenCase receipt'); req(receipt.get('status')=='completed' and receipt.get('returncode')==0,'B071 GenCase receipt not completed/zero'); req(receipt.get('solver_dimension_from_gencase')==3,'B071 GenCase is not 3-D')
 actual_total=int(receipt['total_particles']); actual_fluid=int(receipt['fluid_particles']); req(actual_total==b['actual_counts']['total_particles'] and actual_fluid==b['actual_counts']['fluid_particles'],'actual receipt counts differ from binding')
 req(files['trajectory_h5']['path'] and files['xdmf']['path'],'typed HDF5/XDMF binding is required before Root enables coverage audit')
 req(Path(files['trajectory_h5']['path']).is_file() and Path(files['xdmf']['path']).is_file(),'typed HDF5/XDMF path missing')
 spec=importlib.util.spec_from_file_location('fresh069_reference',Path(b['reference_worker']['path'])); req(spec and spec.loader,'coverage reference worker cannot load'); mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
 out=args.output_dir.resolve(); out.mkdir(parents=True,exist_ok=True)
 result=mod.run_worker(trajectory_h5=Path(files['trajectory_h5']['path']),xdmf=Path(files['xdmf']['path']),generated_xml=Path(files['generated_xml']['path']),output_dir=out,gencase_receipt=Path(files['gencase_receipt']['path']),expected_h5_sha256=files['trajectory_h5']['sha256'],expected_xdmf_sha256=files['xdmf']['sha256'],expected_xml_sha256=files['generated_xml']['sha256'],expected_fluid=actual_fluid)
 old=out/'candidate-b-initial-fixed-bed-distribution-audit.json'; req(old.is_file(),'reference coverage report missing'); report=json.loads(old.read_text())
 report['schema']='ds02.f5.b071.central-fixed-bed-coverage.v1'; report['case_id']=b['case_id']; report['actual_fluid_count_source']='genuine B071 GenCase receipt; no expected-fluid substitution'; report['no_expected_fluid_substitution']=True; report['actual_counts']=b['actual_counts']; report['root_inventory_policy_source_sha256']=b['root_inventory_policy_source_sha256']; report['no_mother_case_assumption']=True; report['interpretation_boundary']={'mk40_range_is_not_bed_only':True,'central_surface_support_is_diagnostic_only':True,'below_profile_is_frame_zero_only':True,'dynamic_solver_cause_unassigned':True,'no_full16_authorization':True,'root_manual_review_required':True}
 (out/'b071-initial-fixed-bed-coverage.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
 print(json.dumps({'status':'completed','actual_total_particles':actual_total,'actual_fluid_particles':actual_fluid,'report':str(out/'b071-initial-fixed-bed-coverage.json')},sort_keys=True))
if __name__=='__main__': main()
