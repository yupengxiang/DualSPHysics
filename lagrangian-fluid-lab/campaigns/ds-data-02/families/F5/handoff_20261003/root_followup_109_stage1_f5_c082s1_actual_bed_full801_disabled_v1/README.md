# F5 fresh109: actual short bed evidence and disabled full801 native templates

Root506 XMF and Root509 dynamic bed audits are actual completed/0 producer evidence. This source-only pack reads only their JSON/XML metadata; it does not read or hash H5/BI4/CSV/VTK/DAT and does not start a solver.

## Short-window evidence

- A080: 51 frames, N=194427, fluid UID denominator=31658, max 1DP=0, max 2DP=0, max missing UID=0, max nonfinite UID=0, x/y outside footprint=0/0; report remains diagnostic-only and visual review is WAIT.
- A120: 51 frames, N=194427, fluid UID denominator=31658, max 1DP=0, max 2DP=0, max missing UID=0, max nonfinite UID=0, x/y outside footprint=0/0; report remains diagnostic-only and visual review is WAIT.

The bed worker binding schema is exactly `ds02.f5.c082s1.short-dynamic-bed-audit-binding.fresh109.v1`, matching both fresh109 candidate worker constants. The historical actual Root506 request used the runtime CPU `audit` task kind for the XMF producer; fresh109 keeps that allowlisted CPU kind in any disabled short request template.

`requests/*-full801-native-request.json` are 16 s, tout=.02, 801-frame, 3-D native solver templates with CPU threads=2 and Root230 live UUID/lease/foreign-process protection fields. They remain disabled because short-window visual report/receipt are WAIT/null. No full801, Q-N, or case credit is granted.

The exact DP lattice 1e-6 negative is retained as an independent numerical diagnostic. Short 0..1 s bed evidence and visual review do not certify the full 16 s runup event.
