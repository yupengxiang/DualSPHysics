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
import argparse, copy, hashlib, importlib.util, json, tempfile
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
DOWNSTREAM_BINDING_FIELDS={'xmf_manifest','xmf_manifest_sha256','xdmf','xdmf_sha256','xmf_receipt','xmf_receipt_sha256'}
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
    for key in DOWNSTREAM_BINDING_FIELDS: result.pop(key,None)
    return result

def _validate_downstream_refs(binding: dict[str,Any]) -> None:
    for path_key,hash_key in (('xmf_manifest','xmf_manifest_sha256'),('xdmf','xdmf_sha256'),('xmf_receipt','xmf_receipt_sha256')):
        raw=binding.get(path_key); digest=binding.get(hash_key)
        if raw is None:
            _require(digest is None,f'{path_key} hash without path'); continue
        p=Path(str(raw)); _require(p.is_file() and p.suffix.lower() not in SCIENCE_SUFFIXES,f'{path_key} metadata path invalid')
        _require(isinstance(digest,str) and _sha(p)==digest,f'{path_key} metadata SHA mismatch')

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
    print('fresh161 original metadata-gate identity regression passed')

def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--check',action='store_true'); parser.add_argument('--binding',type=Path); parser.add_argument('--trajectory-h5',type=Path); parser.add_argument('--xdmf',type=Path); parser.add_argument('--output-dir',type=Path); args=parser.parse_args(argv)
    if args.check: _check_case_rebind_regression(); return 0
    required=(args.binding,args.trajectory_h5,args.xdmf,args.output_dir)
    if any(x is None for x in required): parser.error('--binding, --trajectory-h5, --xdmf, and --output-dir are required')
    binding=validate_binding(args.binding); original=_load_original(); _bind_original_case_id(original,binding)
    return invoke_original(original,binding,args.trajectory_h5,args.xdmf,args.output_dir)
if __name__=='__main__': raise SystemExit(main())
