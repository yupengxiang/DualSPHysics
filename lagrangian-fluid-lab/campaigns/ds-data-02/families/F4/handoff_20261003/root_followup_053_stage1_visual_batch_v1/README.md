# F4 stage1 visual batch 8 source handoff

This handoff defines eight independent F4 physical cases for later root controlled
generation and visual review. It is a source plan only. The disabled request invokes
the bounded definition builder, which writes JSON source specifications and does not
run GenCase, DualSPHysics, conversion, ParaView, or any storage producing binary or
particle arrays.

The two existing centered mothers are retained exactly as source anchors:

- `F4_DROP_CENTERED_REFERENCE_001_DP010`, 1201 native frames over `[0, 1.2] s`.
- `F4_COL_CENTERED_REFERENCE_001_DP010`, the existing centered oblique finite-column
  source with a successful GenCase/native/conversion receipt chain.

The generated source XML for the drop anchor reports `dp="0.01"`; the family
coarse label is retained as a label and is not rewritten into a resolution claim.
Rows vary one physical initial condition at a time. They retain the numerical recipe,
material model, tank, particle spacing, and save window of their selected mother.
The intended parameter changes still require fresh root GenCase and initial QA, so no
byte equality or overlap clearance is claimed here.

Historical negative evidence remains active. F4 spatial and timing non-convergence,
the old precision failure, unresolved `q_n`, and visual acceptance pending are carried
forward. The separately recovered approximately 147 GB artifact is recorded as an
original-OS-unknown audit reference; it is not used as evidence for these source rows.

The batch is not an independent-case increment until root reviews and launches it.
