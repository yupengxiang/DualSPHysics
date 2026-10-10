"""Verify unchanged actual ROOT313 output with a versioned ABI adapter.

The frozen verifier orchestrator and all scientific/fee assertions are
retained. Only the independent checker path and output path change. The
original producer request, output and failed V5 check remain evidence.
"""
from pathlib import Path
import datetime
import hashlib
import importlib.util
import json
import sys

HERE = Path(__file__).resolve().parent
S = HERE.parents[1]
FROZEN = S / 'governance/root-owned-native-admission-v1/verify_actual_mass313_v1.py'
FROZEN_SHA = 'bb6591775b83d43e36c3f00989e5b0b7e97db0c41a78e316a2b31fbd766acca8'
REQUEST = S / 'requests/native-typed-mass-impact-root-forward-313-006.json'


def read(path):
    assert path.suffix == '.json' and path.stat().st_size <= 10485760 and not path.is_symlink()
    return json.loads(path.read_text())


def main():
    assert FROZEN.stat().st_size <= 10485760
    raw = FROZEN.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == FROZEN_SHA
    request = read(REQUEST)
    base = Path('/home/jade/Projects/DualSPHysics-data/ds-data-02/families')
    base = base / request['family_id'] / request['case_id'] / request['attempt_id']
    report = read(base / 'root313-native-typed-mass-impact.json')
    assert report['schema'] == 'ds02.stage2.native-typed-mass-impact.root313-report'
    assert report['status'] == 'COMPLETED_ROOT313_NATIVE_TYPED_MASS_IMPACT_DIAGNOSTIC_ONLY'
    assert report['counts'] == {'requested': 17, 'completed': 17, 'failed': 0}
    text = raw.decode()
    replacements = {
        'ds_data02_stage2_verify_native_typed_mass_impact_v5.py':
        'ds_data02_stage2_verify_native_typed_mass_impact_v8_root313_compat.py',
        'ROOT313_NATIVE_TYPED_MASS_IMPACT_INDEPENDENT_VERIFICATION_V5.json':
        'ROOT313_NATIVE_TYPED_MASS_IMPACT_INDEPENDENT_VERIFICATION_V8_COMPAT.json',
    }
    for old, new in replacements.items():
        assert text.count(old) == 1
        text = text.replace(old, new)
    context = {'__name__': 'root313_frozen_actual_verifier_compat', '__file__': str(FROZEN)}
    exec(compile(text, str(FROZEN), 'exec'), context)
    sys.argv = [str(FROZEN), str(REQUEST)]
    context['main']()
    admission_path = S / 'governance/root-owned-native-admission-v1/continue_after_serial_v1.py'
    spec = importlib.util.spec_from_file_location('root313_frozen_handoff', admission_path)
    a = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(a)
    proof = S / 'checkpoints/NATIVE_TYPED_MASS_IMPACT_ACTUAL_ROOT_VERIFICATION_313.json'
    p = a.load(proof)
    assert p['parent_reservation_released'] and p['repeat_fee_idempotent']
    assert p['verified_counts']['completed'] == 17 and p['verified_counts']['failed'] == 0
    assert a.state('ds02-native-typed-mass-impact-root-313')['SubState'] == 'dead'
    handoff_path = S / 'checkpoints/ROOT310_AFTER_SERIAL_ACTUAL_NATIVE_FULL_GOAL_CONTINUATION_V1.json'
    handoff = a.load(handoff_path)
    cp = S / 'checkpoints/ROOT313_AFTER_NATIVE_ACTUAL_MASS_FULL_GOAL_CONTINUATION_V2.json'
    a.new(cp, {'schema': 'ds02.stage2.root-mass-after-native-actual-continuation.v2',
        'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'goal_status': 'ACTIVE_FULL_SEVEN_ITEMS', 'goal_complete': False,
        'actual_lifecycle_terminal': handoff['actual_lifecycle_terminal'],
        'preceding_actual_native_handoff': a.ref(handoff_path),
        'actual_native_scope': handoff['actual_native_scope'],
        'actual_mass_proof': a.ref(proof), 'verified_counts': p['verified_counts'],
        'abi_repair_root_source': a.ref(Path(__file__)),
        'frozen_root_verifier_source': a.ref(FROZEN),
        'original_verifier_rejection': a.ref(S / 'checkpoints/ROOT313_ACTUAL_REPORT_PENDING_VERIFIER_ABI_REPAIR_V1.json'),
        'new_native_cause_credit': 0, 'new_native_join_credit': 0,
        'physical_fate_flux_dynamics_Q': 'UNKNOWN', 'root_payload_content_read': False,
        'next': 'continue frozen geometry/portable/initial/reference/mass/native chains and actual seven-family field pilots'})
    print(json.dumps({'event': 'ACTUAL_MASS313_COMPAT_VERIFIED_HANDOFF',
                      'checkpoint': str(cp), 'sha256': a.sha(cp), 'goal_complete': False}), flush=True)


if __name__ == '__main__':
    main()
