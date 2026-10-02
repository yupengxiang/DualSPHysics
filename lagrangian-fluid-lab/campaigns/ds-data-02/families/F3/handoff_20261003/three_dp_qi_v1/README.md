# F3 three-resolution Q-I handoff

This handoff registers the existing weak dual-axis F3 coarse, medium, and
fine trajectories for root review.  The producer is
`f3_three_dp_qi_registration_v1.py`; it reads the completed JSON/CSV evidence
and the independently registered trajectory SHA256 values from the macro
input audit.  It does not read or rehash the multi-GB H5 files and it does not
start a solver, converter, or labels job.

Run it with:

```text
python3 f3_three_dp_qi_registration_v1.py --output generated
```

The generated report and the three source contracts bind the physical case,
control, generated XML/BI4, RunPARTs ledger, direct conversion report, finite
surface replay, typed-label JSON, and the terminal solver receipt.  Each
RunPARTs ledger has 4001 numeric rows over 0–10 s, constant 3-D population
identity, and full-window sums of `NpOut`, `NpOutPos`, `NpOutRho`, and
`NpOutMov` equal to zero.  Native initial masses are retained from the direct
conversion reports; they are within the existing 1% initialization budget and
are not normalized.

The report deliberately leaves Q-N unassessed.  The finite-surface replay
observes x/y plane crossings while the older typed-label aggregate reports
zero x/y crossings, so the products are marked
`reconciliation_required` and are not combined.  The top-open surface has no
observed crossing and is right-censored.  The fine historical native-accounting
record is cross-bound to the coarse case and is retained as a negative binding
until a fine-specific sidecar is produced.  The existing medium temporal
diagnostic exceeds the 0.4% save/integration share cap on both observed chord
observables; residence-time budget registration is still absent.  The frozen
macro and event budgets are kept separate at 5% and 2%, respectively.

`generated/requests/*.bounded-audit-request.v1.json` are root-review-only
bounded JSON/CSV audit registrations (`runnable=false`, `launch_allowed=false`)
and must not be treated as solver or conversion requests.  The quarter-dt
follow-up remains separately deferred until its terminal conversion and label
artifacts exist.
