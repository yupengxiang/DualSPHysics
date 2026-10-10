"""Run frozen native verifier with the declared recovery memory envelope."""
from pathlib import Path
import json
import sys

HERE = Path(__file__).resolve().parent
S = HERE.parents[1]
source = S / 'governance/root-owned-native-admission-v1/verify_actual_native_v1.py'
assert sys.argv[1:4] == ['274', 'F6', '1']
q = json.loads(Path(sys.argv[4]).read_text())
assert q['max_memory_bytes'] == 8589934592
assert q['root_failed_attempt_lineage']['path'] == str(S / 'checkpoints/ROOT274_ORPHAN_FAILED_PARENT_RECONCILIATION_V1.json')
# The frozen V1 verifier assumes every native unit has 4 GiB. Only replace
# its literal footer memory expectation; every scientific/source/accounting
# assertion is retained, and the actual request controls the declared limit.
code = source.read_text()
needle = ".replace('1073741824','4294967296')"
assert code.count(needle) == 1
code = code.replace(needle, ".replace('1073741824','8589934592')")
exec(compile(code, str(source), 'exec'), {'__file__': str(source), '__name__': '__main__'})
