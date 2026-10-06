#!/usr/bin/env python3
"""Metadata/proc-evidence validator for fresh140; never follows external payload paths."""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def load(name: str):
    return json.loads((ROOT / 'metadata' / name).read_text())

def main() -> int:
    audit = load('ay0270-process-recovery-audit.json')
    render = load('new-render-status.json')
    visual = load('visual-review-readiness.json')
    assert audit['case_id'] == 'F3_STAGE1_DP006_P1000_AY0270'
    assert audit['historical_receipt']['status'] == 'running'
    assert audit['historical_receipt']['returncode'] is None
    assert audit['historical_processes']['launcher_pid'] == 2367173
    assert audit['historical_processes']['child_pid_recorded_in_receipt'] == 2367325
    assert audit['historical_processes']['launcher_start_ticks'] is None
    assert audit['historical_processes']['child_start_ticks'] is None
    assert audit['current_authoritative_checkpoint']['matching_active_reservation_present'] is False
    assert len(render['cases']) == 2
    assert all(x['terminal_completed_0'] is False for x in render['cases'])
    assert all(not x['local_terminal_receipt_paths'] for x in render['cases'])
    assert all(not x['local_full_animation_report_paths'] for x in render['cases'])
    assert visual['selected_cases'] == []
    assert audit['recovery_state'].startswith('unfinalized_receipt_')
    print(json.dumps({'status':'pass','fresh_id':'fresh140','ay0270_receipt':'running/null','historical_pids_absent':True,'render_controllers_audited':2,'visual_cases_selected':0},sort_keys=True))
    return 0

if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (AssertionError, KeyError, json.JSONDecodeError) as exc:
        print(f'fresh140 validation failed: {exc}', file=sys.stderr)
        raise SystemExit(1)
