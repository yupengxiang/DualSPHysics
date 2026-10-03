"""Prepare immutable CELL3 adaptive floor-safe inputs with verified physical equivalence."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def physical_projection(tree):
    tree = copy.deepcopy(tree)
    for node in tree.findall('.//cflnumber'):
        node.set('value', 'NUMERICAL_CFL')
    for node in tree.findall('./execution/parameters/parameter'):
        if node.get('key') == 'CoefDtMin':
            node.set('value', 'NUMERICAL_DT_FLOOR_COEFFICIENT')
    return ET.canonicalize(ET.tostring(tree, encoding='unicode'))


def prepare(config_path, output):
    cfg = json.loads(config_path.read_text())
    sources = {key: Path(value['path']) for key, value in cfg['sources'].items()}
    before = {key: digest(path) for key, path in sources.items()}
    for key, value in cfg['sources'].items():
        if before[key] != value['sha256']:
            raise ValueError('Source differs from frozen binding: ' + key)
    if output.exists():
        raise FileExistsError(output)

    tree = ET.fromstring(sources['xml'].read_bytes())
    values = {n.get('key'): n.get('value') for n in tree.findall('./execution/parameters/parameter')}
    expected = {'TimeMax': 8.35, 'TimeOut': .01, 'DtIni': 0., 'DtMin': 0., 'DtFixed': 0.,
                'StepAlgorithm': 2.}
    for key, val in expected.items():
        if float(values[key]) != val:
            raise ValueError(f'Parameter {key}={values[key]} differs from expected nominal {val}')

    constants = tree.find('./execution/constants')
    particles = tree.find('./execution/particles')
    if (constants.find('data2d').get('value') != 'false' or
            float(constants.find('dp').get('value')) != .0075 or
            int(particles.get('np')) != 108000 or
            int(particles.find('fluid').get('count')) != 34560):
        raise ValueError('Actual nominal 3D CELL3 source geometry required')

    cfl = tree.findall('.//cflnumber')
    coefficient = tree.findall("./execution/parameters/parameter[@key='CoefDtMin']")
    if len(cfl) != 2 or len(coefficient) != 1:
        raise ValueError('Unexpected nominal CFL or minimum-step definition structure')

    target_cfl = str(cfg['target_cfl'])
    target_coef_dt_min = str(cfg['target_coef_dt_min'])

    old_cfl = float(cfl[0].get('value'))
    old_coef = float(coefficient[0].get('value'))
    physical_before = physical_projection(tree)
    for node in cfl:
        node.set('value', target_cfl)
    for node in coefficient:
        node.set('value', target_coef_dt_min)

    if physical_projection(tree) != physical_before:
        raise ValueError('A physical or unrelated numerical parameter changed')

    output.mkdir(parents=True)
    prefix = output / cfg['case_id']
    xml = prefix.with_suffix('.xml')
    ET.ElementTree(tree).write(xml, encoding='utf-8', xml_declaration=True)
    outputs = {'xml': xml}
    for key in ('bi4', 'control', 'vtk'):
        destination = prefix.with_suffix('.bi4') if key == 'bi4' else output / sources[key].name
        shutil.copyfile(sources[key], destination)
        if digest(destination) != before[key]:
            raise ValueError('Copied native input differs: ' + key)
        outputs[key] = destination

    if physical_projection(ET.parse(xml).getroot()) != physical_before:
        raise ValueError('Serialized XML changed physical projection')
    if before != {key: digest(path) for key, path in sources.items()}:
        raise ValueError('Original inputs changed during preparation')

    report = {
        'schema': 'ds02.f3.cell3-adaptive-floor-repair-input.v1',
        'case_id': cfg['case_id'],
        'physical_binding_sha256': cfg['physical_binding_sha256'],
        'source_sha256': {str(sources[key]): value for key, value in before.items()},
        'outputs': {key: {'path': str(path), 'sha256': digest(path)} for key, path in outputs.items()},
        'prepared_prefix': str(prefix),
        'physical_projection_unchanged': True,
        'physical_projection_sha256': hashlib.sha256(physical_before.encode()).hexdigest(),
        'actual_generated_counts': {'total_particles': 108000, 'fluid_particles': 34560, 'solver_dimension': 3},
        'numerical_changes': {
            'casedef_and_generated_CFL': [old_cfl, float(target_cfl)],
            'CoefDtMin': [old_coef, float(target_coef_dt_min)],
            'ratio_floor_to_cfl': float(target_coef_dt_min) / float(target_cfl),
        },
        'unchanged_time_controls': {'TimeMax': 8.35, 'TimeOut': .01, 'DtIni': 0, 'DtMin': 0, 'DtFixed': 0},
        'source_unchanged': True,
        'q_n_status': 'not_assessed',
        'production_approval': 'none',
        'claim': 'CPU input preparation only; source BI4/control reused by exact digest, no solver claim.',
    }
    for path in outputs.values():
        path.chmod(0o444)
    report_path = output / 'prepared-input-report.json'
    report_path.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'report': str(report_path), 'physical_projection_unchanged': True}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    prepare(args.config, args.output)
