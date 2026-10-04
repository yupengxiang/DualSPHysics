"""Clone each completed lower-head reference with independent half CFL/floor."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET


def digest(p):
    h = hashlib.sha256()
    with Path(p).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binding', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    assert not args.output_dir.exists()
    b = json.loads(args.binding.read_text())
    results = []
    for item in b['cases']:
        parent = json.loads(Path(item['source_native_receipt']).read_text())
        assert parent['status'] == 'completed' and parent['returncode'] == 0
        prefix = Path(item['source_prefix'])
        src_xml, src_bi4 = prefix.with_suffix('.xml'), prefix.with_suffix('.bi4')
        xsha, bsha = digest(src_xml), digest(src_bi4)
        assert bsha == item['native_initial_bi4_sha256']
        root = ET.parse(src_xml).getroot()
        original = ET.tostring(root)
        cfl = root.find('./execution/constants/cflnumber')
        coef = root.find("./execution/parameters/parameter[@key='CoefDtMin']")
        assert float(cfl.get('value')) == .2 and float(coef.get('value')) == .05
        cfl_original, coef_original = cfl.get('value'), coef.get('value')
        for key in ('DtIni', 'DtMin', 'DtFixed'):
            assert float(root.find("./execution/parameters/parameter[@key='%s']" % key).get('value')) == 0
        cfl.set('value', '0.1')
        coef.set('value', '0.025')
        target = args.output_dir / item['role'] / item['target_case_id']
        target.parent.mkdir(parents=True)
        ET.ElementTree(root).write(target.with_suffix('.xml'), encoding='utf-8', xml_declaration=True)
        shutil.copyfile(src_bi4, target.with_suffix('.bi4'))
        assert digest(target.with_suffix('.bi4')) == bsha
        reconstructed = ET.parse(target.with_suffix('.xml')).getroot()
        reconstructed.find('./execution/constants/cflnumber').set('value', cfl_original)
        reconstructed.find("./execution/parameters/parameter[@key='CoefDtMin']").set('value', coef_original)
        assert ET.tostring(reconstructed) == original, 'Unrequested physical/numerical change'
        assert digest(src_xml) == xsha and digest(src_bi4) == bsha
        results.append({**item, 'prepared_prefix': str(target),
                        'source_xml_sha256': xsha, 'initial_bi4_sha256': bsha,
                        'prepared_xml_sha256': digest(target.with_suffix('.xml')),
                        'initial_bi4_byte_identical': True, 'reverse_xml_tree_identical': True,
                        'only_changes': {'CFLnumber': [.2, .1], 'CoefDtMin': [.05, .025]}})
    report = {'schema': 'ds02.f1.lower-head-exact-independent-halfstep-clones.v1',
              'cases': results, 'independent_physical_case_increment': 0,
              'q_n': 'not_granted', 'production_approval': 'none'}
    (args.output_dir / 'clone-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'completed_exact_initial_clones': len(results)}))


if __name__ == '__main__':
    main()
