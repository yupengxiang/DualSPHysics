"""Resume after verified ROOT316 with explicit frozen helper import path."""
from pathlib import Path
import hashlib
import os

HERE = Path(__file__).resolve().parent
PRIOR = HERE / 'resume_v1.py'
assert PRIOR.stat().st_size < 10485760
raw = PRIOR.read_bytes()
assert hashlib.sha256(raw).hexdigest() == '6126a02b1b7a866a595d57f7a88319458ed33879b9138c53a894448541462ffb'
text = raw.decode()
start = "    source = OLD / 'verify_geometry316_v1.py'"
end = "    continuation = OLD / 'continue_after_mass_v2.py'"
assert text.count(start) == text.count(end) == 1
replacement = '''    proof = S / 'checkpoints/GEOMETRY_SUPPORT_ACTUAL_ROOT_VERIFICATION_316.json'
    assert proof.stat().st_size < 10485760
    assert hashlib.sha256(proof.read_bytes()).hexdigest() == '746e28443a65c5ea4ec2be28e547174971a05279041540ff888ac6686cbc976b'
    # The geometry worker, independent checks, full CPU fee and unit shutdown
    # already completed. Keep that evidence and resume only the portable tail.
    sys.path.insert(0, str(OLD))
'''
text = text[:text.index(start)] + replacement + text[text.index(end):]
# Retain V1's lock, predecessor evidence checks and frozen continuation tail.
exec(compile(text, str(PRIOR), 'exec'), {'__name__': '__main__', '__file__': str(Path(__file__).resolve())})
