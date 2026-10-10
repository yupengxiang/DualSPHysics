"""Complete unchanged geometry evidence, then resume frozen portable handoff."""
from pathlib import Path
import fcntl
import hashlib
import importlib.util
import os
import sys

HERE = Path(__file__).resolve().parent
S = HERE.parents[1]
LAB = S.parents[2]
OLD = S / 'governance/root-owned-portable-admission-v1'
D = Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')


def bounded_source(path, digest):
    assert path.stat().st_size < 10485760
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == digest
    return raw.decode()


def main():
    os.chdir(LAB)
    source = OLD / 'verify_geometry316_v1.py'
    text = bounded_source(source, '928cca48053f246a4bd7975c5525a8e9c0b7f40b2df9a55fdb2d586bfa9ec301')
    token = 'ROOT316_GEOMETRY_SUPPORT_INDEPENDENT_VERIFICATION_V2.json'
    assert text.count(token) == 1
    # Preserve the prior independently verified metadata output. Its accounting
    # footer failed because importlib.util had not been explicitly imported.
    text = text.replace(token, 'ROOT316_GEOMETRY_SUPPORT_INDEPENDENT_VERIFICATION_V3_IMPORT_RECOVERY.json')
    context = {'__name__': 'root316_import_recovery', '__file__': str(source)}
    exec(compile(text, str(source), 'exec'), context)
    sys.argv = [str(source), str(S / 'requests/four-sentinel-geometry-audit-root-forward-316-002.json')]
    context['main']()

    continuation = OLD / 'continue_after_mass_v2.py'
    frozen = bounded_source(continuation, 'e72259812569d40286b7c3772c0ba22320e773d075bdc6b1a0fd775706267b3a')
    spec = importlib.util.spec_from_file_location('root316_frozen_continuation', continuation)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    a = module.load_module(S / 'governance/root-owned-native-admission-v1/continue_after_serial_v1.py', 'root316_frozen_admission')
    barrier = S / 'checkpoints/ROOT313_AFTER_NATIVE_ACTUAL_MASS_FULL_GOAL_CONTINUATION_V2.json'
    prior = a.load(barrier)
    assert prior['goal_complete'] is False and prior['goal_status'] == 'ACTIVE_FULL_SEVEN_ITEMS'
    for key in ['actual_lifecycle_terminal', 'actual_native_scope', 'actual_mass_proof']:
        assert a.sha(prior[key]['path']) == prior[key]['sha256']
    assert not a.load(D / 'runtime/resource-ledger.json')['reservations']
    primary_gate = module.assert_primary_venv_gate(a)
    start = "    geometry = S / 'checkpoints/GEOMETRY_SUPPORT_ACTUAL_ROOT_VERIFICATION_316.json'"
    assert frozen.count(start) == 1
    tail = frozen[frozen.index(start):frozen.index("\n\nif __name__ == '__main__':")]
    token = "str(HERE / 'verify_actual_v1.py')"
    assert tail.count(token) == 1
    tail = tail.replace(token, "str(HERE_RECOVERY / 'verify_portable_v2.py')")
    globals_for_tail = dict(module.__dict__, admission=a, barrier=barrier,
                            prior=prior, primary_gate=primary_gate, HERE_RECOVERY=HERE)
    exec(compile('def resume_tail():\n' + tail + '\n', str(continuation), 'exec'), globals_for_tail)
    globals_for_tail['resume_tail']()


if __name__ == '__main__':
    with (D / 'runtime/root-owned-postmass-geometry-portable-v1.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        main()
