from pathlib import Path
import json,hashlib,importlib.util,argparse
BAD={'.h5','.hdf5','.bi4','.csv','.dat','.vtk','.vtu','.npy','.npz'}
ORIGINAL_SHA='89be048da1df6bae49627308edb35a8a1936bc0888259cb5ab3d195307b550e2'
# Only schema/identity provenance and actual metadata-backed representations
# change; scientific inputs, geometry, thresholds and full-time contract stay exact.
CHANGES={'schema','identity_adapter','physical_condition_hash_semantics','actual_counts','initial_qa_output_root','initial_qa_report','initial_qa_report_sha256','xmf_manifest','xmf_manifest_sha256','xdmf','xdmf_sha256','xmf_receipt','xmf_receipt_sha256','xmf_attempt_id','root_original_source169_binding','root_metadata_representation_changes'}
def sha(p):
 p=Path(p);assert p.suffix.lower() not in BAD;return hashlib.sha256(p.read_bytes()).hexdigest()
def load(p):return json.loads(Path(p).read_text())
def prepare(bp):
 b=load(bp);source=b['root_original_source169_binding'];assert sha(source['path'])==source['sha256'];old=load(source['path'])
 assert {k:v for k,v in b.items() if k not in CHANGES}=={k:v for k,v in old.items() if k not in CHANGES}
 a=b['identity_adapter'];assert a['schema']=='ds02.f5.root1012.original138.generic-case-identity.v1' and sha(a['worker_path'])==a['worker_sha256']==ORIGINAL_SHA
 assert b['case_id']==b['producer_case_id']==old['case_id'] and b['physical_case_id']==old['physical_case_id']
 for role in ['gencase_receipt','initial_qa_receipt','full_native_receipt','full_typed_receipt','xmf_receipt']:
  r=load(b[role]);assert (r['status'],r['returncode'])==('completed',0) and r['request']['case_id']==b['case_id']
 t=load(b['full_typed_conversion_report']);x=load(b['xmf_manifest']);assert x['physical_case_id']==t['hash_scopes']['physical_condition']['physical_case_id']==b['physical_case_id']
 assert b['trajectory_h5_sha256']==t['output_sha256']==x['source_h5_sha256'] and b['trajectory_h5']==t['output_hdf5']
 assert b['physical_condition_sha256']==x['canonical_physical_condition_sha256']==x['physical_condition_sha256']
 assert b['source_h5_physical_condition_sha256']==t['hash_scopes']['physical_condition_sha256']==x['source_h5_physical_condition_sha256']
 spec=importlib.util.spec_from_file_location('root1012_unchanged_original138',a['worker_path']);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
 assert m.CASE_ID=='F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1';m.CASE_ID=b['case_id']
 proof=m._verify_bound_metadata(b) # unchanged original gate; real 801 filenames
 return m,b,proof
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--binding',type=Path,required=True);ap.add_argument('--trajectory-h5',type=Path,required=True);ap.add_argument('--xdmf',type=Path,required=True);ap.add_argument('--output-dir',type=Path,required=True);a=ap.parse_args();m,b,proof=prepare(a.binding)
 assert str(a.trajectory_h5)==b['trajectory_h5'] and str(a.xdmf)==b['xdmf']
 return m.main(['--binding',str(a.binding),'--trajectory-h5',str(a.trajectory_h5),'--xdmf',str(a.xdmf),'--output-dir',str(a.output_dir)])
if __name__=='__main__':raise SystemExit(main())
