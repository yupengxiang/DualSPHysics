"""Prepare immutable CELL3 quarter-CFL inputs with verified physical equivalence."""
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


def prepare(config, output):
    cfg = json.loads(config.read_text())
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
                'CoefDtMin': .05, 'StepAlgorithm': 2.}
    if any(float(values[key]) != value for key, value in expected.items()):
        raise ValueError('Only the registered nominal CELL3 source is supported')
    constants = tree.find('./execution/constants')
    particles = tree.find('./execution/particles')
    if (constants.find('data2d').get('value') != 'false' or
            float(constants.find('dp').get('value')) != .0075 or
            int(particles.get('np')) != 108000 or
            int(particles.find('fluid').get('count')) != 34560):
        raise ValueError('Actual nominal 3D CELL3 source geometry required')
    cfl = tree.findall('.//cflnumber')
    coefficient = tree.findall("./execution/parameters/parameter[@key='CoefDtMin']")
    if len(cfl) != 2 or len(coefficient) != 1 or any(float(n.get('value')) != .05 for n in cfl):
        raise ValueError('Unexpected nominal CFL or minimum-step definition')
    physical_before = physical_projection(tree)
    for node in cfl + coefficient:
        node.set('value', '0.0125')
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
        'schema': 'ds02.f3.cell3-quarter-cfl-input.v1', 'case_id': cfg['case_id'],
        'physical_binding_sha256': cfg['physical_binding_sha256'],
        'source_sha256': {str(sources[key]): value for key, value in before.items()},
        'outputs': {key: {'path': str(path), 'sha256': digest(path)} for key, path in outputs.items()},
        'prepared_prefix': str(prefix), 'physical_projection_unchanged': True,
        'physical_projection_sha256': hashlib.sha256(physical_before.encode()).hexdigest(),
        'actual_generated_counts': {'total_particles': 108000, 'fluid_particles': 34560, 'solver_dimension': 3},
        'numerical_changes': {'casedef_and_generated_CFL': [.05, .0125], 'CoefDtMin': [.05, .0125]},
        'unchanged_time_controls': {'TimeMax': 8.35, 'TimeOut': .01, 'DtIni': 0, 'DtMin': 0, 'DtFixed': 0},
        'source_unchanged': True, 'q_n_status': 'not_assessed', 'production_approval': 'none',
        'claim': 'Actual CPU input preparation only; source BI4/control reused by exact digest, no solver claim.'}
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
