# F3 fresh065: first48 pitch/AY source handoff

This package adds 24 prospective F3 physical conditions to the existing first24
source set.  The new conditions are the Cartesian product of pitch multipliers
`0.8` and `1.2` with AY values `0.25, 0.29, 0.32, 0.36, 0.39, 0.43, 0.46,
0.50, 0.54, 0.57, 0.64, 0.75`.  `first48-manifest.json` retains the unchanged
fresh064 first24 case IDs as its first24 subset and appends these 24 new IDs.

The frozen transformer has been reviewed at the source level: `amplitude_x`
is the longitudinal pitch control and `amplitude_y` is the transverse linear
acceleration control.  `prepare_pitch_axis.py` binds those two arguments
explicitly.  It does not infer CSV columns.  The genuine DP006 3D XML/BI4
initial clone, particle counts, mass policy, DP, `-mdbc_noslip:1`, `tmax=8.35`,
`tout=0.01`, and expected 836 saved frames remain unchanged.

Every new condition, owner, and native full836 request is source-only and
disabled.  New forcing, physical-condition, preparation receipt, solver,
typed-conversion, and visual evidence hashes are null until Root executes and
audits the corresponding stage.  This package grants no production scope,
precision status, QN, or case-count increment.  The pitch values are outside
the currently registered nominal pitch domain.  The four corners
`(.8,.25)`, `(.8,.75)`, `(1.2,.25)`, and `(1.2,.75)` require independent
qualification, native-to-typed evidence, complete full836 products, and Root
visual decisions before any two-dimensional pitch/AY domain registration.

Run the source-only contract check from this directory with:

```text
python3 -B tests/test_fresh065_contract.py
```

The check reads JSON and small source files only.  It deliberately does not
open or hash BI4, H5, or CSV payloads.  Root's strict CPU runner owns actual
forcing materialization and all future artifact hashes.
