"""Export recovered native artifacts without asserting an unknown solver OS exit."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def snapshot(root):
    return {str(p.relative_to(root)): [p.stat().st_size, p.stat().st_mtime_ns]
            for p in sorted(root.rglob('*')) if p.is_file()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binding', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    b = json.loads(args.binding.read_text())
    audit_path = Path(b['artifact_audit'])
    audit = json.loads(audit_path.read_text())
    audit_receipt = json.loads(Path(b['artifact_audit_receipt']).read_text())
    assert audit_receipt['status'] == 'completed' and audit_receipt['returncode'] == 0
    assert audit_receipt['input_hashes_at_launch'] == audit_receipt['input_hashes_after_run']
    assert audit['original_launcher_OS_returncode'] == 'unknown; original receipt remains unchanged'
    assert audit['native_solver_self_reported_returncode'] == 0
    assert audit['input_hashes_current_match_launch'] is True
    original_path = Path(audit['original_receipt'])
    assert sha(original_path) == audit['original_receipt_sha256']
    original = json.loads(original_path.read_text())
    for path, digest in original['input_hashes_at_launch'].items():
        assert sha(path) == digest, 'Recovered input changed: ' + path
    assert sha(b['solver_log']) == audit['run_out_sha256']
    raw = Path(b['raw_root'])
    before = snapshot(raw)
    assert len(list(raw.glob('Part_*.bi4'))) == audit['native_frames'] == 241
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report = args.output_dir / 'recovered-export-provenance.json'
    assert not report.exists()
    command = [x.replace('{output_dir}', str(args.output_dir)) for x in b['command']]
    result = subprocess.run(command, check=False)
    assert result.returncode == 0, 'Official export failed'
    assert before == snapshot(raw), 'Native source tree changed during export'
    assert sha(original_path) == audit['original_receipt_sha256']
    outputs = list((args.output_dir / b['expected_directory']).glob(b['expected_pattern']))
    assert len(outputs) == b['expected_files'] and all(p.stat().st_size > 0 for p in outputs)
    report.write_text(json.dumps({
        'schema': 'ds02.root.recovered-native-official-export.v1',
        'original_receipt': str(original_path),
        'original_receipt_sha256': audit['original_receipt_sha256'],
        'original_launcher_OS_returncode': None,
        'native_solver_self_reported_returncode': 0,
        'artifact_audit': str(audit_path), 'artifact_audit_sha256': sha(audit_path),
        'official_export_command': command, 'official_export_returncode': result.returncode,
        'native_source_size_mtime_unchanged': True,
        'export_files': {str(p): sha(p) for p in outputs},
        'claim_boundary': 'Official recovered-artifact export only. Original OS exit unknown; complete state/time and rigid-pose numeric QA follow independently.',
        'q_n': 'not_granted', 'production_approval': 'none',
    }, indent=2) + '\n')


if __name__ == '__main__':
    main()
