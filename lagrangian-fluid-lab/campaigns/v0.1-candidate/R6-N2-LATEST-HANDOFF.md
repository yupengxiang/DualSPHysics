# R6 N2 latest handoff

Date: 2026-09-08
Scope: full-time `plain_dam_break` re-audit, registered `0.9H0`/`1.1H0` endpoint runs, and plain-control material semantics.

## Decision

`formal_v0.1 = NO_GO` remains invariant.  The T1 result is a numerical SPH
reference-recipe decision only; it is not an external continuous-fluid truth
claim.  Development authorization is limited to the explicit recipe recorded
in `r6-n2-n2-campaign.json` and is false unless the machine-readable gate says
otherwise.

| height label | height (m) | decision | coarse-medium max TV | medium-fine max TV |
|---|---:|---|---:|---:|
| `h09` | `0.414` | `blocked_t1_height_candidate` | `0.04958994708994707` | `0.03533584098100226` |
| `h10` | `0.46` | `qualified_t1_height_candidate` | `0.04738095238095241` | `0.04733893557422966` |
| `h11` | `0.506` | `blocked_t1_height_candidate` | `0.06006060606060604` | `0.05504385964912284` |

Qualified height labels: `['h10']`
Qualified range: `[0.46, 0.46]`
T1 recipe status: `candidate_only_or_blocked`
Development authorized: `False`
Development tranche: `not_started`

## T2 material reference

Status: `completed`; acceptance:
`candidate_t2_numerical_reference_only`; formal
material admission: `false`.

The plain-control run uses one continuous source support envelope
`[0.03, 0.52] m` across medium/fine, with nominal geometry
range `[0.04, 0.50] m` retained separately.  First passage and final category
are separate fields; failure after an earlier arrival is not relabelled as a
negative first-passage result.  The material configuration count is
`6` and all
cross-configuration comparisons remain diagnostic, not acceptance gates.
The plain-control neighbour query used an optional CPU-only exact top-k
accelerator; no CUDA/GPU was used, and the full finite-wall collision check
remained active.

## G4 and external scope

G4 training status: `deferred_t1_not_authorized`;
no G4 model ranking or development tranche was launched from this round.
External/reference validation: `not_run`.

## Semantics and scope

- The audit uses 21 fixed requested physical times over 0--1.5 s and records
  the actual nearest saved frame.
- It compares mass distribution, mass-weighted centre of mass, front q50/q90/q99,
  and a kinetic-energy proxy across the complete time window.
- The initial fluid source layers use declared continuous z bounds, not per-run
  discrete particle extrema.  The latter are retained only as diagnostics.
- The material task separates first passage from final destination.  A tracer
  that reaches the target and later fails has an observed first passage but an
  unknown final category.
- F6 received no new solver call.  Center/twin forensic evidence is bounded and
  does not block the plain control.

## Machine artefacts

- T1 report: `r6-n2-n2-campaign.json`
- Material report: `r6-f1-material-task.json`
- This handoff: `R6-N2-LATEST-HANDOFF.md`

Open blockers: ["T1 remains a numerical-reference candidate at one height only; development authorization is false", "T2 plain-control material reference completed, but external/reference anchors are absent", "material support-gate failures and tracer_unknown mass remain candidate-only findings", "center/twin missing identities remain a separate forensic branch", "formal v0.1 and hidden test release remain unauthorized"]
