"""Root combines immutable native finite-face and domain-only stage evidence."""
import copy
import hashlib
import json
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
LAB = HERE.parents[6]
ROOT = LAB.parent
SOURCE = HERE.parent / 'dp020_dp0125_cpu_003/root_domain_dispatch_001'
FACES = HERE.parent / 'dp0125_finite_face_reference_001/finite_face_audit_001.json'
GUARD = LAB / 'scripts/ds_data02_strict_dispatch_v1.py'

def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(4*1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()

def dump(path, value):
    if path.exists():
        raise FileExistsError(path)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False)+'\n')

def canonical_without_domain(path):
    root = ET.parse(path).getroot()
    parameters = root.find('execution/parameters')
    parameters.remove(parameters.find('simulationdomain'))
    for element in root.iter():
        element.text = (element.text or '').strip() or None
        element.tail = None
    return ET.canonicalize(ET.tostring(root, encoding='unicode'))

def main():
    faces = json.loads(FACES.read_text())
    assert faces['all_cases_finite_faces_pass']
    assert all(c['audit_pass'] and c['actual_3d'] for c in faces['cases'])
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    entries = []
    for source in sorted(SOURCE.glob('*DP0125_request.json')):
        old = json.loads(source.read_text())
        proof_path = Path(old['root_prelaunch_domain_proof'])
        proof = json.loads(proof_path.read_text())
        xml_path = Path(proof['new_generated_xml'])
        root = ET.parse(xml_path).getroot()
        assert canonical_without_domain(proof['source_generated_xml']) == canonical_without_domain(xml_path)
        assert digest(proof['native_bi4']) == proof['native_bi4_sha256']
        assert digest(Path(proof['source_generated_xml']).with_suffix('.bi4')) == proof['native_bi4_sha256']
        constants = root.find('execution/constants')
        assert constants.find('data2d').get('value') == 'false'
        assert float(constants.find('dp').get('value')) == .0125
        fluid_count = sum(int(x.get('count')) for x in root.findall('execution/particles/fluid'))
        assert fluid_count == 2621440
        assert fluid_count * float(constants.find('massfluid').get('value')) == 5120
        body = root.find('execution/particles/floating')
        assert float(body.find('massbody').get('value')) == 128
        assert [float(body.find('center').get(k)) for k in 'xyz'] == [2.4,1.2,1.08]
        for k, target in zip('xyz',[8.53333333333,8.53333333333,13.6533333333]):
            assert abs(float(body.find('inertia').get(k))-target) < 5e-5
        domain = root.find('execution/parameters/simulationdomain')
        assert [float(domain.find('posmin').get(k)) for k in 'xyz'] == [-.25,-.15,-.15]
        assert [float(domain.find('posmax').get(k)) for k in 'xyz'] == [5.1,2.55,3.05]
        assert all(v>0 for a in proof['margins_after_kernel_padding'].values() for v in a)
        face = next(x for x in faces['cases'] if x['case_id']==old['case_id'])
        assert face['finite_face_audit']['all_five_finite_faces_covered']
        record = dict(schema='ds02.f6.root-finite-face-domain-review.v1',
            case_id=old['case_id'], parent_request=str(source), parent_request_sha256=digest(source),
            domain_proof=str(proof_path), domain_proof_sha256=digest(proof_path),
            finite_face_audit=str(FACES), finite_face_audit_sha256=digest(FACES),
            generated_xml_except_domain_canonical_equal=True, original_bi4_byte_identical=True,
            initial_and_prescribed_motion_kernel_padding_positive=True,
            free_body_trajectory_support='requires actual post-solver pose and bounds',
            fluid_mass_kg=5120, body_mass_kg=128,
            center_m=[2.4,1.2,1.08], inertia_native_tolerance_kg_m2=5e-5,
            fixed_five_finite_faces=face['finite_face_audit'],
            q_n_status='not_assessed', production_approval='none')
        review_path=HERE/(old['mechanism_id']+'_root_preflight.json')
        dump(review_path, record)
        request=copy.deepcopy(old)
        request['attempt_id']=old['case_id']+'_SOLVER_QUAL_FINE_ROOT_FACE_DOMAIN_002'
        request['worktree_root']=str(ROOT)
        request['cwd']=str(LAB)
        request['root_registration_commit']=commit
        request['request_registration_commit']=commit
        request['finite_face_audit']=str(FACES)
        request['finite_face_audit_sha256']=digest(FACES)
        request['simulationdomain_gate']={'status':'root_reviewed_initial_and_prescribed_sweep',
            'root_proof':str(proof_path),'free_body_full_pose_gate':'pending actual solver'}
        request['root_combined_preflight']=str(review_path)
        request['expected_native_frames']=241
        request['qualification_claim']='none_until_full_native_postprocessing_and_frozen_QN'
        request['old_request_consumed']=False
        hashes=request.setdefault('input_sha256',{})
        for p in [FACES, GUARD, Path(__file__).resolve(), review_path, source, proof_path]:
            key=str(p.resolve())
            if key not in request['input_files']:
                request['input_files'].append(key)
            hashes[key]=digest(p)
        destination=HERE/(old['mechanism_id']+'_solver_request.json')
        dump(destination, request)
        entries.append({'request':str(destination),'request_sha256':digest(destination),
            'case_id':old['case_id'], 'max_wall_seconds':request['max_wall_seconds'],
            'estimated_storage_bytes':request['estimated_storage_bytes']})
    assert len(entries)==2
    dump(HERE/'request_manifest.json',dict(schema='ds02.f6.root-pair-dispatch.v1',
        created_at_utc=datetime.now(timezone.utc).isoformat(),requests=entries,
        gpu_launch_authority='root via unchanged shared runtime and strict guard',
        q_n_status='not_assessed',production_approval='none'))
    print(json.dumps(entries))

if __name__=='__main__':
    main()
