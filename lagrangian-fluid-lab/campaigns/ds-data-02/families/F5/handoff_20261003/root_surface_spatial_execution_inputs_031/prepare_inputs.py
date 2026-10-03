"""Stage native inputs with the already reviewed DP-specific numerical envelopes."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for b in iter(lambda:stream.read(1024**2), b''):
            h.update(b)
    return h.hexdigest()

def projection(node):
    return (node.tag, sorted(node.attrib.items()), (node.text or '').strip(), [projection(c) for c in node])

def strip_domain(root):
    parent = root.find('.//execution/parameters')
    parent.remove(parent.find('simulationdomain'))
    return projection(root)

def run(config, output):
    c = json.loads(config.read_text()); summaries=[]
    for case in c['cases']:
        for gate in case['gates']:
            r = json.loads(Path(gate['receipt']).read_text())
            q = json.loads(Path(gate['report']).read_text())
            assert r['status']=='completed' and r['returncode']==0 and q[gate['pass_key']] is True
        p = Path(case['prefix']); original = ET.parse(p.with_suffix('.xml')).getroot()
        domain = ET.parse(case['domain_source']).getroot().find('.//execution/parameters/simulationdomain')
        assert domain is not None
        lo = [float(domain.find('posmin').get(k)) for k in 'xyz']; hi = [float(domain.find('posmax').get(k)) for k in 'xyz']
        coverage = json.loads(Path(case['gates'][1]['report']).read_text())
        for bounds in coverage['native_marker_bounds_m'].values():
            assert all(lo[i] < bounds[0][i] <= bounds[1][i] < hi[i] for i in range(3))
        target = output/'prepared'/case['case_id']; target.parent.mkdir(parents=True, exist_ok=False)
        staged = copy.deepcopy(original); parent = staged.find('.//execution/parameters'); parent.remove(parent.find('simulationdomain')); parent.append(copy.deepcopy(domain))
        assert strip_domain(copy.deepcopy(original)) == strip_domain(copy.deepcopy(staged))
        ET.ElementTree(staged).write(target.with_suffix('.xml'), encoding='utf-8', xml_declaration=True)
        shutil.copyfile(p.with_suffix('.bi4'), target.with_suffix('.bi4'))
        assert digest(p.with_suffix('.bi4'))==digest(target.with_suffix('.bi4'))
        for path in case['auxiliary_files']:
            path=Path(path); rel=path.relative_to(Path(case['definition_root'])); destination=target.parent/rel; destination.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(path,destination); assert digest(path)==digest(destination)
        summaries.append({'case_id':case['case_id'], 'execution_prefix':str(target), 'source_prefix':str(p), 'domain_source':case['domain_source'], 'domain_source_sha256':digest(case['domain_source']), 'numerical_envelope_m':[lo,hi], 'same_BI4_bytes':True, 'same_XML_without_simulationdomain':True, 'same_motion_and_mesh_bytes':True, 'actual_initial_gates_passed':True, 'physical_geometry_control_mass_unchanged':True, 'q_n_granted':False})
    r={'schema':'ds02.f5.actual-spatial-execution-input-binding.v1','cases':summaries, 'q_n_status':'not_assessed'}
    (output/'execution-input-binding.json').write_text(json.dumps(r,indent=2)+'\n'); print(json.dumps(r),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);p.add_argument('--output-dir',type=Path,required=True);a=p.parse_args();run(a.config,a.output_dir)
