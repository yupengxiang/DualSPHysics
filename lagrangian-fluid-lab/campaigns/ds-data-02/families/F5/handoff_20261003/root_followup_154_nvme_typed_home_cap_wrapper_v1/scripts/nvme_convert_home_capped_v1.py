#!/usr/bin/env python3
"""NVMe-only typed conversion with a hard, conservative Home publish cap.

The integration direct converter, decoder, EOS, full-time lifecycle checks,
PartVTK three-frame validation, and payload hash semantics remain unchanged.
This successor only owns the transient storage protocol: decoder scratch, the
temporary H5, and PartVTK CSV validation are forced below one private NVMe
staging directory.  A final JSON preview is stat'ed on NVMe, then the live
Home floor and all *other* ledger reservations are checked while holding the
shared ledger lock.  Only a passing guard may create Home ``.partial`` files.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import shutil
import signal
import sys
import tempfile
import time

# The integration worktree is an immutable producer input.  The package must
# import from its scripts directory; the parent LAB_ROOT is not importable.
LAB_ROOT = Path(
    '/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab'
)
INTEGRATION_SCRIPT_ROOT = LAB_ROOT / 'scripts'
if str(INTEGRATION_SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(INTEGRATION_SCRIPT_ROOT))

import ds_data02_direct_convert as converter  # noqa: E402
from ds_data02_f3_nvme_input_audit_v1 import verified_copy  # noqa: E402
from home_publish_math import (  # noqa: E402
    evaluate_publish,
    other_reserved_storage_bytes,
    serialized_json_bytes,
)

DEFAULT_HOME_ROOT = Path('/home/jade')
DEFAULT_LEDGER = Path(
    '/home/jade/Projects/DualSPHysics-data/ds-data-02/runtime/resource-ledger.json'
)
DEFAULT_LOCK = Path(
    '/home/jade/Projects/DualSPHysics-data/ds-data-02/runtime/resource-ledger.lock'
)
DEFAULT_HOME_FLOOR = 500 * 1024**3
DEFAULT_HOME_HEADROOM = 2 * 1024**3
DEFAULT_PUBLISH_CAP = 4 * 1024**3
DEFAULT_STAGING_LIMIT = 24 * 1024**3
DEFAULT_NVME_RESERVE = 100 * 1024**3


class HomePublishRefusal(RuntimeError):
    """Raised before or during a guarded publication failure."""


def _load_ledger(path: Path) -> dict:
    value = json.loads(path.read_text())
    limits = value.get('limits') if isinstance(value, dict) else None
    if (
        not isinstance(value, dict)
        or not isinstance(value.get('reservations'), list)
        or not isinstance(limits, dict)
        or not isinstance(limits.get('home_min_free_bytes'), (int, float))
    ):
        raise HomePublishRefusal(f'invalid shared resource ledger: {path}')
    if int(limits['home_min_free_bytes']) < DEFAULT_HOME_FLOOR:
        raise HomePublishRefusal('shared ledger Home floor is below the reviewed 500 GiB floor')
    for row in value['reservations']:
        if not isinstance(row, dict):
            raise HomePublishRefusal('shared ledger contains a non-object reservation')
        try:
            storage = int(row.get('new_storage_bytes', 0))
        except (TypeError, ValueError) as exc:
            raise HomePublishRefusal('shared ledger reservation size is not numeric') from exc
        if storage < 0:
            raise HomePublishRefusal('shared ledger reservation size is negative')
    return value


def _home_free(path: Path) -> int:
    stat = os.statvfs(path)
    return stat.f_bavail * stat.f_frsize


def _same_device(a: Path, b: Path) -> bool:
    return a.stat().st_dev == b.stat().st_dev


def _ledger_exclusive(path: Path):
    """Open the actual shared lock inode; the JSON ledger stays read-only."""
    if not path.is_file():
        raise HomePublishRefusal(f'shared ledger lock is missing: {path}')
    return path.open('r')


def _stage_bytes(root: Path) -> int:
    """Stat only private staging files; never open a science input."""
    total = 0
    for path in root.rglob('*'):
        if path.is_file():
            total += path.stat().st_size
    return total


def _check_stage_budget(*, stage: Path, staging_root: Path,
                        staging_limit_bytes: int,
                        nvme_free_reserve_bytes: int,
                        reason: str) -> tuple[int, int]:
    used = _stage_bytes(stage)
    free = shutil.disk_usage(staging_root).free
    if used > staging_limit_bytes:
        raise HomePublishRefusal(
            f'private NVMe staging peak exceeded during {reason}: '
            f'{used} > {staging_limit_bytes} bytes'
        )
    if free < nvme_free_reserve_bytes:
        raise HomePublishRefusal(
            f'private NVMe free-space floor reached during {reason}: '
            f'{free} < {nvme_free_reserve_bytes} bytes'
        )
    return used, free


def _write_private_report_preview(path: Path, report: dict) -> int:
    """Serialize the final report on NVMe and return its measured byte size."""
    payload = (json.dumps(report, indent=2, sort_keys=True) + '\n').encode('utf-8')
    with path.open('wb') as writer:
        writer.write(payload)
        writer.flush()
        os.fsync(writer.fileno())
    measured = path.stat().st_size
    if measured != len(payload):
        raise HomePublishRefusal('private final-report preview changed while being written')
    return measured


def _prepare_report(*, staged_report: Path, output: Path, staged_h5: Path,
                    private_validation: Path, cap_bytes: int,
                    configured_home_floor_bytes: int,
                    effective_home_floor_bytes: int,
                    home_headroom_bytes: int,
                    other_reserved_bytes: int, home_free_bytes: int,
                    current_attempt_id: str,
                    current_reservation_storage_bytes: int,
                    staging_limit_bytes: int,
                    nvme_free_reserve_bytes: int,
                    staging_root: Path,
                    started: float) -> tuple[dict, int, dict]:
    if private_validation.parent != staged_h5.parent:
        raise HomePublishRefusal('PartVTK validation is outside private NVMe staging')
    report = json.loads(staged_report.read_text())
    report['output_hdf5'] = str(output)
    expected = report.get('output_sha256')
    if not isinstance(expected, str) or len(expected) != 64:
        raise HomePublishRefusal(
            'direct converter did not provide a 64-character output attestation'
        )
    h5_bytes = staged_h5.stat().st_size
    protocol = {
        'reader': 'unchanged ds_data02_direct_convert.convert_direct',
        'decoder_scratch': 'private NVMe staging only; reclaimed after each decode',
        'per_frame_decoder_reclaim_check': True,
        'private_partvtk_validation': True,
        'private_partvtk_csv_peak_checked': True,
        'private_final_report_preview_peak_checked': True,
        'private_staging_removed': True,
        'staging_peak_limit_bytes': staging_limit_bytes,
        'staging_free_reserve_bytes': nvme_free_reserve_bytes,
        'verified_published_output_sha256': expected,
        'verified_hash_semantics': (
            'unchanged verified_copy result; producer payload hash is not '
            'recomputed by source preparation'
        ),
        'home_publish_guard_schema': 'ds02.nvme.home-publish-cap.v1',
        'home_publish_cap_bytes': cap_bytes,
        'home_floor_bytes': effective_home_floor_bytes,
        'configured_home_floor_bytes': configured_home_floor_bytes,
        'home_publish_headroom_bytes': home_headroom_bytes,
        'other_reserved_storage_bytes': other_reserved_bytes,
        'home_free_bytes_at_guard': home_free_bytes,
        'current_attempt_id': current_attempt_id,
        'current_reservation_storage_bytes': current_reservation_storage_bytes,
        'staged_h5_bytes': h5_bytes,
        'publish_guard_status': 'prepublish_passed',
        'private_validation_workspace_deleted_after_publish': True,
        'wrapper_elapsed_seconds_before_publish': round(
            time.monotonic() - started, 6
        ),
    }
    report['storage_protocol'] = protocol

    # The report includes its measured byte count and remaining Home floor.
    # Iterate their decimal widths to a fixed point, writing only to a private
    # NVMe preview.  The guard therefore uses an actual stat of the exact JSON
    # bytes that will later be published, without opening a Home path.
    preview = staged_h5.parent / 'final-conversion-report.preview.json'
    planned_report = planned_total = remaining = 0
    for _ in range(12):
        protocol['final_report_bytes'] = planned_report
        protocol['planned_publish_bytes'] = planned_total
        protocol['remaining_after_publish_and_reservations'] = remaining
        measured_report = _write_private_report_preview(preview, report)
        _check_stage_budget(
            stage=staged_h5.parent,
            staging_root=staging_root,
            staging_limit_bytes=staging_limit_bytes,
            nvme_free_reserve_bytes=nvme_free_reserve_bytes,
            reason='final report preview',
        )
        guard = evaluate_publish(
            h5_bytes=h5_bytes,
            report_bytes=measured_report,
            cap_bytes=cap_bytes,
            home_free_bytes=home_free_bytes,
            home_floor_bytes=effective_home_floor_bytes,
            other_reserved_bytes=other_reserved_bytes,
            headroom_bytes=home_headroom_bytes,
        )
        measured_total = h5_bytes + measured_report
        measured_remaining = guard['remaining_after_publish_and_reservations']
        if (measured_report, measured_total, measured_remaining) == (
            planned_report, planned_total, remaining
        ):
            return report, measured_total, guard
        planned_report, planned_total, remaining = (
            measured_report, measured_total, measured_remaining
        )
    raise HomePublishRefusal('final report byte plan did not stabilize')


def run(args, staging_root: Path, staging_limit_bytes: int) -> dict:
    output = args.output.absolute()
    report_path = args.report.absolute()
    partial = output.with_suffix(output.suffix + '.partial')
    report_partial = report_path.with_suffix(report_path.suffix + '.partial')
    if any(
        path.exists() or path.is_symlink()
        for path in (output, partial, report_path, report_partial)
    ):
        raise FileExistsError('existing Home publication or partial report')
    home_root = args.home_root.absolute()
    if output == report_path:
        raise HomePublishRefusal('H5 and final report must be different paths')
    if (
        not home_root.is_dir()
        or not output.parent.exists()
        or not report_path.parent.exists()
        or not _same_device(home_root, output.parent)
        or not _same_device(home_root, report_path.parent)
    ):
        raise HomePublishRefusal('H5 and report must be on the guarded Home filesystem')
    if args.home_publish_cap_bytes <= 0 or args.home_publish_cap_bytes > DEFAULT_PUBLISH_CAP:
        raise HomePublishRefusal(
            'publish cap must be positive and no larger than the reviewed 4 GiB cap'
        )
    if staging_limit_bytes != DEFAULT_STAGING_LIMIT:
        raise HomePublishRefusal('the reviewed 24 GiB NVMe staging threshold is immutable')
    if args.nvme_free_reserve_bytes < DEFAULT_NVME_RESERVE:
        raise HomePublishRefusal('the reviewed 100 GiB NVMe free-space floor is immutable')
    if args.home_floor_bytes < DEFAULT_HOME_FLOOR:
        raise HomePublishRefusal('the reviewed 500 GiB Home floor is immutable')
    if args.home_publish_headroom_bytes < DEFAULT_HOME_HEADROOM:
        raise HomePublishRefusal('Home publish headroom may not be reduced below 2 GiB')
    if args.skip_partvtk_validation:
        raise HomePublishRefusal('this wrapper requires the official three-frame PartVTK check')
    if not args.current_attempt_id:
        raise HomePublishRefusal('current_attempt_id is required for reservation identity')
    if args.resource_ledger.absolute() == args.resource_ledger_lock.absolute():
        raise HomePublishRefusal('ledger JSON and its lock must be distinct paths')

    staging_root.mkdir(parents=True, exist_ok=True)
    if _same_device(home_root, staging_root):
        raise HomePublishRefusal('private staging must be on a separate NVMe filesystem')
    if shutil.disk_usage(staging_root).free < staging_limit_bytes + args.nvme_free_reserve_bytes:
        raise HomePublishRefusal('NVMe free-space floor is unavailable')
    started = time.monotonic()
    original_mkdtemp = converter.tempfile.mkdtemp
    original_decode = converter.decode_frame
    original_partvtk = converter._run_partvtk_frame
    stdlib_mkdtemp = tempfile.mkdtemp
    published = False
    output_moved = False
    try:
        with tempfile.TemporaryDirectory(
            prefix='ds02-home-capped-stage-', dir=staging_root
        ) as owned:
            owned_path = Path(owned)
            staged_h5 = owned_path / 'trajectory.h5'
            staged_report = owned_path / 'conversion-report.json'
            private_validation = owned_path / 'partvtk-validation'

            def private_mkdtemp(*names, **kwargs):
                kwargs['dir'] = str(owned_path)
                return stdlib_mkdtemp(*names, **kwargs)

            def check_stage(reason: str):
                return _check_stage_budget(
                    stage=owned_path,
                    staging_root=staging_root,
                    staging_limit_bytes=staging_limit_bytes,
                    nvme_free_reserve_bytes=args.nvme_free_reserve_bytes,
                    reason=reason,
                )

            def decode_and_reclaim(frame_path, decoder, scratch, index):
                try:
                    frame = original_decode(frame_path, decoder, scratch, index)
                    check_stage(f'decode frame {index}')
                    return frame
                finally:
                    prefix = scratch / f'frame_{index:04d}'
                    shutil.rmtree(prefix, ignore_errors=True)
                    prefix.with_suffix('.xml').unlink(missing_ok=True)

            def partvtk_with_stage_check(partvtk, data_root, frame, output_dir):
                result = original_partvtk(partvtk, data_root, frame, output_dir)
                check_stage(f'PartVTK frame {frame}')
                return result

            converter.tempfile.mkdtemp = private_mkdtemp
            converter.decode_frame = decode_and_reclaim
            converter._run_partvtk_frame = partvtk_with_stage_check
            try:
                converter.convert_direct(
                    data_root=args.data_root,
                    generated_xml=args.generated_xml,
                    output=staged_h5,
                    report_path=staged_report,
                    decoder=args.decoder,
                    partvtk=args.partvtk,
                    validation_dir=private_validation,
                    solver_log=args.solver_log,
                    solver_receipt=args.solver_receipt,
                    gencase_receipt=args.gencase_receipt,
                    owner_metadata=args.owner_metadata,
                    reference_hdf5=args.compare_hdf5,
                    run_partvtk=True,
                    keep_validation_csv=args.keep_validation_csv,
                    particle_chunk=args.particle_chunk,
                )
            finally:
                converter._run_partvtk_frame = original_partvtk
                converter.decode_frame = original_decode
                converter.tempfile.mkdtemp = original_mkdtemp

            check_stage('post-conversion')
            if staged_h5.stat().st_size > staging_limit_bytes:
                raise HomePublishRefusal('staged H5 exceeds registered NVMe limit')

            # Reservations are read while holding the actual shared lock used
            # by Root142; neither the JSON ledger nor the lock is modified.
            with _ledger_exclusive(args.resource_ledger_lock) as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                try:
                    ledger = _load_ledger(args.resource_ledger)
                    reservations = ledger['reservations']
                    current_matches = [
                        row for row in reservations
                        if row.get('id') == args.current_attempt_id
                    ]
                    if len(current_matches) != 1:
                        raise HomePublishRefusal(
                            'current_attempt_id must match exactly one live reservation id'
                        )
                    current_storage = int(
                        current_matches[0].get('new_storage_bytes', 0)
                    )
                    other_reserved = other_reserved_storage_bytes(
                        ledger, args.current_attempt_id
                    )
                    effective_floor = max(
                        int(args.home_floor_bytes),
                        int(ledger['limits']['home_min_free_bytes']),
                    )
                    free = _home_free(home_root)
                    report, planned_total, guard = _prepare_report(
                        staged_report=staged_report,
                        output=output,
                        staged_h5=staged_h5,
                        private_validation=private_validation,
                        cap_bytes=args.home_publish_cap_bytes,
                        configured_home_floor_bytes=args.home_floor_bytes,
                        effective_home_floor_bytes=effective_floor,
                        home_headroom_bytes=args.home_publish_headroom_bytes,
                        other_reserved_bytes=other_reserved,
                        home_free_bytes=free,
                        current_attempt_id=args.current_attempt_id,
                        current_reservation_storage_bytes=current_storage,
                        staging_limit_bytes=staging_limit_bytes,
                        nvme_free_reserve_bytes=args.nvme_free_reserve_bytes,
                        staging_root=staging_root,
                        started=started,
                    )
                    # No Home H5, partial, report, or report.partial has been
                    # opened before the guard above has passed.
                    if output.exists() or report_path.exists():
                        raise FileExistsError(
                            'Home publication appeared while the ledger guard was held'
                        )
                    actual = verified_copy(
                        staged_h5, partial, report['output_sha256']
                    )
                    if actual != report['output_sha256']:
                        raise HomePublishRefusal(
                            'verified-copy hash differs from direct report attestation'
                        )
                    report_bytes = _report_bytes(report)
                    if staged_h5.stat().st_size + report_bytes != planned_total:
                        raise HomePublishRefusal(
                            'publish bytes changed after verified copy'
                        )
                    try:
                        report_payload = (
                            json.dumps(report, indent=2, sort_keys=True) + '\n'
                        ).encode('utf-8')
                        with report_partial.open('xb') as writer:
                            writer.write(report_payload)
                            writer.flush()
                            os.fsync(writer.fileno())
                        os.replace(partial, output)
                        output_moved = True
                        if report_path.exists():
                            raise FileExistsError(
                                'final report appeared before atomic report publish'
                            )
                        os.replace(report_partial, report_path)
                        published = True
                    finally:
                        if report_partial.exists():
                            report_partial.unlink()
                        if partial.exists():
                            partial.unlink()
                finally:
                    fcntl.flock(lock, fcntl.LOCK_UN)
            return report
    except Exception:
        if partial.exists():
            partial.unlink()
        if report_partial.exists():
            report_partial.unlink()
        if (published or output_moved) and output.exists() and not report_path.exists():
            output.unlink()
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--staging-root', type=Path, required=True)
    parser.add_argument('--staging-limit-bytes', type=int, default=DEFAULT_STAGING_LIMIT)
    parser.add_argument('--nvme-free-reserve-bytes', type=int, default=DEFAULT_NVME_RESERVE)
    parser.add_argument('--home-publish-cap-bytes', type=int, default=DEFAULT_PUBLISH_CAP)
    parser.add_argument('--home-floor-bytes', type=int, default=DEFAULT_HOME_FLOOR)
    parser.add_argument(
        '--home-publish-headroom-bytes', type=int, default=DEFAULT_HOME_HEADROOM
    )
    parser.add_argument('--home-root', type=Path, default=DEFAULT_HOME_ROOT)
    parser.add_argument('--resource-ledger', type=Path, default=DEFAULT_LEDGER)
    parser.add_argument('--resource-ledger-lock', type=Path, default=DEFAULT_LOCK)
    parser.add_argument('--current-attempt-id', required=True)
    parser.add_argument('converter_args', nargs=argparse.REMAINDER)
    opts = parser.parse_args()
    argv = opts.converter_args
    if argv and argv[0] == '--':
        argv = argv[1:]
    args = converter._build_parser().parse_args(argv)

    def stop_owned(*_):
        raise SystemExit(143)

    signal.signal(signal.SIGTERM, stop_owned)
    result = run(opts, opts.staging_root, opts.staging_limit_bytes)
    print(
        json.dumps(
            {
                'frames': result['frames'],
                'particles': result['particles'],
                'partvtk_all_passed': result['partvtk_validation']['all_passed'],
                'output_sha256': result['output_sha256'],
            },
            sort_keys=True,
        ),
        flush=True,
    )
