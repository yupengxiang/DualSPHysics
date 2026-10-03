"""Export actual native exclusions without assigning a physical spill fate."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binding', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    b = json.loads(args.binding.read_text())
    receipt = json.loads(Path(b['native_receipt']).read_text())
    if receipt['status'] != 'completed' or receipt['returncode'] != 0:
        raise ValueError('Native source is not completed0')
    output = args.output_dir
    csv_path, resume = output / 'PartOut.csv', output / 'PartOut-resume.csv'
    if csv_path.exists():
        raise FileExistsError(csv_path)
    command = [b['binary'], '-dirdata', b['data_root'], '-savecsv', str(csv_path),
               '-saveresume', str(resume), '-createdirs:1', '-csvsep:1']
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (output / 'PartVTKOut.stdout.log').write_text(result.stdout)
    if result.returncode:
        raise ValueError('Official PartVTKOut failed')
    ids, motives, rows = set(), {}, 0
    with csv_path.open(newline='') as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            row = {k.strip(): v.strip() for k, v in raw.items()}
            if not any(row.values()):
                continue
            identity = int(row['Idp'])
            if identity in ids:
                raise ValueError('Duplicate native exclusion identity')
            ids.add(identity)
            motive = int(row['Motive'])
            for axis in 'xyz':
                if not math.isfinite(float(row[f'Pos.{axis} [m]'])):
                    raise ValueError('Nonfinite native exclusion position')
            part = int(row['PartOut'])
            if not 0 <= part < b['expected_frames']:
                raise ValueError('Exclusion part outside actual saved interval')
            motives[str(motive)] = motives.get(str(motive), 0) + 1
            rows += 1
    if rows != b['expected_native_exclusions']:
        raise ValueError('Official exclusions disagree with native terminal count')
    report = {'schema': 'ds02.f2.actual-native-dense-exclusion-export.v1',
              'binding': b, 'command': command, 'rows': rows,
              'unique_identities': len(ids), 'motive_counts': motives,
              'csv': str(csv_path), 'csv_sha256': hashlib.sha256(csv_path.read_bytes()).hexdigest(),
              'unknown_physical_fate_preserved': True,
              'q_n_status': 'not_granted', 'production_approval': 'none',
              'limitations': ['Native excluded identities remain unknown physical fates.',
                              'Subsequent label processing must join native Idp to the actual initial fluid cohort.']}
    (output / 'native-exclusion-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'rows': rows, 'motive_counts': motives, 'q_n_status': 'not_granted'}))


if __name__ == '__main__':
    main()
