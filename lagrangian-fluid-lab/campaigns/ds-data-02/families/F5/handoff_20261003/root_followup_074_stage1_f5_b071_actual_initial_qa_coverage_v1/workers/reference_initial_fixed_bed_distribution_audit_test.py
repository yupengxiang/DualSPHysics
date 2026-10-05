import importlib.util
from pathlib import Path

MODULE = Path(__file__).parents[1] / "scripts" / "initial_fixed_bed_distribution_audit.py"
spec = importlib.util.spec_from_file_location("candidate_b_audit", MODULE)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

def test_synthetic_source_only_audit():
    module._check()
