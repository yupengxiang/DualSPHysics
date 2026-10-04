# F1 fresh064 initial-vx source handoff

This package prepares 16 prospective F1 cases: each completed first-eight head
geometry is paired with a uniform Type 3/Mk 0 fluid initial velocity of `vx=0.1`
or `0.2 m/s`, with `vy=vz=0`. The only XML change is the official direct
`<initials><velocity mkfluid="0" ... /></initials>` element. Geometry, DP,
solver options, and full native windows are copied from the parent source and
native032 receipt.

The first-eight audit records actual completed GenCase metadata and canonical
physical IDs without opening BI4 arrays. All new definitions, owner bindings,
GenCase/initial-QA/native requests, and the vx-aware QA worker are source-only
and disabled. Root must run genuine GenCase, the read-only initial QA, the
exact native032 solver recipe, and full visual review before accepting this
axis. No case count, Q-N status, production approval, shared index, or ledger
entry is asserted here.
