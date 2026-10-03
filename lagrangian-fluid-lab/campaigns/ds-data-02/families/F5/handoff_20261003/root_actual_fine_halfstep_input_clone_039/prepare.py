"""Create exact initial-state clones with only two execution timestep changes."""
import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binding', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    b = json.loads(args.binding.read_text())
    spec = importlib.util.spec_from_file_location('selected_halfstep_transformer', b['transformer'])
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    results = []
    for case in b['cases']:
        source = Path(case['source_xml'])
        destination = args.output_dir / case['mechanism']
        destination.mkdir(parents=True, exist_ok=False)
        original = source.read_bytes()
        transformed, mutation = m.transform_execution_xml_bytes(original)
        before, after = ET.fromstring(original), ET.fromstring(transformed)
        # Independently undo the two intended semantic changes and require
        # complete tree equivalence, including physical geometry and controls.
        cfl = after.find('./execution/constants/cflnumber')
        coef = after.find('./execution/parameters/parameter[@key="CoefDtMin"]')
        if cfl.get('value') != '0.1' or coef.get('value') != '0.025':
            raise ValueError('Wrong actual halfstep execution constants')
        cfl.set('value', '0.2')
        coef.set('value', '0.05')
        if ET.tostring(before) != ET.tostring(after):
            raise ValueError('Additional unapproved XML semantic change')
        target = destination / source.name
        target.write_bytes(transformed)
        copied = []
        for child in source.parent.iterdir():
            if child.name in [source.name, 'execution-input-binding.json']:
                continue
            if child.is_dir():
                shutil.copytree(child, destination / child.name)
                files = [p for p in child.rglob('*') if p.is_file()]
            elif child.is_file():
                shutil.copyfile(child, destination / child.name)
                files = [child]
            else:
                raise ValueError('Unexpected input entry')
            for path in files:
                copy = destination / path.relative_to(source.parent)
                expected = m.compute_sha256(path)
                if m.compute_sha256(copy) != expected:
                    raise ValueError('Initial/control/geometry clone differs')
                copied.append({'source': str(path), 'copy': str(copy), 'sha256': expected})
        initial = source.with_suffix('.bi4')
        if m.compute_sha256(initial) != case['initial_bi4_sha256']:
            raise ValueError('Original initial state differs from actual GenCase evidence')
        receipt = json.loads(Path(case['gencase_receipt']).read_text())
        if (receipt['status'] != 'completed' or receipt['returncode'] != 0
                or receipt['solver_dimension_from_gencase'] != 3):
            raise ValueError('No original actual 3D GenCase evidence')
        results.append({'mechanism': case['mechanism'], 'case_id': case['case_id'],
                        'prefix': str(target.with_suffix('')), 'mutation': mutation,
                        'source_actual_gencase_receipt': case['gencase_receipt'],
                        'initial_bi4_sha256': case['initial_bi4_sha256'],
                        'total_particles': receipt['total_particles'],
                        'fluid_particles': receipt['fluid_particles'],
                        'copied_files': copied, 'new_gencase_generation': False,
                        'native_identity_evidence': 'Exact original generated BI4 bytes retained; historical typed initial proof remains applicable.'})
    (args.output_dir / 'clone-report.json').write_text(json.dumps({
        'schema': 'ds02.f5.actual-halfstep-execution-clone.v1', 'cases': results,
        'q_n': 'not_granted', 'production_approval': 'none'}, indent=2) + '\n')
    print(json.dumps({'actual_execution_clones': len(results), 'new_gencase_generation': False}))


if __name__ == '__main__':
    main()
