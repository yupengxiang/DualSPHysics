"""Generate a common-volume ladder without launching any solver."""
from pathlib import Path
import xml.etree.ElementTree as ET
import subprocess, os, re, json
LAB=Path(__file__).resolve().parents[2]
source=LAB/'campaigns/l1-resume/artifacts/branches/F3_3D_CELL2_plain_dp0p01_INPUTFIX/F3_3D_CELL2_plain_dp0p01_Def.xml'
binary=LAB/'vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64'
rows=[]
for dp in (.01,.0075,.006):
 name='F3_CELL3_plain_'+str(dp).replace('.','p')
 folder=LAB/'campaigns/l1-resume/artifacts/cell3'/name
 folder.mkdir(parents=True,exist_ok=True)
 tree=ET.parse(source); root=tree.getroot(); definition=root.find('.//geometry/definition'); definition.set('dp',str(dp))
 for axis in 'xyz': definition.find('pointref').set(axis,str(dp/2))
 fluid,bound=root.findall('.//mainlist/drawbox')
 for axis,low,size in zip('xyz',(-.45,-.09,0),(.9,.18,.09)):
  fluid.find('point').set(axis,str(low+dp/2)); fluid.find('size').set(axis,str(size-dp))
 for axis,low,size in zip('xyz',(-.45,-.09,0),(.9,.18,.51)):
  bound.find('point').set(axis,str(low-dp/2)); bound.find('size').set(axis,str(size+(dp if axis!='z' else dp/2)))
 path=folder/(name+'_Def.xml'); tree.write(path,encoding='utf-8',xml_declaration=True)
 env=dict(os.environ,OMP_NUM_THREADS='8')
 proc=subprocess.run([str(binary),str(path.with_suffix('')),str(folder/name),'-save:all'],env=env,cwd=folder,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
 (folder/'gencase.log').write_text(proc.stdout)
 match=re.search(r'Fluid\.+\s*:\s*([\d,]+)',proc.stdout)
 n=int(match[1].replace(',','')) if match else None
 mass=n*1000*dp**3 if n else None
 rows.append(dict(case=name,dp=dp,exit_code=proc.returncode,fluid_particles=n,mass_kg=mass,relative_mass_error=abs(mass/14.58-1) if mass else None))
print(json.dumps(rows,indent=2))
(LAB/'diagnostics/f3-audit/cell3-preflight.json').write_text(json.dumps(rows,indent=2)+'\n')
