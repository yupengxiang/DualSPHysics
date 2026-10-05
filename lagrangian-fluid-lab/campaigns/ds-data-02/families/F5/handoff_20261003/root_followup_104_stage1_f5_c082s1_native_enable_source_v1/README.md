# F5 fresh104: actual QA-bound disabled 51-frame native enablement

This source-only package inherits immutable fresh103 and binds the real
Root426 GenCase and QA441 JSON metadata for candidates A080 and A120. Both
candidates have producer evidence of 194427 total particles, 158559 fixed,
4210 moving, 0 floating, 31658 fluid, and solver dimension 3. The prepared
report's BI4 and XML digests are copied as producer attestations; this package
never opens or hashes those payloads.

QA441 completed with all basic placement/Mk50 checks true, including finite
rows, UID/type/Mk integrity, 3-D placement, no overlap, fluid above the
continuous bed, 15 transverse levels, and central native Mk50 support in six
x segments. The original exact DP lattice threshold remains a diagnostic and
numerical_precision_result_accepted remains false. QA441 grants no solver,
Q-N, full16, full801, visual, or case acceptance.

requests/A080-native-enable-request.json and its A120 counterpart are the
complete runtime closure for a disabled 1 s/51-frame native solver request:
the official solver path, CPU2/4096 MiB profile, Root230/root142 policy
digests, actual GenCase/QA receipt paths, actual counts, actual generated
XML/BI4 producer attestations, Root425 single motion-asset path/hash, and
source-helper hashes are all recorded. The request remains launch=false,
execution_allowed=false, solver_allowed=false, and all native/typed/XMF/bed
future output hashes remain null. The actual motion asset is listed with its
producer-declared DAT digest; source validation refuses to open it.

Use the source validator:

/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python scripts/validate_fresh104.py

For a reviewable metadata binding (no execution), use:

python3 scripts/bind_native_enable.py --candidate A080 \
  --gencase-receipt <actual execution-receipt.json> \
  --prepared-report <actual prepared-input-report.json> \
  --initial-qa-report <actual c082s1-stage1-placement-mk50-audit.json> \
  --initial-qa-receipt <actual QA execution-receipt.json> \
  --output-summary <root-owned JSON summary>

The helper reads and hashes JSON only. It keeps the future native receipt,
solver output, typed H5, XMF manifest and bed audit hashes null. Root must
review the actual native 51-frame result and then register typed/XMF/bed
workers sequentially. No full16/full801 permission is implied.

Source preparation facts: no job was started, no shared ledger or registry was
modified, no science payload was read or hashed, and this package adds zero
independent cases.
