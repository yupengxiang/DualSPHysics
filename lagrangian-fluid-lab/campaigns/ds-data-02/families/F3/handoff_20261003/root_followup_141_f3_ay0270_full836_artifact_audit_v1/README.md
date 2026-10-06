# F3 fresh141: AY0270 full-836 artifact audit

This package is a disabled, Root-owned CPU audit handoff for the existing
`F3_STAGE1_DP006_P1000_AY0270` trajectory. It does not restart or settle the
old typed attempt. The old receipt remains `running` with a null return code;
the historical tool status `143` and the earlier pre-launch rejection remain
separate evidence. A future audit return code of zero would be a new,
independent fact.

Root may register the request as one serial CPU task with two threads. The
disabled source request intentionally omits the opaque H5 from its immutable
digest map. Before strict dispatch, Root must derive a new request, stream the
H5 once, add its actual SHA-256 for that absolute input path, and revalidate
the complete input closure under the strict guard.

The worker reads the immutable conversion report, GenCase/native/request metadata,
then reads and streams the existing H5 only inside that registered Root job.
It imports the approved `f3_full_temporal_verify_v1` kernel and adds the F3
typed-field checks: all 836 report times and lifecycle counts, composite
`particle_zone`/`particle_id` identity, N-by-3 position and velocity, finite
state fields, and integer type/Mk counts. It writes a new audit receipt with
an exclusive, fsynced publish; it never edits the old receipt or H5 and does
not grant production, Q-N, or case credit.

The existing fresh073 worker is recorded in
`metadata/source-audit-kernel-comparison.json`. It is useful for opaque SHA
and metadata closure but deliberately does not decode H5 datasets, so fresh141
uses the approved full temporal reader plus this typed schema adapter. The
source agent did not open, decode, copy, or hash H5/BI4/CSV/DAT/VTK payloads;
the binding leaves the H5 digest null for Root to produce at execution time.

The actual native physical identity, the converter's legacy scope, and the
fresh139 first-48 census alias are recorded as separate fields. The alias is
not substituted into the old receipt or used to create an additional case.
All future audit/report/XMF/visual hashes remain null in this disabled source
package. `scripts/validate_fresh141.py` and the small tests inspect only
metadata, code, and package files; they do not touch scientific payloads.
