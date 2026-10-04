import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import xml.etree.ElementTree as ET


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


p = argparse.ArgumentParser()
p.add_argument('--binding', required=True)
p.add_argument('--output-dir', required=True)
a = p.parse_args()
b = json.loads(Path(a.binding).read_text())
out = Path(a.output_dir)
out.mkdir(exist_ok=False)
module = Path(b['selected_module'])
assert sha(module) == b['selected_module_sha256']
spec = importlib.util.spec_from_file_location('selected_motion', module)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
controls = []
for dt, filename in [(.001, 'motion_obstacle_quintic.dat'),
                     (.0005, 'motion_obstacle_quintic_dt0005.dat')]:
    content = m.generate_motion_dat_content(45., 12., dt)
    dst = out / filename
    digest = m.write_motion_file_exclusive(dst, content)
    rows = [list(map(float, line.split())) for line in dst.read_text().splitlines()
            if line and not line.startswith('#')]
    assert len(rows) == round(12. / dt) + 1
    assert rows[0] == [0., 0.] and rows[-1] == [12., 0.]
    assert all(t == i * dt and angle == m.evaluate_trajectory_analytic(t, 45.)[0]
               for i, (t, angle) in enumerate(rows))
    actual_slopes = [(q[1] - r[1]) / (q[0] - r[0]) for r, q in zip(rows, rows[1:])]
    io = m.describe_sampled_motion_io(45., 12., dt)
    controls.append({'sampling_dt_s': dt, 'path': str(dst), 'sha256': digest,
                     'actual_roundtrip_rows': len(rows), 'target_descriptor': io,
                     'actual_nonuniform_float_time_first_slope_deg_s': actual_slopes[0],
                     'actual_max_abs_knot_slope_jump_deg_s': max(abs(x-y) for x,y in zip(actual_slopes,actual_slopes[1:])),
                     'native_interpolation': 'piecewise linear, finite knot slope jumps; not C2'})
definitions = []
for case in b['cases']:
    src = Path(case['reference_definition'])
    before = sha(src)
    assert before == case['reference_sha256']
    reference = ET.parse(src).getroot()
    axis = reference.find('./casedef/motion/objreal/mvrotsinu/axisp1')
    assert [float(axis.get(k)) for k in ['x','y','z']] == [-.04,0.,.05]
    dst = out / (case['case_id'] + '_Def.xml')
    text = m.generate_smooth_c2_definition_xml(src, controls[0]['path'].split('/')[-1])
    with dst.open('x') as f:
        f.write(text)
    result = m.verify_xml_declared_subtree_undo(src, dst)
    assert result['whole_tree_identical_upon_undo'] and result['declared_motion_subtree_isolated']
    assert sha(src) == before
    definitions.append({**case, 'definition': str(dst), 'definition_sha256': sha(dst),
                        'whole_xml_undo': result, 'source_unchanged': True})
assert sha(module) == b['selected_module_sha256']
with (out / 'motion-preparation.json').open('x') as f:
    json.dump({'schema':'ds02.f7.actual-quintic-target-source-preparation.v1',
               'controls':controls, 'definitions':definitions,
               'physical_mother_id':'F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_BASE_V1',
               'analytic_target':'C2; two finite symmetric cycles 0..8, neutral rest 8..12',
               'actual_solver_motion':'Sampled file interpreted piecewise linearly; cadence sensitivity pending native qualification',
               'old_43pct_KE_cause':'not established', 'q_n':'not_granted',
               'production_approval':'none', 'independent_case_count_increment':0},f,indent=2)
    f.write('\n')
