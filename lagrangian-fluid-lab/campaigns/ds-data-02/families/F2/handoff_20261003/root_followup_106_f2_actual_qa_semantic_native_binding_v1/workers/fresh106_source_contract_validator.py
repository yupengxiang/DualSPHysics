#!/usr/bin/env python3
"""Validate generated fresh106 metadata without runtime validation or raw reads."""
from __future__ import annotations
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
loader = importlib.util.spec_from_file_location('fresh106_builder', HERE / 'build_fresh106.py')
if loader is None or loader.loader is None:
    raise SystemExit('cannot load fresh106 builder')
mod = importlib.util.module_from_spec(loader)
loader.loader.exec_module(mod)


def load(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def main() -> int:
    manifest = load(HERE / 'F2_STAGE1_FRESH106_ACTUAL_QA_SEMANTIC_NATIVE_BINDING_MANIFEST.json')
    failures = []
    rows = manifest.get('cases', [])
    if manifest.get('case_count') != 16 or len(rows) != 16:
        failures.append('case_count')
    for row in rows:
        req_path = Path(row['native_request']['path'])
        req = load(req_path)
        closure = mod.check_command_input_closure(req)
        if not closure['passed']:
            failures.append(f"native-closure:{row['case_id']}")
        if req.get('disabled') is not True or req.get('execution_allowed') is not False or req.get('launch_allowed') is not False:
            failures.append(f"disabled:{row['case_id']}")
        if req.get('native_receipt_sha256') is not None or req.get('run_out_sha256') is not None:
            failures.append(f"future-hash:{row['case_id']}")
        if not row.get('gate', {}).get('enable_eligible'):
            failures.append(f"actual-gate:{row['case_id']}")
    evidence = load(HERE / 'evidence/upstream-actual-binding.json')
    upstream_missing = []
    for row in evidence.get('cases', []):
        for name in ('qa_request', 'semantic_request'):
            check = row['command_input_closure'][name]
            if check['missing_command_inputs']:
                upstream_missing.extend(check['missing_command_inputs'])
    result = {
        'schema': 'ds02.f2.stage1.fresh106.source-contract-validation.v1',
        'case_count': len(rows), 'native_requests_disabled': not failures,
        'all_native_command_closures_pass': not any(x.startswith('native-closure:') for x in failures),
        'actual_gate_count': sum(bool(x.get('gate', {}).get('enable_eligible')) for x in rows),
        'upstream_missing_command_input_count': len(upstream_missing),
        'upstream_missing_command_inputs_unique': sorted(set(upstream_missing)),
        'upstream_missing_inputs_reported_not_repaired': True,
        'runtime_v2_validate_request_called': False,
        'scientific_payloads_read_or_hashed_here': [],
        'failures': failures,
        'status': 'pass' if not failures else 'fail',
    }
    out = HERE / 'evidence/fresh106-validator-run.json'
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not failures else 2


if __name__ == '__main__':
    raise SystemExit(main())
