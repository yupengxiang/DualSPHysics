#!/usr/bin/env python3
"""Forward-only cleanup wrapper for the native typed task-impact screen.

The v2 sidecars remain immutable.  This version removes the legacy XML-based
fraction field from each MK row so consumers cannot mistake it for the native
typed denominator; all v2 evidence and bindings are retained.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from ds_data02_runtime_v2 import atomic_json
from ds_data02_stage2_omission_task_impact_v2 import assess as assess_v2


def assess(sidecar_path: Path) -> dict:
    result = assess_v2(sidecar_path)
    for group in result.get('source_mk_breakdown', []):
        group.pop('missing_mass_fraction_of_frozen_initial_fluid', None)
    result['schema'] = 'ds02.stage2.omission-task-impact.v3'
    result['status'] = 'TASK_IMPACT_SCREENED_NATIVE_TYPED_DENOMINATOR_DYNAMICS_UNAVAILABLE'
    result.setdefault('source_evidence', {})['task_module_version'] = 'v3-forward-cleanup'
    result.setdefault('unknown_and_acceptance', {})['denominator_version'] = 'native_typed_scan_v3'
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sidecar', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('Preserve existing task-impact sidecar: ' + str(args.output))
    result = assess(args.sidecar)
    atomic_json(args.output, result)
    print(json.dumps({'status': result['status'], 'case': result['physical_case_id'],
                      'missing_fraction': result['missing_mass_screen']['identified_missing_mass_fraction'],
                      'screen': result['missing_mass_screen']['screen']}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
