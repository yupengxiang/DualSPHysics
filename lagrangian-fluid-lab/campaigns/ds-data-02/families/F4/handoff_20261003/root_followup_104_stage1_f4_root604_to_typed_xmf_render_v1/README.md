# F4 fresh104 Root604 to native, typed, XMF and Root023 handoff

This source-only package binds all 24 actual Root604 GenCase reports. Counts,
3-D status, generated XML digest, and BI4 producer digest come from each
prepared-input-report.json. The raw Root604 receipt remains immutable; the
per-case semantic evidence sidecar only exposes report-backed fields required
by the qualification runtime.

Each case has four independent disabled singleton requests:

1. Root230 full native, DP=.01, 1.2 s, .001 s, 1201 frames, no forcing/no mDBC;
2. CPU2/NVMe-cap2 direct typed conversion with official PartVTK validation;
3. N3 temporal XMF export;
4. Root023 full 1201-frame software rendering.

Root616 basic QA, Root619 native completion, and Root623 frame-0 raw
Mk/Type/velocity QA are now bound as actual per-case evidence. Root626's
independent review confirms all 24 frame-0 checks passed, with no initial
padding or missing particles; the observed native Run.out exclusion values
remain recorded per case. This evidence does not grant precision, Q-N,
visual, or production acceptance. Typed conversion, XMF, full render, and
their product hashes remain deferred and null.

The original fresh102 owner/source-plan condition hashes are retained. The
original owner is legacy scope under the converter. fresh104 derives an
allowlisted physical-binding.v1 object and records the real converter
_validate_physical_binding/canonical_hash result in the preflight evidence.
The derived converter hash is kept separate from source hashes and does not
grant canonical qualification, Q-N, precision, visual, or production status.

The package never reads or hashes BI4/H5/VTK/CSV/DAT payloads, launches jobs,
or writes shared state. `workers/verify_frame0_contract.py` documents and
checks the singleton `cases=[...]` wrapper required by fresh103 and the
per-case fresh097 audit; it does not execute either worker.
