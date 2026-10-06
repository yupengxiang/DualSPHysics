from pathlib import Path
import os,json,hashlib,datetime
H=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003');O=next(H.glob('root*1217'));D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
a=json.loads((O/'failed-attempts-current-storage-audit.json').read_text());rs=[x for x in a['failed_attempts'] if Path(x['receipt']).parent.name in ('conversion-f2-comm4-center_v1_fine-fullstate-compat-v2','conversion-f2-comm4-offset_v1_fine-fullstate-compat-v2')]
needles={str(Path(x['receipt']).parent):x for x in rs};refs=[];files=set()
roots=[D/'families',Path('/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02')]
roots += [p/'lagrangian-fluid-lab/campaigns/ds-data-02' for p in Path('/home/jade/.codex/worktrees').glob('ds-data-02-*') if p.is_dir()]
for root in roots:
 for base,dirs,names in os.walk(root,followlinks=False):
  dirs[:]=[n for n in dirs if n not in ('.git','.venv','__pycache__') and not (Path(base)/n).is_symlink()]
  for n in names:
   p=Path(base)/n
   if p.suffix.lower() not in ('.json','.xml','.xmf','.xdmf','.py','.md','.txt','.yaml','.yml'):continue
   if p.is_symlink() or p in files:continue
   files.add(p)
   try:
    if p.stat().st_size>32*1024**2:continue
    t=p.read_text(errors='replace')
   except OSError:continue
   for prefix in needles:
    if prefix in t or Path(prefix).name in t:
     refs.append({'candidate_attempt':prefix,'metadata':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'exact_prefix_present':prefix in t})
proc=[]
for p in Path('/proc').iterdir():
 if not p.name.isdigit():continue
 try:
  cmd=(p/'cmdline').read_bytes().replace(b'\0',b' ').decode(errors='replace');cwd=os.readlink(p/'cwd')
 except (OSError,PermissionError):continue
 for prefix in needles:
  hits=[]
  if prefix in cmd or Path(prefix).name in cmd:hits.append('cmdline')
  if cwd.startswith(prefix):hits.append('cwd')
  try:
   for fd in (p/'fd').iterdir():
    try: target=os.readlink(fd)
    except OSError:continue
    if target.startswith(prefix):hits.append('fd:'+target)
  except OSError:pass
  if hits:proc.append({'pid':int(p.name),'candidate_attempt':prefix,'hits':hits})
o={'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'candidate_attempts':list(needles),'metadata_files_scanned':len(files),'metadata_references':refs,'live_process_references':proc,'payload_contents_read':False}
(O/'failed-converter-csv-dependency-reference-audit.json').write_text(json.dumps(o,ensure_ascii=False,indent=2)+'\n');(O/'dependency-audit-source.py').write_bytes(Path(__file__).read_bytes());print('files',len(files),'references',len(refs),'live',proc)
for r in refs: print(json.dumps(r,ensure_ascii=False))
