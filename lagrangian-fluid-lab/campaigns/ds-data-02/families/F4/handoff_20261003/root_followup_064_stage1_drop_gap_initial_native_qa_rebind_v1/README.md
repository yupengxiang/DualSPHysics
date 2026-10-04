# F4 Root 064 initial-native QA rebind

This source-only handoff repairs the evidence binding for the fresh initial
native QA of the two physical F4 drop-gap endpoints:

- `F4_DROP_ENDPOINT_GAP0p18000_DP010` (`gap_m=0.18`)
- `F4_DROP_ENDPOINT_GAP0p26000_DP010` (`gap_m=0.26`)

The completed 063 strict attempt contains successful individual GenCase
commands, the exact all-numeric endpoint XML files, and the exact native BI4
files. Its shared `execution-receipt.json` is intentionally retained as
`status=failed` with `error=GenCase actual particle count missing`: the shared
runner captured stdout and did not bind the count. This scope does not repair,
rewrite, or relabel that receipt.

The disabled 064 QA worker binds both the 063 `gencase-preflight-result.json`
and the original failed shared receipt. It checks that endpoint IDs and
physical-condition digests are unchanged, derives actual total/fixed/fluid and
per-source counts from each generated XML, and verifies the completed metadata
source counts. For each endpoint it then copies the exact XML and BI4 bytes to
the fresh QA output under:

```text
{attempt_root}/initial-qa/<endpoint>/derived-gencase/<endpoint>.xml
{attempt_root}/initial-qa/<endpoint>/derived-gencase/<endpoint>.bi4
{attempt_root}/initial-qa/<endpoint>/derived-gencase/execution-receipt.json
```

The staged receipt is a derived per-endpoint evidence receipt with
`status=completed`, which is the status required by the consumed F4 native
audit helper when it checks the prefix parent. It explicitly records the
original 063 receipt as failed and keeps its path and hash. This status must
not be read as promotion of the shared 063 receipt.

The consumed audit is invoked only after staging, using the staged prefix.
The worker never runs GenCase, decodes BI4 itself, reads H5 or particle
arrays, generates CSV, converts, solves, or renders. `launch=false` and
`launch_allowed=false` remain frozen in the request. The request is ready for
Root strict review and launch; this handoff itself creates no generated or
native output.

The existing 060 endpoint plan and 062 completed metadata remain the source of
the physical IDs, gaps, definitions, and expected counts. No endpoint is
added, removed, or renumbered. Precision remains `not_accepted`, `q_n` remains
`not_assessed`, and production/solver/visual acceptance remain outside this
input-integrity QA scope.
