"""Prepare a four-layer boundary contrast; never launch CFD or grant qualification."""
import json
import os
import re
import subprocess
import time
import xml.etree.ElementTree as ET
import numpy as np
from scripts.l1r_continuation_evidence import LAB,OUT,write
from scripts.l1r_q2_mdbc_bridge import sha256


def points(path):
    with path.open('rb') as f:
        while True:
            line=f.readline()
            if not line:raise ValueError('missing VTK points')
            if line.startswith(b'POINTS '):break
        _,count,kind=line.split()
        if kind!=b'float':raise ValueError('unexpected VTK scalar type')
        return np.frombuffer(f.read(int(count)*12),dtype='>f4').reshape(-1,3).astype(float)


def main():
    source=LAB/'campaigns/l1-resume/artifacts/cell3-long/F3_CELL3_LONG_dp0p01_a1p000_noslip_visco1'
    base='F3_CELL3_plain_0p01'
    name='F3_CELL4_LONG_dp0p01_a1p000_noslip_visco1'
    target=LAB/'campaigns/l1-resume/artifacts/cell4-long'/name
    report=OUT/'F3-BOUNDARY4-INPUT-PREFLIGHT.json'
    if target.exists():raise ValueError('existing preparation; inspect without overwriting')
    root=ET.parse(source/(base+'_Def.xml'))
    bounds=root.getroot().findall('.//mainlist/drawbox')[-1]
    assert bounds.find('layers').get('vdp')=='0,1,2'
    coef=float(root.getroot().find('.//coefh').get('value'));hdp=coef*np.sqrt(3)
    design=dict(scope='input preparation only; no CFD launch or qualification',predecessor='F3_CELL3_LONG_dp0p01_a1p000_noslip_visco1',source_definition_sha256=sha256(source/(base+'_Def.xml')),change={'boundary_layers_vdp':['0,1,2','0,1,2,3']},h_over_dp=hdp,kernel_diameter_over_dp=2*hdp,minimum_layers_for_native_recommendation=int(np.ceil(2*hdp)),held_fixed=['nominal physical walls including open top','fluid initial lattice','normal-generating physical surfaces','forcing and full time window','no-slip viscosity treatment','time and output steps','no projection','hard audit thresholds'],native_warning_semantics='JSph.cpp warning depends only on h/dp and density mode; it does not count layers, so warning disappearance is not a verification criterion',decision='Wait for running temporal diagnostic before selecting another CFD attempt.')
    write('F3-BOUNDARY4-DESIGN.json',design)
    target.mkdir(parents=True)
    bounds.find('layers').set('vdp','0,1,2,3')
    path=target/(name+'_Def.xml');root.write(path,encoding='utf-8',xml_declaration=True)
    start=time.monotonic()
    binary=LAB/'vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64'
    p=subprocess.run([str(binary),str(path.with_suffix('')),str(target/name),'-save:all'],cwd=target,env=dict(os.environ,OMP_NUM_THREADS='4'),capture_output=True,text=True,timeout=120)
    (target/'gencase.log').write_text(p.stdout+p.stderr)
    if p.returncode:raise ValueError('GenCase failed; retain output')
    # GenCase creates an empty acceleration template; restore only afterward.
    drive=target/'CaseSloshingAccData.csv'
    drive.write_bytes((source/'CaseSloshingAccData.csv').read_bytes())
    if drive.stat().st_size==0:raise ValueError('empty source drive')
    from scripts.l1r_input_preflight import check_input
    check_input(dict(id=name,generated_prefix=str((target/name).relative_to(LAB)),
                     solver_mode='-mdbc_noslip',time_max_s=8.35,drive_sha256=sha256(drive)))
    original=LAB/'campaigns/l1-resume/artifacts/cell3'/base
    oldfluid=points(original/(base+'_Fluid.vtk'));newfluid=points(target/(name+'_Fluid.vtk'))
    oldbound=points(original/(base+'_Bound.vtk'));newbound=points(target/(name+'_Bound.vtk'))
    unchanged=np.array_equal(oldfluid,newfluid)
    oldset={tuple(x) for x in oldbound};newset={tuple(x) for x in newbound}
    assert unchanged and oldset <= newset and len(newset)>len(oldset)
    generated=ET.parse(target/(name+'.xml')).getroot()
    result=dict(status='passed_input_only',solver_attempts=0,elapsed_seconds=time.monotonic()-start,fluid_positions_exactly_unchanged=unchanged,fluid_count=len(newfluid),fluid_mass_kg=len(newfluid)*1000*.01**3,old_boundary_count=len(oldbound),new_boundary_count=len(newbound),old_boundary_positions_retained=True,added_boundary_count=len(newset-oldset),candidate_prefix=str((target/name).relative_to(LAB)),assets={f.name:sha256(f) for f in target.iterdir() if f.suffix in ('.xml','.bi4','.csv')},design_sha256=sha256(OUT/'F3-BOUNDARY4-DESIGN.json'),qualified=False)
    write(report.name,result);print(json.dumps(result,indent=2))


if __name__=='__main__':main()
