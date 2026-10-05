#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parent
TYPED=ROOT/'typed-conversion'
CASES=[
 'F1_STAGE1_DUAL_H220_DP020_VX010','F1_STAGE1_DUAL_H220_DP020_VX020',
 'F1_STAGE1_DUAL_H340_DP020_VX010','F1_STAGE1_DUAL_H340_DP020_VX020',
 'F1_STAGE1_ECC_H110_DP010_VX010','F1_STAGE1_ECC_H110_DP010_VX020',
 'F1_STAGE1_ECC_H190_DP010_VX010','F1_STAGE1_ECC_H190_DP010_VX020']
def load(p): return json.loads(Path(p).read_text())
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
errs=[]; rows=[]
for c in CASES:
 p=TYPED/'requests'/f'{c}.full-native-typed-nvme.request.json';
 if not p.exists(): errs.append(f'missing request {p}'); continue
 q=load(p)
 if not (q.get('source_only') is True and q.get('execution_allowed') is False and q.get('launch_allowed') is False): errs.append(f'{c}: disabled/source-only contract')
 files=q.get('input_files',[]); hm=q.get('input_sha256',{})
 if set(files)!=set(hm): errs.append(f'{c}: input_files/input_sha256 mismatch')
 for f in files:
  x=Path(f)
  if not x.exists(): errs.append(f'{c}: missing input {f}'); continue
  if x.suffix.lower() in {'.bi4','.h5','.csv'}: errs.append(f'{c}: raw payload in active inputs {f}')
  if x.is_file() and sha(x)!=hm[f]: errs.append(f'{c}: input hash mismatch {f}')
 d=q.get('frame0_vx_qualification_dependency',{})
 if d.get('status')!='actual_root181_completed_zero_pass' or d.get('report_passed') is not True: errs.append(f'{c}: Root181 not actual pass')
 for k in ('receipt','report'):
  if not Path(d.get(k,'')).exists(): errs.append(f'{c}: missing actual {k}')
  elif d.get(k+'_sha256')!=sha(d[k]): errs.append(f'{c}: actual {k} hash mismatch')
 if d.get('receipt_status')!='completed' or d.get('receipt_returncode')!=0: errs.append(f'{c}: actual receipt not completed/0')
 if any(v is not None for k,v in q.get('future_outputs',{}).items() if k.endswith('_sha256') or k in ('typed_partvtk_sha256',)): errs.append(f'{c}: future output hash is not null')
 w=q.get('native_full_binding',{}); expected=401 if 'DUAL' in c else 161; tmax=4.0 if 'DUAL' in c else 1.6
 if w.get('expected_frames')!=expected or w.get('tmax_s')!=tmax or w.get('tout_s')!=0.01: errs.append(f'{c}: native window changed')
 rows.append({'case':c,'attempt_id':q.get('attempt_id'),'frame0_status':d.get('status'),'frames':w.get('expected_frames'),'root181_report_sha256':d.get('report_sha256'),'root181_receipt_sha256':d.get('receipt_sha256')})
print(json.dumps({'ok':not errs,'errors':errs,'cases':rows,'raw_arrays_read':False},ensure_ascii=False,indent=2))
sys.exit(1 if errs else 0)
