# fresh193 full336 user-delivery index

This package is a metadata-only delivery directory and index draft frozen from
Root checkpoint 326. It describes 332 accepted independent physical cases out
of 336, with four cases still pending. `delivery_complete` is therefore
`false`; this package does not promote pending work, grant case credit, or
replace the main checkpoint.

The authoritative machine-readable entry point is
`metadata/full336-user-delivery-index.json`. It records the exact checkpoint
and current-index paths and SHA-256 values, the seven family primary products,
their explicit membership arrays, per-family navigation contracts, the four
pending observations, and the latest F5=45 product. The latest F5 source is
Root1439; the older 44-case F5 product is historical and is not the current
source. F2's 48-case source is fresh226 in the F5 worktree.

## Selecting a case

Use a family product's explicit `physical_case_id` arrays. The frozen first
eight must be a subset of the ordered actual first 24, which must be a subset
of the registered final 48. Those arrays are authoritative; do not sort case
names, substitute a case alias, count a resolution replica, or use a
directory listing to reconstruct membership. Resolve the selected physical ID
to its own row in that family's primary product while retaining its `case_id`
aliases and each native, typed, XMF, SourceDef, and source-plan namespace.

For an accepted row, open that row's own `primary_XMF_XML` or
`ParaView_open_XMF` together with its `primary_XMF_manifest` in ParaView. Use
the same row's render report, execution receipt, and published output refs for
the complete animation. Use the row's published contact sheets and navigation
key refs for overview. A request, readiness record, private staged directory,
or another case's manifest is not a completed animation.

The package itself only reads and hashes JSON metadata. It does not open,
copy, or hash H5/BI4/IBI4/CSV/DAT/VTK scientific payloads or PNGs, and it does
not start jobs or write shared state. Published PNG refs are preserved as
provenance for a downstream consumer; their presence is not a new personal
visual review by this package.

## Current state

The checkpoint contains these accepted counts:

| Family | Accepted | Roster | Status |
| --- | ---: | ---: | --- |
| F1 | 48 | 48 | accepted |
| F2 | 48 | 48 | accepted; fresh226 primary source |
| F3 | 47 | 48 | AY0390 pending |
| F4 | 48 | 48 | accepted |
| F5 | 45 | 48 | M095/T090, M104/T085, M106/T085 pending |
| F6 | 48 | 48 | accepted rigid/particle delivery |
| F7 | 48 | 48 | accepted |

The four pending physical cases are:

- `F3_TWOAXIS_P1200_AY0390_STAGE1_FIRST48_PITCH_VARIANT` — 836-frame,
  179208-particle render request; no actual receipt or publication in the
  frozen observation.
- `F5_COMPACT_RUNUP_RECOVERY_C082S1_M095_T090` — 801-frame,
  194427-particle request; no actual receipt or publication in the frozen
  observation.
- `F5_COMPACT_RUNUP_RECOVERY_C082S1_M104_T085` — 801-frame,
  194427-particle request; no actual receipt or publication in the frozen
  observation.
- `F5_COMPACT_RUNUP_RECOVERY_C082S1_M106_T085` — 801-frame,
  194427-particle request; no actual receipt or publication in the frozen
  observation.

Their request and manifest refs, historical PID/start-tick observations, and
null future hashes are in `pending_cases`. Those observations are frozen
metadata, not a new liveness probe and not a restart instruction.

## Family evidence limits

- F1, F4, and F7 use the Root1261 primary products. Their accepted decisions
  are visual delivery decisions; numerical precision is not certified.
- F6 uses the Root1353 particle/rigid-motion product. Its baseline Part/time
  verification limitation and particle-versus-continuum mass semantics remain
  explicit.
- F3 has 47 accepted primary rows in Root1433. Original154 typed runtime
  unknowns, recovery evidence, and the AY0390 pending row remain separate;
  shared initial QA is not relabeled as an independent per-case QA.
- F5 uses the latest Root1439 45-case primary/bed product. Native canonical,
  typed legacy, XMF condition/physical plan, SourceDef, and source-plan roles
  remain separate; missing legacy publication receipts and runtime unknowns
  remain missing.
- F2's fresh226 48-case source is kept in the F5 worktree. Older partial
  42/6 or 33/15 products are historical and are not the final source.

Across families, per-case particle omissions and causes remain exactly as
reported. Original runtime/return-code gaps, recovery audits, and absent
legacy atomic-publication receipts are not rewritten. Numerical precision,
strict containment, sub-DP depth, run-up magnitude, production acceptance,
and Q-N/Q-E qualification are outside this delivery index; `Q_N=0`,
`Q_E=0`, and `new_case_credit=0`.

## Validation

From this package directory, run:

```sh
python3 -B scripts/validate_user_delivery_index.py
```

The validator checks JSON-only source SHA closure, checkpoint 326, the 332/4
counts, all explicit 8/24/48 membership subsets, the four pending identities,
the Root1439 F5 extension, F2 fresh226 provenance, and the source-boundary
flags. It intentionally does not validate scientific payloads or PNG content.

Configured provenance for this package is `gpt-5.6-luna/max`; no model
substitution or recursive delegation was used.
