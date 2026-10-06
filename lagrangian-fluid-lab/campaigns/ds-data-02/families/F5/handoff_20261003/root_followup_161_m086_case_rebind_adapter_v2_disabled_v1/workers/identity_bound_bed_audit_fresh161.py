#!/usr/bin/env python3
"""Fresh161 M086 case-identity adapter for the unchanged fresh138 bed audit.

The original numerical worker has a module-global base CASE_ID.  The actual M086
producer receipts use the suffixed producer case ID.  This adapter verifies the
original source digest, sets only the loaded module's CASE_ID in memory to the
binding's producer identity, then delegates to original.main.  It never edits
receipts, arrays, H5/XDMF data, geometry, thresholds, or the consumed fresh159
package.
"""
from __future__ import annotations
import argparse, copy, hashlib, importlib.util, json, shutil, tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

BINDING_SCHEMA='ds02.f5.c082s1.full-event-bed-audit-binding.fresh138.v1'
ADAPTER_SCHEMA='ds02.f5.c082s1.m086.case-rebind-adapter.fresh161.v2'
BASE_CASE_ID='F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1'
PRODUCER_CASE_ID='F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M086_T085_NEXT34'
PHYSICAL_CASE_ID='F5_COMPACT_RUNUP_RECOVERY_C082S1_M086_T085'
ORIGINAL_WORKER=Path('/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_138_stage1_f5_remaining10_full801_downstream_disabled_v1/workers/bed_audit_full801_fresh138.py')
ORIGINAL_WORKER_SHA='89be048da1df6bae49627308edb35a8a1936bc0888259cb5ab3d195307b550e2'
MUTABLE_ROOT_BOUND_FIELDS={
    # This is a producer-report representation normalization only: the
    # numeric counts are unchanged, while the old binding had an extra
    # data2d=false bookkeeping key that the actual QA report omits.
    'actual_counts',
    # The initial-QA receipt is already a producer artifact.  Its output root
    # is filled from that receipt when this adapter is materialized.
    'initial_qa_output_root',
    # These are downstream XMF identity/provenance fields.  They may be filled
    # only from a real Root-owned XMF receipt/manifest; all science/physics
    # binding fields remain immutable.
    'xmf_manifest','xmf_manifest_sha256','xdmf','xdmf_sha256',
    'xmf_receipt','xmf_receipt_sha256','xmf_attempt_id',
}
SCIENCE_SUFFIXES={'.h5','.hdf5','.bi4','.ibi4','.csv','.dat','.vtk','.vtu','.npy','.npz'}

def _require(condition: bool, message: str) -> None:
    if not condition: raise ValueError(message)
def _sha(path: Path) -> str:
    if path.suffix.lower() in SCIENCE_SUFFIXES: raise ValueError(f'science payload hash forbidden: {path}')
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''): h.update(block)
    return h.hexdigest()
def _load(path: Path) -> dict[str,Any]:
    value=json.loads(path.read_text())
    _require(isinstance(value,dict),f'JSON object required: {path}')
    return value

def _identity_without_adapter(value: dict[str,Any]) -> dict[str,Any]:
    result=copy.deepcopy(value); result.pop('identity_adapter',None)
    for key in MUTABLE_ROOT_BOUND_FIELDS: result.pop(key,None)
    return result

def _validate_downstream_refs(binding: dict[str,Any]) -> None:
    for path_key,hash_key in (('xmf_manifest','xmf_manifest_sha256'),('xdmf','xdmf_sha256'),('xmf_receipt','xmf_receipt_sha256')):
        raw=binding.get(path_key); digest=binding.get(hash_key)
        if raw is None:
            _require(digest is None,f'{path_key} hash without path'); continue
        p=Path(str(raw)); _require(p.is_file() and p.suffix.lower() not in SCIENCE_SUFFIXES,f'{path_key} metadata path invalid')
        _require(isinstance(digest,str) and _sha(p)==digest,f'{path_key} metadata SHA mismatch')
    xmf_attempt_id=binding.get('xmf_attempt_id')
    if xmf_attempt_id is not None:
        _require(isinstance(xmf_attempt_id,str) and bool(xmf_attempt_id),'xmf_attempt_id must be a non-empty string when bound')
        _require(binding.get('xmf_manifest') is not None,'xmf_attempt_id requires an XMF manifest')
        receipt_path=binding.get('xmf_receipt')
        if receipt_path is not None:
            receipt=_load(Path(str(receipt_path)))
            observed_attempt=receipt.get('request',{}).get('attempt_id',receipt.get('attempt_id'))
            if observed_attempt is not None:
                _require(observed_attempt==xmf_attempt_id,'XMF receipt attempt identity mismatch')
            observed_case=receipt.get('request',{}).get('case_id',receipt.get('case_id'))
            if observed_case is not None:
                _require(observed_case==binding.get('case_id'),'XMF receipt case identity mismatch')
    manifest_path=binding.get('xmf_manifest')
    if manifest_path is not None:
        manifest=_load(Path(str(manifest_path)))
        _require(manifest.get('case_id')==binding.get('case_id'),'XMF manifest case identity mismatch')
        if xmf_attempt_id is not None and manifest.get('attempt_id') is not None:
            _require(manifest.get('attempt_id')==xmf_attempt_id,'XMF manifest attempt identity mismatch')

def _write_json(path: Path, value: dict[str,Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,sort_keys=True)+'\n')

def _copy_metadata(source: Path, destination: Path) -> None:
    _require(source.suffix.lower() not in SCIENCE_SUFFIXES,'science metadata copy forbidden')
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source,destination)

def _real_original_metadata_gate_regression(binding_path: Path, original: Any) -> None:
    """Run the unchanged fresh138 metadata gate on a metadata-only toy fixture.

    The fixture uses real producer JSON/XML metadata as its source, but writes
    temporary receipt copies and an empty 801-name Part_* listing.  No H5,
    BI4, CSV, DAT, VTK, or other science payload is opened or hashed.  This
    catches both the module-global CASE_ID failure and the missing
    initial_qa_output_root failure before a real Root-owned XMF is attached.
    """
    source=_load(binding_path)
    with tempfile.TemporaryDirectory(prefix='f5-m086-real-metadata-gate-') as temp_name:
        root=Path(temp_name)
        toy=copy.deepcopy(source)
        toy['initial_qa_output_root']=str(root/'initial-qa')
        toy['xmf_attempt_id']='toy-root-xmf-attempt'

        gencase=_load(Path(str(source['gencase_receipt'])))
        gencase_root=root/'gencase'; gencase['output_root']=str(gencase_root)
        gencase_path=root/'metadata/gencase-receipt.json'; _write_json(gencase_path,gencase)
        toy['gencase_receipt']=str(gencase_path); toy['gencase_receipt_sha256']=_sha(gencase_path)

        prepared_source=Path(str(source['gencase_prepared_report']))
        prepared_path=root/'gencase/prepared/prepared-input-report.json'; _copy_metadata(prepared_source,prepared_path)
        toy['gencase_prepared_report']=str(prepared_path); toy['gencase_prepared_report_sha256']=_sha(prepared_path)
        xml_source=Path(str(source['canonical_generated_xml']))
        xml_path=root/'gencase/prepared/generated.xml'; _copy_metadata(xml_source,xml_path)
        toy['canonical_generated_xml']=str(xml_path); toy['canonical_generated_xml_sha256']=_sha(xml_path)
        toy['gencase_output_root']=str(gencase_root); toy['gencase_prepared_output_root']=str(xml_path.parent)

        qa=_load(Path(str(source['initial_qa_receipt'])))
        qa_root=root/'initial-qa'; qa['output_root']=str(qa_root)
        qa_path=root/'metadata/initial-qa-receipt.json'; _write_json(qa_path,qa)
        toy['initial_qa_receipt']=str(qa_path); toy['initial_qa_receipt_sha256']=_sha(qa_path)
        qa_report_source=Path(str(source['initial_qa_report']))
        qa_report_path=root/'initial-qa/placement/audit.json'; _copy_metadata(qa_report_source,qa_report_path)
        toy['initial_qa_report']=str(qa_report_path); toy['initial_qa_report_sha256']=_sha(qa_report_path)
        toy['initial_qa_output_root']=str(qa_root)

        native=_load(Path(str(source['full_native_receipt'])))
        native_root=root/'native'; native['output_root']=str(native_root)
        native_path=root/'metadata/native-receipt.json'; _write_json(native_path,native)
        toy['full_native_receipt']=str(native_path); toy['full_native_receipt_sha256']=_sha(native_path)
        data_root=native_root/'solver_output/data'; data_root.mkdir(parents=True,exist_ok=True)
        # The original gate checks the exact frame-name sequence only.  These
        # are empty toy placeholders, never native data and never opened.
        for index in range(801): (data_root/f'Part_{index:04d}.bi4').touch()
        toy['full_native_output_root']=str(native_root); toy['full_native_data_root']=str(data_root)

        typed_source=Path(str(source['full_typed_conversion_report']))
        typed_path=root/'metadata/typed-conversion-report.json'; _copy_metadata(typed_source,typed_path)
        toy['full_typed_conversion_report']=str(typed_path); toy['full_typed_conversion_report_sha256']=_sha(typed_path)

        xmf_path=root/'xmf/manifest.json'
        _write_json(xmf_path,{
            'schema':'toy-root-xmf-manifest', 'case_id':toy['case_id'],
            'attempt_id':toy['xmf_attempt_id'], 'frames':toy['expected_frames'],
            'particles':toy['expected_particle_axis'],
            'source_h5_sha256':toy['trajectory_h5_sha256'],
            'physical_condition_sha256':toy['physical_condition_sha256'],
            'canonical_physical_condition_sha256':toy['physical_condition_sha256'],
        })
        toy['xmf_manifest']=str(xmf_path); toy['xmf_manifest_sha256']=_sha(xmf_path)
        xmf_receipt_path=root/'xmf/execution-receipt.json'
        _write_json(xmf_receipt_path,{
            'status':'completed', 'returncode':0,
            'request':{'case_id':toy['case_id'],'attempt_id':toy['xmf_attempt_id']},
        })
        toy['xmf_receipt']=str(xmf_receipt_path); toy['xmf_receipt_sha256']=_sha(xmf_receipt_path)
        _validate_downstream_refs(toy)

        # Without this in-memory identity change the real gate must reject the
        # producer case.  With it, the same unchanged gate reaches its XMF
        # checks and returns a metadata report.
        original.CASE_ID=BASE_CASE_ID
        try: original._verify_bound_metadata(toy)
        except ValueError: pass
        else: raise AssertionError('real metadata gate accepted base CASE_ID before rebind')
        original.CASE_ID=toy['case_id']
        result=original._verify_bound_metadata(toy)
        _require(result.get('case_id')==PRODUCER_CASE_ID,'real metadata gate did not reach XMF stage')
        _require(result.get('native_conversion',{}).get('particles')==toy['expected_particle_axis'],'real metadata gate result incomplete')

def validate_binding(binding_path: Path) -> dict[str,Any]:
    binding=_load(binding_path)
    _require(binding.get('schema')==BINDING_SCHEMA,'fresh138 binding schema mismatch')
    adapter=binding.get('identity_adapter',{})
    _require(adapter.get('schema')==ADAPTER_SCHEMA,'fresh161 adapter schema missing')
    _require(binding.get('case_id')==PRODUCER_CASE_ID and binding.get('producer_case_id')==PRODUCER_CASE_ID,'producer case identity mismatch')
    _require(binding.get('physical_case_id')==PHYSICAL_CASE_ID,'physical identity mismatch')
    previous=Path(str(adapter.get('previous_adapter_binding_path','')))
    _require(previous.is_file(),'previous fresh159 binding missing')
    _require(_sha(previous)==adapter.get('previous_adapter_binding_sha256'),'previous fresh159 binding SHA mismatch')
    old=_load(previous)
    _require(old.get('identity_adapter',{}).get('schema')=='ds02.f5.c082s1.m086.identity-adapter.fresh159.v1','fresh159 identity adapter expected')
    _require(_identity_without_adapter(binding)==_identity_without_adapter(old),'fresh161 changed scientific binding fields')
    base=Path(str(adapter.get('base_binding_path','')))
    _require(base.is_file() and _sha(base)==adapter.get('base_binding_sha256'),'fresh158 base binding closure')
    base_value=_load(base)
    _require(base_value.get('case_id')==BASE_CASE_ID and base_value.get('producer_case_id')==PRODUCER_CASE_ID,'base binding identity')
    _require(adapter.get('base_case_id')==BASE_CASE_ID and adapter.get('producer_case_id')==PRODUCER_CASE_ID,'adapter identity')
    _require(adapter.get('physical_case_id')==PHYSICAL_CASE_ID,'adapter physical identity')
    _require(adapter.get('original_worker_path')==str(ORIGINAL_WORKER),'original worker path')
    _require(_sha(ORIGINAL_WORKER)==ORIGINAL_WORKER_SHA==adapter.get('original_worker_sha256'),'original worker SHA')
    adapter_worker=Path(str(adapter.get('adapter_worker_path','')))
    _require(adapter_worker.is_file() and adapter_worker == Path(__file__).resolve(),'adapter worker path')
    _require(adapter.get('adapter_worker_sha256')==_sha(adapter_worker),'adapter worker SHA')
    _require(adapter.get('numerical_logic_unchanged') is True and adapter.get('array_edit_allowed') is False and adapter.get('receipt_edit_allowed') is False and adapter.get('threshold_edit_allowed') is False,'mutation policy')
    _validate_downstream_refs(binding)
    for key in ('full_native_receipt','full_typed_receipt','full_typed_conversion_report','canonical_generated_xml','gencase_receipt','gencase_prepared_report','initial_qa_receipt','initial_qa_report'):
        if binding.get(key):
            p=Path(str(binding[key])); _require(p.is_file() and p.suffix.lower() not in SCIENCE_SUFFIXES,f'{key} missing or science')
    qa_receipt=_load(Path(str(binding['initial_qa_receipt'])))
    _require(qa_receipt.get('status')=='completed' and qa_receipt.get('returncode')==0,'initial QA producer receipt not completed/0')
    _require(Path(str(qa_receipt.get('output_root',''))).resolve()==Path(str(binding.get('initial_qa_output_root',''))).resolve(),'initial QA output root does not match receipt')
    qa_report=_load(Path(str(binding['initial_qa_report'])))
    _require(qa_report.get('actual_counts')==binding.get('actual_counts'),'actual_counts do not match initial QA report')
    _require(binding.get('native_bed_marker_mk')==50 and binding.get('source_bed_marker_mkbound')==40,'marker mapping')
    return binding

def _load_original():
    _require(_sha(ORIGINAL_WORKER)==ORIGINAL_WORKER_SHA,'original fresh138 source changed')
    spec=importlib.util.spec_from_file_location('fresh138_original_bed_audit_fresh161',ORIGINAL_WORKER)
    _require(spec is not None and spec.loader is not None,'cannot load original worker')
    original=importlib.util.module_from_spec(spec); spec.loader.exec_module(original)
    _require(getattr(original,'CASE_ID',None)==BASE_CASE_ID,'original module base CASE_ID unexpected')
    return original

def _bind_original_case_id(original: Any, binding: dict[str,Any]) -> None:
    expected=binding.get('case_id')
    _require(expected==PRODUCER_CASE_ID,'binding is not producer identity')
    # This is the only mutation: the loaded original module's global identity.
    original.CASE_ID=expected
    _require(getattr(original,'CASE_ID',None)==expected,'original module CASE_ID was not rebound')

def invoke_original(original: Any, binding: dict[str,Any], trajectory_h5: Path, xdmf: Path, output_dir: Path) -> int:
    _bind_original_case_id(original,binding)
    with tempfile.TemporaryDirectory(prefix='f5-m086-case-rebind-') as temp_dir:
        temp_binding=Path(temp_dir)/'case-rebound-binding.json'
        temp_binding.write_text(json.dumps(binding,ensure_ascii=False,indent=2,sort_keys=True)+'\n')
        return int(original.main(['--binding',str(temp_binding),'--trajectory-h5',str(trajectory_h5),'--xdmf',str(xdmf),'--output-dir',str(output_dir)]))

def _check_case_rebind_regression() -> None:
    original=SimpleNamespace(CASE_ID=BASE_CASE_ID)
    seen={}
    def stub_main(argv):
        bp=Path(argv[argv.index('--binding')+1]); value=_load(bp)
        seen['module_case_id']=original.CASE_ID; seen['binding_case_id']=value['case_id']
        _require(original.CASE_ID==value['case_id']==PRODUCER_CASE_ID,'stub original.main identity mismatch')
        return 0
    original.main=stub_main
    result=invoke_original(original,{'case_id':PRODUCER_CASE_ID},Path('/tmp/toy-trajectory.h5'),Path('/tmp/toy.xdmf'),Path('/tmp/toy-output'))
    _require(result==0 and seen=={'module_case_id':PRODUCER_CASE_ID,'binding_case_id':PRODUCER_CASE_ID},'stub delegation regression')
    try: invoke_original(SimpleNamespace(CASE_ID=BASE_CASE_ID,main=stub_main),{'case_id':BASE_CASE_ID},Path('/tmp/a.h5'),Path('/tmp/a.xdmf'),Path('/tmp/a'))
    except ValueError: pass
    else: raise AssertionError('base identity was incorrectly accepted')
    loaded=_load_original(); _bind_original_case_id(loaded,{'case_id':PRODUCER_CASE_ID}); _require(loaded.CASE_ID==PRODUCER_CASE_ID,'real module rebind regression')
    package_binding=Path(__file__).resolve().parents[1]/'bindings/M086_T085-case-rebind-bed-binding.json'
    _require(package_binding.is_file(),'fresh161 package binding missing for real metadata regression')
    _real_original_metadata_gate_regression(package_binding,loaded)
    print('fresh161 original CASE_ID and real metadata-gate-to-XMF regression passed')

def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--check',action='store_true'); parser.add_argument('--binding',type=Path); parser.add_argument('--trajectory-h5',type=Path); parser.add_argument('--xdmf',type=Path); parser.add_argument('--output-dir',type=Path); args=parser.parse_args(argv)
    if args.check: _check_case_rebind_regression(); return 0
    required=(args.binding,args.trajectory_h5,args.xdmf,args.output_dir)
    if any(x is None for x in required): parser.error('--binding, --trajectory-h5, --xdmf, and --output-dir are required')
    binding=validate_binding(args.binding); original=_load_original(); _bind_original_case_id(original,binding)
    return invoke_original(original,binding,args.trajectory_h5,args.xdmf,args.output_dir)
if __name__=='__main__': raise SystemExit(main())
