"""Source-bound analytic motion regularity; no claimed cause of native errors."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

def digest(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binding', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    b = json.loads(args.binding.read_text())
    if args.output.exists():
        raise FileExistsError(args.output)
    for source in b['sources']:
        if digest(source['path']) != source['sha256']:
            raise ValueError('Bound source changed')
    cpp = Path(b['motion_implementation']).read_text()
    reader = Path(b['motion_xml_reader']).read_text()
    for needle in ['double ang=mv->Ampl*sin(ph)', 'ang=mv->Ampl*sin(ph)-ang', 'amov->PhaseUni=ph']:
        if needle not in cpp:
            raise ValueError('Prescribed incremental sinusoidal semantics differ')
    if 'bool phaseprev=(ele->FirstChildElement("phase")==NULL)' not in reader:
        raise ValueError('Explicit phase reset semantics differ')
    cases = []
    motion_bytes = None
    for source in b['definitions']:
        tree = ET.parse(source)
        motion = tree.find('./casedef/motion')
        if motion is None:
            raise ValueError('Required physical motion missing')
        semantic = ET.tostring(motion)
        if motion_bytes is None:
            motion_bytes = semantic
        elif motion_bytes != semantic:
            raise ValueError('Prescribed motion differs across original resolutions')
        obj = motion.find('objreal')
        begin = obj.find('begin')
        moves = {int(x.get('id')): x for x in obj if x.get('id') is not None}
        current = int(begin.get('mov'))
        time = float(begin.get('start'))
        finish = float(begin.get('finish'))
        angle = 0.0
        rows = []
        while time < finish:
            node = moves[current]
            duration = min(float(node.get('duration')), finish-time)
            before = angle
            if node.tag == 'wait':
                v0 = v1 = acc0 = acc1 = 0.0
            elif node.tag == 'mvrotsinu':
                if node.get('anglesunits') != 'degrees' or node.find('phase') is None:
                    raise ValueError('Only explicit degree phase sinusoidal source accepted')
                amp = float(node.find('ampl').get('v'))
                omega = 2*math.pi*float(node.find('freq').get('v'))
                phase = math.radians(float(node.find('phase').get('v')))
                end = phase+omega*duration
                angle += amp*(math.sin(end)-math.sin(phase))
                v0, v1 = amp*omega*math.cos(phase), amp*omega*math.cos(end)
                acc0, acc1 = -amp*omega**2*math.sin(phase), -amp*omega**2*math.sin(end)
            else:
                raise ValueError('Unexpected physical motion branch')
            rows.append({'movement_id':current, 'type':node.tag, 'start_s':time, 'end_s':time+duration,
                         'angle_start_deg':before, 'angle_end_deg':angle,
                         'velocity_start_right_deg_s':v0, 'velocity_end_left_deg_s':v1,
                         'acceleration_start_right_deg_s2':acc0, 'acceleration_end_left_deg_s2':acc1})
            time += duration
            current = int(node.get('next'))
        jumps = [{'time_s':right['start_s'], 'left_movement':left['movement_id'],
                  'right_movement':right['movement_id'],
                  'prescribed_velocity_jump_deg_s':right['velocity_start_right_deg_s']-left['velocity_end_left_deg_s'],
                  'prescribed_acceleration_jump_deg_s2':right['acceleration_start_right_deg_s2']-left['acceleration_end_left_deg_s2']}
                 for left,right in zip(rows,rows[1:])]
        cases.append({'definition':source,'sha256':digest(source),'segments':rows,'one_sided_transitions':jumps,
                      'initial_prescribed_velocity_right_deg_s':rows[0]['velocity_start_right_deg_s'],
                      'initial_velocity_left':'not inferred from definition; solver initial moving state remains separately audited'})
    result = {'schema':'ds02.f7.actual-source-prescribed-motion-regularity.v1','binding':b,'cases':cases,
              'interpretation':'Explicit phases reset each sinusoidal segment; waits hold accumulated current pose. Transition derivatives are analytic prescribed motion, not sampled native rigid-body diagnostics.',
              'rejected_owner_claim':'Sinusoidal segments with waits do not by themselves ensure zero transition velocity or acceleration.',
              'limitations':['No unique cause assigned to existing 43.011% spatial kinetic-energy discrepancy.',
                             'No source air-gap/kernel-radius rule grants native geometry truth or explains particle fate.',
                             'No retrospective smoothing of consumed driving files; prospective change requires new physical identity and full numerical qualification.'],
              'q_n':'not_granted','production_approval':'none'}
    with args.output.open('x') as stream:
        json.dump(result,stream,indent=2,allow_nan=False)
        stream.write('\n')
    print(json.dumps({'definitions':len(cases),'one_sided_transitions':len(cases[0]['one_sided_transitions']),
                      'q_n':'not_granted'}))

if __name__ == '__main__':
    main()
