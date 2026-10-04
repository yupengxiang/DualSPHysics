# F5 062 receipt and initial-QA scope sidecar

This sidecar is a fresh source audit for the already-consumed 061 Candidate-A
chain. It does not edit 061, launch GenCase, launch PartVTK, read BI4/H5/CSV
arrays, or make a numerical result claim. Its purpose is to keep the Root
execution decision tied to the actual unmodified runtime and to record the
scope mismatch in the existing generic F5 initial-QA helper.

The unmodified runtime can produce the required new receipt fields. The
`gencase.py` wrapper inherits official GenCase stdout, while
`ds_data02_runtime_v2.py` parses `Total particles`, `Fluid...`, and `Data2D`
from that stdout and writes `total_particles`, `fluid_particles`, and
`solver_dimension_from_gencase` into `execution-receipt.json`. Its solver
guard then requires completed status, return code zero, positive actual total
and fluid counts, and dimension 3. A prior F5 wrapper receipt (Root048) is
metadata-only corroboration of this path; it is not evidence for A061.

The existing `ds_data02_f5_initial_mass_qa_v2.py` does check the fresh receipt,
actual 3-D, manifest fluid count, finite native rows, consecutive unique
`Idp`, typed XML block/type/mk consistency, positive row mass/density, zero
initial velocity, and fluid mass against the manifest. It does not check
bed-surface coverage or spatial no-overlap between fixed, moving, and fluid
coordinates. Its imported generic PartVTK audit also hard-codes a different
commensurate fluid box and continuum mass and requires an STL marker. Those
contracts do not describe A061's explicit closed-mesh source, so this helper
must not be treated as an A061 pass until Root uses an A061-specific evaluator
or explicitly records a fresh adapter.

The 057 mk40 evidence is consequently limited to bounded selected-point and
mid-layer indicators. The mk40 cohort contains mixed boundary geometry,
including walls; nonzero counts in profile x segments do not establish a
continuous solid slope bed. The bed-completeness and no-overlap hypotheses
remain open for the fresh A061 QA.
