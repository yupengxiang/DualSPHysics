# F4 060 strict request readiness — source-only successor 062

This scope reviews the disabled requests in
`root_followup_060_stage1_drop_gap_endpoints_v1` and carries only the exact
request fixes needed for a fresh Root strict attempt. The two physical
endpoints remain the 060 source Definitions:

- `F4_DROP_ENDPOINT_GAP0p18000_DP010`
- `F4_DROP_ENDPOINT_GAP0p26000_DP010`

The 060 GenCase request had a `cpu_task_kind` outside the runtime allowlist
and its worker tried to create
`{attempt_root}/gencase/<endpoint>` before `{attempt_root}/gencase` existed.
The successor uses the approved `gencase` CPU kind and creates that nested
root before launching. Its command still contains the explicit `--execute`
switch, but the request remains `launch=false` and `launch_allowed=false` in
this source handoff.

The 060 QA request had the same runtime-kind problem and required a
`generated-inputs.json` that no preceding worker produced. The successor uses
the approved `audit` CPU kind and binds the actual names emitted by the
GenCase worker:

```text
{attempt_root}/gencase/<endpoint>/<endpoint>.xml
{attempt_root}/gencase/<endpoint>/<endpoint>.bi4
{attempt_root}/gencase/<endpoint>/execution-receipt.json
```

After Root strict GenCase, the QA worker invokes the consumed F4 native audit
script for each endpoint and writes:

```text
{attempt_root}/initial-qa/<endpoint>/native-preflight-audit.json
{attempt_root}/initial-qa/initial-native-audit-index.json
```

The QA request records the preceding GenCase attempt's concrete data-root
path in `runtime_preconditions`; it does not incorrectly point at the QA
attempt's own `{attempt_root}` for upstream generated inputs. Root must launch
the GenCase request first, retain its successful output root, and then launch
the QA request with that recorded path.

The audit therefore checks the actual all-numeric GenCase XML and native BI4
through the existing read-only F4 audit path: complete unique native UIDs,
the fixed/fluid type partition, native support weights, finite 3-D fluid
positions, source population checks, and tank face coverage. The successor
also requires positive `drop` and `pool` source rows with finite, vertically
separated bounds. `pool` is the source label for the bath. Physical mass
continues to be `rho*dp^3`; native support weights remain authoritative and
no continuum rescale is introduced.

This handoff does not run GenCase, open BI4/H5, read particle arrays, convert,
solve, render, or claim numerical/visual acceptance. Root must run the two
disabled requests in order after reviewing the source plan. Historical F4
spatial non-convergence, the old precision failure, particle-chord timing
uncertainty, unassessed `q_n`, pending whole-frame visual review, and the
recovered approximately 147 GB artifact with unknown original OS remain
separate active evidence.
