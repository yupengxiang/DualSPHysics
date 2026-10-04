import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET


def sha(p):
    h = hashlib.sha256()
    with Path(p).open('rb') as f:
        for block in iter(lambda: f.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


p = argparse.ArgumentParser()
p.add_argument('--binding', required=True)
p.add_argument('--output-dir', required=True)
a = p.parse_args()
b = json.loads(Path(a.binding).read_text())
out = Path(a.output_dir)
out.mkdir(exist_ok=False)
source = Path(b['definition'])
before = sha(source)
assert before == b['definition_sha256']
definition = out / (b['case_id'] + '_Def.xml')
shutil.copyfile(source, definition)
asset_reports = []
for asset in b.get('assets', []):
    src = Path(asset['source'])
    assert sha(src) == asset['sha256']
    dst = out / asset['relative_name']
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    assert sha(dst) == asset['sha256']
    asset_reports.append({**asset, 'copied_to': str(dst)})
prefix = out / b['case_id']
# Inherit stdout: the runner parses the original official GenCase output.
cmd = [b['gencase'], str(definition.with_suffix('')), str(prefix),
       '-save:all', '-threads:' + str(b['threads'])]
subprocess.run(cmd, cwd=out, check=True)
root = ET.parse(prefix.with_suffix('.xml')).getroot()
constants = {n.tag: dict(n.attrib) for n in root.find('./execution/constants')}
assert constants['data2d']['value'] == 'false'
assert float(constants['dp']['value']) == b['dp_m']
counts = {k: sum(int(n.get('count')) for n in root.findall('./execution/particles/' + k))
          for k in ['fixed', 'moving', 'floating', 'fluid']}
assert counts['fluid'] > 0 and counts['fixed'] > 0
if b.get('expected_fluid') is not None:
    assert counts['fluid'] == b['expected_fluid']
assert int(root.find('./execution/particles').get('np')) == sum(counts.values())
assert prefix.with_suffix('.bi4').stat().st_size > 0
assert sha(source) == before
report = {'schema': 'ds02.root.actual-native-source-preflight.v1',
          'case_id': b['case_id'], 'prefix': str(prefix), 'command': cmd,
          'source_definition': str(source), 'definition_sha256': before,
          'xml_sha256': sha(prefix.with_suffix('.xml')),
          'bi4_sha256': sha(prefix.with_suffix('.bi4')),
          'actual_generated_constants': constants, 'generated_xml_particle_counts': counts,
          'actual_total_particles': sum(counts.values()), 'assets': asset_reports,
          'predictions': b.get('predictions', {}),
          'native_initial_typed_QA': 'pending actual arrays',
          'mass_evidence': 'Generated XML text only; actual binary native weights pending typed QA',
          'q_n': 'not_granted', 'production_approval': 'none',
          'independent_case_count_increment': 0}
with (out / 'prepared-input-report.json').open('x') as f:
    json.dump(report, f, indent=2)
    f.write('\n')
