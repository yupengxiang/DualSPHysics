"""Audit centered body plus the previously proven complete +Y wall lattice."""
import argparse
import json
from pathlib import Path
import subprocess
import time
import xml.etree.ElementTree as ET

import numpy as np

from ds_data02_f6_body_cellcenter_native_v1 import _vtk_points_payload
from ds_data02_runtime_v2 import parse_gencase_output, sha256


def save(path, record):
    with path.open('x') as out:
        json.dump(record,out,indent=2);out.write('\n')


def points(path):
    count, payload = _vtk_points_payload(path)
    return np.frombuffer(payload, dtype='>f4').reshape(count,3).astype(np.float64)


def face_coverage(fixed, dp):
    low, high = fixed.min(axis=0), fixed.max(axis=0)
    axes = [int(round((high[k]-low[k])/dp))+1 for k in range(3)]
    faces={}
    for label,axis,plane in [('x_low',0,low[0]),('x_high',0,high[0]),
                             ('y_low',1,low[1]),('y_high',1,high[1]),('z_low',2,low[2])]:
        selected=fixed[np.abs(fixed[:,axis]-plane)<3e-6]
        other=[k for k in range(3) if k!=axis]
        grid=np.rint((selected[:,other]-low[other])/dp).astype(np.int64)
        unique=np.unique(grid,axis=0)
        expected=axes[other[0]]*axes[other[1]]
        faces[label]=dict(actual_points=len(selected),unique_grid_points=len(unique),expected_points=expected,
                          complete=len(unique)==expected and len(selected)==expected)
    return dict(native_fixed_bounds_m=[low.tolist(),high.tolist()],axis_grid_counts=axes,faces=faces,
                all_five_faces_complete=all(x['complete'] for x in faces.values()))


def child(command, log, cwd):
    start=time.monotonic()
    with log.open('x') as out:
        process=subprocess.run(command,cwd=cwd,stdout=out,stderr=subprocess.STDOUT)
    return dict(command=command,returncode=process.returncode,
                status='completed' if process.returncode==0 else 'failed',
                elapsed_seconds=time.monotonic()-start,stdout=str(log),stdout_sha256=sha256(log))


def run(manifest_path, output):
    m=json.loads(manifest_path.read_text());case=m['case_id'];native=output/'native';native.mkdir(exist_ok=False)
    prefix=native/case;binary=m['official_bin'];definition=Path(m['definition'])
    gen=child([binary+'/GenCase_linux64',str(definition.with_suffix('')),str(prefix),'-save:all','-threads:4'],
              output/'gencase.stdout.log',definition.parent)
    gen.update(parse_gencase_output((output/'gencase.stdout.log').read_text()))
    gen.update(generated_xml=str(prefix.with_suffix('.xml')),generated_bi4=str(prefix.with_suffix('.bi4')))
    if gen['returncode']==0:
        gen.update(generated_xml_sha256=sha256(gen['generated_xml']),generated_bi4_sha256=sha256(gen['generated_bi4']))
    save(output/'gencase-child-receipt.json',gen)
    if gen['returncode']!=0:raise ValueError('Official GenCase failed')
    if any(gen.get(k)!=v for k,v in dict(total_particles=786004,fluid_particles=640000,solver_dimension_from_gencase=3).items()):
        raise ValueError('Actual native total/fluid/3D differs from repaired-wall contract')
    vtk=output/'partvtk';vtk.mkdir()
    audit=child([binary+'/PartVTK_linux64','-filedata',gen['generated_bi4'],'-filexml',gen['generated_xml'],
                 '-savecsv',str(vtk/'initial_all'),'-vars:-all,+idp,+vel,+rhop,+mass,+type,+mk,+zone',
                 '-onlytype:+all','-csvsep:1','-threads:4'],output/'partvtk.stdout.log',vtk)
    save(output/'partvtk-child-receipt.json',audit)
    if audit['returncode']!=0:raise ValueError('Official initial PartVTK failed')
    csv_path=vtk/'initial_all.csv'
    import csv
    with csv_path.open() as stream:
        for line_number,line in enumerate(stream,1):
            headers=[x.strip() for x in next(csv.reader([line]))]
            if 'Pos.x [m]' in headers and 'Type' in headers:break
            if line_number>64:raise ValueError('Particle CSV header missing')
    fields=['Pos.x [m]','Pos.y [m]','Pos.z [m]','Type','Mass [kg]','Vel.x [m/s]','Vel.y [m/s]','Vel.z [m/s]','Rhop [kg/m^3]']
    rows=np.loadtxt(csv_path,delimiter=',',skiprows=line_number,usecols=[headers.index(k) for k in fields])
    if not np.all(np.isfinite(rows)):raise ValueError('Nonfinite native initial position/type/mass/velocity/density')
    actual={str(t):int((rows[:,3]==t).sum()) for t in range(4)}
    if actual!={'0':114004,'1':0,'2':32000,'3':640000}:raise ValueError('Actual typed counts differ')
    fixed=rows[rows[:,3]==0,:3];body=rows[rows[:,3]==2,:3]
    coverage=face_coverage(fixed,.02)
    if not coverage['all_five_faces_complete']:raise ValueError('A native tank face is incomplete')
    current_bound=points(prefix.with_name(case+'_Bound.vtk'))
    repaired_bound=points(Path(m['repaired_fixed_vtk']))
    prior_bound=points(Path(m['centered_bound_vtk']))
    fixed_identical=np.array_equal(current_bound[:114004],repaired_bound[:114004])
    body_identical=np.array_equal(current_bound[114004:],prior_bound[85682:])
    fluid_identical=np.array_equal(points(prefix.with_name(case+'_Fluid.vtk')),points(Path(m['centered_fluid_vtk'])))
    center_ok=bool(np.max(np.abs(body.mean(axis=0)-[2.4,1.2,1.08]))<3e-6)
    parsed=ET.parse(prefix.with_suffix('.xml'))
    floating=parsed.find('.//execution/particles/floating')
    physical_mass=float(floating.find('massbody').get('value'))
    masspart=float(parsed.find('.//execution/constants/massfluid').get('value'))
    mass_ok=physical_mass==128 and abs(masspart*640000-5120)<1e-8
    result=dict(schema='ds02.f6.repaired-wall-centered-initial.v1',status='completed',
                actual_typed_counts=actual,actual_gencase=gen,actual_partvtk=audit,
                initial_csv=str(csv_path),initial_csv_sha256=sha256(csv_path),wall_coverage=coverage,
                old_wall_coverage=face_coverage(prior_bound[:85682],.02),
                fluid_payload_identical_to_centered004=bool(fluid_identical),
                body_payload_identical_to_centered004=bool(body_identical),
                fixed_payload_identical_to_known_repaired_source=bool(fixed_identical),
                body_center_m=body.mean(axis=0).tolist(),declared_body_mass_kg=physical_mass,
                native_fluid_mass_kg=masspart*640000,
                body_support_weight_sum_kg=float(rows[rows[:,3]==2,4].sum()),
                q_n_granted=False,production_granted=False,solver_launched=False)
    save(output/'native-initial-audit.json',result)
    if not (fixed_identical and body_identical and fluid_identical and center_ok and mass_ok):
        raise ValueError('Repaired-wall lineage or centered body/fluid physical contract differs')
    print(json.dumps(result),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--manifest',type=Path,required=True);p.add_argument('--output-root',type=Path,required=True);a=p.parse_args();run(a.manifest,a.output_root)
