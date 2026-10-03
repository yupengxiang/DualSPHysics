import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def semantic(node):
    return (node.tag, sorted((k, v) for k, v in node.attrib.items() if not k.endswith('comment')),
            (node.text or '').strip(), [semantic(c) for c in node])


def main():
    p = argparse.ArgumentParser();p.add_argument('--binding', required=True);p.add_argument('--output-dir', required=True)
    args = p.parse_args();b = json.loads(Path(args.binding).read_text());out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True);candidate = ET.parse(b['definition']).getroot()
    fine = ET.parse(b['fine_definition']).getroot();anchor = ET.parse(b['fine_generated_xml']).getroot()
    for tree in [candidate, fine]:
        parameters = {c.get('key'): c.get('value') for c in tree.findall('.//execution/parameters/parameter')}
        anchored = {c.get('key'): c.get('value') for c in anchor.findall('.//execution/parameters/parameter')}
        if parameters != anchored:
            raise ValueError('Candidate solver parameters differ from actual fine adaptive anchor')
        if semantic(tree.find('./execution/special')) != semantic(anchor.find('./execution/special')):
            raise ValueError('Whole-field physical forcing differs from anchor')
        if float(tree.find('./casedef/constantsdef/cflnumber').get('value')) != .05:
            raise ValueError('Actual baseline CFL must be preserved')
    geom = candidate.find('./casedef/geometry/definition');dp = float(geom.get('dp'))
    if dp != b['dp_m'] or any(float(geom.find('pointref').get(axis)) != dp/2 for axis in 'xyz'):
        raise ValueError('Commensurate cell-centre grid differs')
    # Source statements about masses/cohorts remain predictions until GenCase finishes.
    prefix = out / b['case_id']
    command = [b['gen_binary'], str(Path(b['definition']).with_suffix('')), str(prefix), '-save:all']
    result = subprocess.run(command, check=False)
    if result.returncode:
        raise RuntimeError('Official GenCase failed')
    shutil.copyfile(b['forcing'], out / 'CaseSloshingAccData.csv')
    if sha(out / 'CaseSloshingAccData.csv') != sha(b['forcing']):
        raise ValueError('Actual forcing copy differs')
    xml = prefix.with_suffix('.xml');bi = prefix.with_suffix('.bi4')
    generated = ET.parse(xml).getroot();constants = generated.find('./execution/constants')
    values = {c.tag: dict(c.attrib) for c in constants}
    if values['data2d']['value'] != 'false' or float(values['dp']['value']) != dp or float(values['cflnumber']['value']) != .05:
        raise ValueError('Generated adaptive 3D constants differ')
    counts = {'fluid': 0, 'fixed': 0, 'moving': 0, 'floating': 0}
    for c in generated.findall('./execution/particles/*'):
        if c.tag in counts:
            counts[c.tag] += int(c.get('count', '0'))
    report = {'schema': 'ds02.f3.actual-adaptive-spatial-gencase-input.v1',
              'case_id': b['case_id'], 'role': b['role'], 'prefix': str(prefix),
              'xml_sha256': sha(xml), 'bi4_sha256': sha(bi),
              'forcing_sha256': sha(out / 'CaseSloshingAccData.csv'),
              'generated_constants': values, 'generated_xml_particle_counts': counts,
              'expected_fluid_particles': b['expected_fluid'], 'expected_total_particles': b['expected_total'],
              'native_typed_identity_audit': 'pending; XML counts are not a native array audit',
              'EOS_status': 'actual automatic GenCase B/h retained; cross-DP EOS dependence reported, no override',
              'q_n': 'not_granted', 'production_approval': 'none'}
    (out / 'prepared-input-report.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
