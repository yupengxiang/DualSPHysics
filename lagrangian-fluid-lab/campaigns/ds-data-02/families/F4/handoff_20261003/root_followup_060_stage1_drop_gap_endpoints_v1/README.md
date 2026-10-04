# F4 narrow DROP gap endpoints — source-only handoff

This scope freezes exactly two prospective physical endpoints from the DROP
initial-height/gap axis in source handoff 053:

- `F4_DROP_ENDPOINT_GAP0p18000_DP010`, drop point z literal
  `0.38500000000000004`;
- `F4_DROP_ENDPOINT_GAP0p26000_DP010`, drop point z literal
  `0.46500000000000004`.

Both use the known `F4_DROP_CENTERED_REFERENCE_001_DP010` mother. The builder
copies the mother Definition bytes and replaces the one `mk=1` drop point z
attribute. It verifies that every other byte is unchanged and writes only the
two source Definition XML files plus a source receipt. The mother’s exact
all-numeric generated XML is retained as a read-only anchor; endpoint generated
XML does not exist until Root runs fresh GenCase.

The numerical recipe is fixed at `dp=0.01 m`, `TimeMax=1.2 s`, `TimeOut=0.001
s`, and the mother’s 1201-frame native window. Pool/drop sizes, x/y positions,
drop velocity `[0, 0, -0.5]`, tank/wall geometry, material, constants, and
integrator remain bound to the mother. Native support weights follow
`rho*dp^3`; no continuum rescale is permitted.

Two disabled Root-strict requests are included:

1. `requests/f4_drop_gap_gencase_preflight_request.json` binds the actual
   GenCase worker. It remains `launch=false`; Root must review the source
   definitions and explicitly launch any fresh CPU preflight.
2. `requests/f4_drop_gap_initial_native_qa_request.json` binds the generated
   all-numeric XML and a Root-produced initial QA JSON. It does not read BI4,
   H5, particle arrays, or CSV in this scope. Its UID/type/support-weight/
   clearance checks are downstream of fresh GenCase and are not available yet.

The source plan does not add independent-case credit, perform solver or
conversion work, or make a precision, q_n, containment, or visual acceptance
claim. Root’s current mother-review note describes coherent drop/impact/wave
behavior through review page/frame 029 at about 0.72 s; that note is retained
as a review pointer and does not substitute for whole-frame review of either
new endpoint. Historical F4 spatial non-convergence, the old precision
failure, particle-chord timing uncertainty, unassessed q_n, pending visual
decision, and the separately audited recovered artifact with unknown original
OS remain active.
