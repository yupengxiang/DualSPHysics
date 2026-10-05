# F4 fresh096 Root502 basic QA to Root230 full1201 native handoff

Fresh096 binds the actual Root502-derived basic GenCase QA closure for all 24
F4 cases. Root503 reports 24/24 completed/0 and Root504 records all basic
checks true. The original Root500 first-case failure/held evidence and Root471
strict continuum/lattice negative evidence remain preserved.

Each native request is disabled and gated on its matching Root502 request,
actual execution receipt, and `gencase-basic-initial-qa.json` report. The gate
requires completed/0 plus `audit.pass=true` and every basic check true. Raw
Mk/Type are not claimed as observed: the type/source partition remains
derived from XML and Idp ranges. Mass is diagnostic only and is never
rescaled.

The native command is the approved Root230 solver with the exact
`-tmax:1.2 -tout:0.001` recipe, dp=.01, 1,201 frames, no mDBC and no forcing.
CPU/OMP threads are 2. Root resolves live UUID leases only at enable time,
protects foreign processes, and enforces the Home/NVMe floors and parent
resource window. Future native receipts, frame-0 reports, typed outputs and
hashes are null.

Fresh094 is recorded as a post-native frame-0 downward-velocity contract only;
it is deliberately absent from the pre-solver dependency list so the
pipeline is acyclic. No solver, converter, array read, scientific-payload
hash/copy, or shared registry write was performed by this package.

Validate with:
`PYTHONPYCACHEPREFIX=/tmp/ds02-fresh096-validator-pyc python3 tests/validate_source_contract.py`.
