# M4 additional physical-depth request templates

This subtree binds the two existing M4 definitions named by
`M4_PHYSICAL_DESIGN.json`:

| case | initial fill height | grid index at `dp=.01` | definition SHA256 |
| --- | ---: | ---: | --- |
| `UF_F1_MDBC_DP010_H052` | `.52 m` | `52` | `64beaa0020d4d4079a52e95260f374951065c5fceb9cde5ece2f4e0655b0c16b` |
| `UF_F1_MDBC_DP010_H058` | `.58 m` | `58` | `09f3cbffc1336855d2515ec83a1d673e8e9cc21a08bb42d611fc2e6839382b7c` |

`definition-verification.json` records a static XML comparison against the
official `CaseDamBreak3D_Def.xml`. Each child has exactly two differences:
the physical initial fill height and the separate `TimeOut=.025` sampling
interval. The comparison does not retime data and makes no experimental,
equivalence, threshold, or physical-condition credit claim.

The four files below are immutable, receipt-gated templates:

* `requests/UF_F1_MDBC_DP010_H052-gencase.template.json`
* `requests/UF_F1_MDBC_DP010_H052-solver.template.json`
* `requests/UF_F1_MDBC_DP010_H058-gencase.template.json`
* `requests/UF_F1_MDBC_DP010_H058-solver.template.json`

Both cases use the full `0..6 s` event window and `241` expected output
frames. Each solver template reserves exactly `9 GiB` (`9663676416` bytes).
The templates require immutable later-batch admission before GenCase or
solver submission. They also leave the actual GenCase receipt SHA256 and the
grid-aligned generated fluid-cohort SHA256 null until completed GenCase output
has been audited. A definition hash never substitutes for that generated
cohort hash. The solver templates bind runtime v2, runtime v6, `DsphConfig`,
the official mother, the M4 design, the static definition verification, the
fine-mother decision chain, the root-approved H050 postprocess request, and
the actual child definition. Future regular native solver files remain
receipt-bound and are not fabricated here.

The root-approved H050 postprocess request is an input reference only. After
the child postprocess completes, `m3/f1-fine-dp010-t025/comparison/
finalize_m3_requests_v1.py` must be run with a **fresh** `--candidate-dir`:
the existing immutable finalization report records its earlier pending state.
Do not overwrite consumed candidates or that report.

No GenCase or solver was launched for H052 or H058 while preparing these
files. Root must materialize any later request in the root request directory
only after all recorded gates and actual receipt bindings are satisfied.
