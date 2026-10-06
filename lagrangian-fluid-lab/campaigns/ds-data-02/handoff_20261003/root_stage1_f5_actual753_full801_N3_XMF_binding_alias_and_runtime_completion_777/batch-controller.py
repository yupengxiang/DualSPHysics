from pathlib import Path
import subprocess,json,xml.etree.ElementTree as ET
L=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab');H=L/'campaigns/ds-data-02/handoff_20261003';O=Path(__file__).parent
load=lambda p:json.loads(Path(p).read_text())
rows=[]
for item in load(O/'actual-root-XMF-enabling-review.json')['rows']:
 p=subprocess.run([str(L/'.venv/bin/python'),str(H/'root_stage1_home_floor_inventory_dispatch_142/launch.py'),item['request']],cwd=L,text=True,capture_output=True)
 ar=Path(item['actual_attempt']);rp=ar/'execution-receipt.json';r=load(rp) if rp.exists() else {};passed=False
 if (r.get('status'),r.get('returncode'))==('completed',0):
  m=load(ar/'xmf/manifest.json');grids=ET.parse(m['xdmf']).getroot().findall('.//Grid[@GridType="Uniform"]');passed=m['frames']==801 and m['particles']==194427 and m['source_h5_read_only'] and m['source_h5_sha256']==item['producer_h5_sha256'] and m['source_h5_physical_condition_sha256']==item['source_legacy_scope'] and m['canonical_physical_condition_sha256']==item['canonical_scope'] and len(grids)==801 and all(g.find('Geometry/DataItem').get('Dimensions')==g.find('Attribute[@Name="velocity"]/DataItem').get('Dimensions')=='194427 3' for g in grids)
 row={**item,'receipt':str(rp),'status':r.get('status'),'returncode':r.get('returncode'),'launcher_returncode':p.returncode,'actual_full801_N3_XMF_pass':passed,'launcher_error':p.stderr[-1500:]};rows.append(row);print(json.dumps(row),flush=True)
 if not passed:break
v={'requested':2,'completed0':sum((r['status'],r['returncode'])==('completed',0) for r in rows),'actual_full801_N3_XMF_pass_count':sum(r['actual_full801_N3_XMF_pass'] for r in rows),'pending_held':2-len(rows),'results':rows};(O/'controller-result.json').write_text(json.dumps(v,indent=2)+'\n');print(json.dumps({k:x for k,x in v.items() if k!='results'}),flush=True);raise SystemExit(0 if v['actual_full801_N3_XMF_pass_count']==2 else 1)
