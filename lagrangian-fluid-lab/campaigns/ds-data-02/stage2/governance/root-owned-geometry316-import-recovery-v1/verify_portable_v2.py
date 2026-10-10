"""Explicit importlib.util bootstrap for the frozen portable verifier."""
from pathlib import Path
import hashlib
import importlib.util
import sys

SOURCE = Path(__file__).resolve().parent.parent / 'root-owned-portable-admission-v1/verify_actual_v1.py'
assert SOURCE.stat().st_size < 10485760
raw = SOURCE.read_bytes()
assert hashlib.sha256(raw).hexdigest() == '06247c1d05fc1c2b2248c04efcda2df54e1257ceda827fbb2d3d1867306c6de9'
sys.path.insert(0, str(SOURCE.parent))
sys.argv[0] = str(SOURCE)
exec(compile(raw, str(SOURCE), 'exec'), {'__name__': '__main__', '__file__': str(SOURCE)})
