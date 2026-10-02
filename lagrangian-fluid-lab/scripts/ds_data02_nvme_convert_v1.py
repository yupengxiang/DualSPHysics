"""Stage the unchanged direct converter on NVMe and publish verified H5 bytes.

Raw sources, typed conversion, EOS, full native timeline, source manifests,
lifecycle checks and official PartVTK comparisons remain unchanged. Only
fully loaded decoder scratch is reclaimed between frames, and the output
storage location changes before one checksum-verified publication.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import tempfile
import time

import ds_data02_direct_convert as converter
from ds_data02_f3_nvme_input_audit_v1 import verified_copy


def run(args, staging_root, staging_limit_bytes):
    output, report_path = args.output.absolute(), args.report.absolute()
    partial = output.with_suffix(output.suffix + '.partial')
    if any(path.exists() for path in (output, partial, report_path)):
        raise FileExistsError('Existing published conversion or partial output')
    staging_root.mkdir(parents=True, exist_ok=True)
    reserve = 100 * 1024**3
    free = lambda: shutil.disk_usage(staging_root).free
    if staging_limit_bytes <= 0 or free() < staging_limit_bytes + reserve:
        raise ValueError('NVMe stage requires registered peak plus 100 GiB free')
    started = time.monotonic()
    original_decode = converter.decode_frame
    with tempfile.TemporaryDirectory(prefix='ds02-convert-stage-', dir=staging_root) as owned:
        staged_h5 = Path(owned) / 'trajectory.h5'
        staged_report = Path(owned) / 'conversion-report.json'
        def decode_and_reclaim(frame_path, decoder, scratch, index):
            try:
                frame = original_decode(frame_path, decoder, scratch, index)
                # decode_frame uses fromfile and copies, never memory maps.
                if free() < reserve:
                    raise ValueError('NVMe free-space floor reached')
                candidate = staged_h5.with_suffix('.h5.partial')
                if candidate.exists() and candidate.stat().st_size > staging_limit_bytes:
                    raise ValueError('Registered NVMe output peak exceeded')
                if index % 100 == 0:
                    print(json.dumps({'stage': 'decoded-native-frame', 'frame': index,
                        'native_time_s': frame.time}), flush=True)
                return frame
            finally:
                # These are exactly the one decoder call's owned derived files.
                prefix = scratch / f'frame_{index:04d}'
                shutil.rmtree(prefix, ignore_errors=True)
                prefix.with_suffix('.xml').unlink(missing_ok=True)
        converter.decode_frame = decode_and_reclaim
        try:
            converter.convert_direct(data_root=args.data_root, generated_xml=args.generated_xml,
                output=staged_h5, report_path=staged_report, decoder=args.decoder,
                partvtk=args.partvtk, validation_dir=args.validation_dir,
                solver_log=args.solver_log, solver_receipt=args.solver_receipt,
                gencase_receipt=args.gencase_receipt, owner_metadata=args.owner_metadata,
                reference_hdf5=args.compare_hdf5, run_partvtk=not args.skip_partvtk_validation,
                keep_validation_csv=args.keep_validation_csv, particle_chunk=args.particle_chunk)
        finally:
            converter.decode_frame = original_decode
        report = json.loads(staged_report.read_text())
        if staged_h5.stat().st_size > staging_limit_bytes:
            raise ValueError('Registered NVMe final output peak exceeded')
        output.parent.mkdir(parents=True, exist_ok=True)
        try:
            actual = verified_copy(staged_h5, partial, report['output_sha256'])
            os.replace(partial, output)
        finally:
            partial.unlink(missing_ok=True)
        report['output_hdf5'] = str(output)
    report['storage_protocol'] = {
        'reader': 'unchanged ds_data02_direct_convert.convert_direct',
        'decoder_scratch': 'reclaim only the completed decode call after all arrays are in RAM',
        'verified_published_output_sha256': actual,
        'private_staging_removed': True, 'staging_peak_limit_bytes': staging_limit_bytes,
        'total_wrapper_wall_seconds': time.monotonic() - started,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open('x') as writer:
        writer.write(json.dumps(report, indent=2, sort_keys=True) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--staging-root', type=Path, required=True)
    parser.add_argument('--staging-limit-bytes', type=int, required=True)
    parser.add_argument('converter_args', nargs=argparse.REMAINDER)
    opts = parser.parse_args()
    argv = opts.converter_args
    if argv and argv[0] == '--':
        argv = argv[1:]
    args = converter._build_parser().parse_args(argv)
    def stop_owned(*_):
        raise SystemExit(143)
    signal.signal(signal.SIGTERM, stop_owned)
    result = run(args, opts.staging_root, opts.staging_limit_bytes)
    print(json.dumps({'frames': result['frames'], 'particles': result['particles'],
        'partvtk_all_passed': result['partvtk_validation']['all_passed'],
        'output_sha256': result['output_sha256']}), flush=True)
