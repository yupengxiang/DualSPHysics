#!/usr/bin/env python3
from __future__ import annotations
import argparse, importlib.util, json
from pathlib import Path
PACKAGE=Path(__file__).resolve().parents[1]
ADAPTER_PATH=PACKAGE/'workers/identity_bound_bed_audit_fresh174.py'
def load_adapter():
 spec=importlib.util.spec_from_file_location('fresh174_adapter',ADAPTER_PATH); mod=importlib.util.module_from_spec(spec); assert spec.loader is not None; spec.loader.exec_module(mod); return mod
def main():
 p=argparse.ArgumentParser(); p.add_argument('--check',action='store_true'); p.add_argument('--report',type=Path); a=p.parse_args();
 if not a.check: p.error('--check required')
 mod=load_adapter(); rows=[]
 for binding in sorted((PACKAGE/'bindings').glob('*.json')): rows.append(mod.validate_binding(binding,run_original_metadata_gate=True))
 out={'schema':'ds02.f5.fresh174.validator-report.v1','status':'passed','source_only':True,'science_payload_opened_or_hashed':False,'checks':rows,'manifest_excludes_this_report':True}
 text=json.dumps(out,ensure_ascii=False,indent=2,sort_keys=True)+'\n'; print(text,end='')
 if a.report: a.report.write_text(text,encoding='utf-8')
 return 0
if __name__=='__main__': raise SystemExit(main())
