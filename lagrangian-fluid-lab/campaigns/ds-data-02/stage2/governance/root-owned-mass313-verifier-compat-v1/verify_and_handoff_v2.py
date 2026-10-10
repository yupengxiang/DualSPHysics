"""Recover the root verifier's launch cwd without overwriting prior evidence."""
from pathlib import Path
import hashlib
import os

HERE = Path(__file__).resolve().parent
PRIOR = HERE / 'verify_and_handoff_v1.py'
PRIOR_SHA = 'f4d0a4701b3f7e4c36bf6793ac48f363e8664076ee7170638f0e756bc39fb7c3'


def main():
    assert PRIOR.stat().st_size < 10485760
    raw = PRIOR.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == PRIOR_SHA
    # The frozen common accounting helper intentionally uses Path.cwd().
    # The first invocation from the repository root completed the independent
    # 17-case verifier but could not write the CPU evidence under LAB. Preserve
    # that completed verification and use a fresh metadata verification path.
    stage = HERE.parents[1]
    lab = stage.parents[2]
    os.chdir(lab)
    text = raw.decode()
    prior_output = 'ROOT313_NATIVE_TYPED_MASS_IMPACT_INDEPENDENT_VERIFICATION_V8_COMPAT.json'
    assert text.count(prior_output) == 1
    text = text.replace(prior_output,
        'ROOT313_NATIVE_TYPED_MASS_IMPACT_INDEPENDENT_VERIFICATION_V8_COMPAT_RETRY2.json')
    context = {'__name__': 'root313_verified_metadata_cwd_recovery', '__file__': str(Path(__file__).resolve())}
    exec(compile(text, str(PRIOR), 'exec'), context)
    context['main']()


if __name__ == '__main__':
    main()
