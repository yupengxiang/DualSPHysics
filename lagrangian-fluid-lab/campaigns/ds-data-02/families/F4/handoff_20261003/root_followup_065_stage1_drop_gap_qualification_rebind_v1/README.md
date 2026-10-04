# F4 Root 065 qualification-input rebind

This source-only package prepares the two physical F4 drop-gap endpoints for
full native qualification after the completed Root 069 actual-native QA:

* `F4_DROP_ENDPOINT_GAP0p18000_DP010` (`gap_m=0.18`)
* `F4_DROP_ENDPOINT_GAP0p26000_DP010` (`gap_m=0.26`)

The 069 index and its hash are fixed in `source-binding.json`. The builder
reads that index, verifies the endpoint reports have `true_3d` and
`gencase_completed`, parses the actual `execution/particles` counts from each
069 generated XML, and checks that the XML/BI4 bytes and hashes match the
source 063 individual GenCase outputs. It also checks the 063 genuine
individual command rows and return code `0`.

The 063 shared `execution-receipt.json` remains a required failed input with
`error="GenCase actual particle count missing"`. The builder never writes in
the 063 or 069 scopes. Its new per-endpoint receipt contains
`returncode=0`, `gencase_returncode=0`, `total_particles=83233`,
`fluid_particles=59072`, and `solver_dimension_from_gencase=3` so the runtime
validator can bind a qualification request. Those fields are explicitly
carried from the genuine 063 individual command and the generated XML/069 QA;
the receipt says `builder_ran_gencase=false` and
`derived_is_new_gencase_process=false`. The original shared failure is never
promoted to completed.

The mother qualification recipe is read from the completed centered DP010
XML/receipt. Both disabled endpoint request files inherit:

* solver `DualSPHysics5.4_linux64`, `-tmax:1.2`, and `-tout:0.001`;
* the complete 1.2 s window at 0.001 s output cadence (1201 frames);
* DBC/no-slip controls (`ViscoTreatment=1`, `Visco=0.08`,
  `ViscoBoundFactor=1`);
* baseline CFL/DT controls (`cflnumber=0.2`, `CoefDtMin=0.05`, adaptive
  `DtIni=DtMin=DtFixed=DtAllParticles=0`), Verlet, Wendland, and density-DT
  settings from the mother XML.

Only the endpoint native prefix and the new solver output path vary. The
requests remain `launch=false`, `launch_allowed=false`, and
`launch_owner="root"`; this package does not submit a solver job or create a
qualification output.

## Root generation sequence

After reviewing the existing 069 index and its hashes, Root can build a fresh
preparation scope (the output directory must not already exist):

```text
/home/jade/.codex/worktrees/ds-data-02-f4/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python \
  /home/jade/.codex/worktrees/ds-data-02-f4/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F4/handoff_20261003/root_followup_065_stage1_drop_gap_qualification_rebind_v1/workers/build_f4_gap_qualification_bindings_v1.py \
  --plan /home/jade/.codex/worktrees/ds-data-02-f4/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F4/handoff_20261003/root_followup_060_stage1_drop_gap_endpoints_v1/endpoint-plan.json \
  --actual-qa-index /home/jade/Projects/DualSPHysics-data/ds-data-02/families/F4/F4_DROP_GAP_ENDPOINTS/root-stage1-f4-gap0180-0260-actual-native-initial-qa-069/initial-qa/initial-native-audit-index.json \
  --actual-qa-index-sha256 a6fbe94141a3274ea80b6fdea01ea41a95541c9f5c3c4775f850e2b49c44ffc0 \
  --gencase-result /home/jade/Projects/DualSPHysics-data/ds-data-02/families/F4/F4_DROP_GAP_ENDPOINTS/root-stage1-f4-gap0180-0260-genuine-gencase-063/gencase-preflight-result.json \
  --original-execution-receipt /home/jade/Projects/DualSPHysics-data/ds-data-02/families/F4/F4_DROP_GAP_ENDPOINTS/root-stage1-f4-gap0180-0260-genuine-gencase-063/execution-receipt.json \
  --metadata-root /home/jade/.codex/worktrees/ds-data-02-f4/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F4/handoff_20261003/root_followup_062_stage1_drop_gap_request_readiness_v1/metadata \
  --mother-xml /home/jade/Projects/DualSPHysics-data/ds-data-02/families/F4/F4_DROP_CENTERED_REFERENCE_001_DP010/gencase-centered-reference-002/F4_DROP_CENTERED_REFERENCE_001_DP010.xml \
  --mother-qualification-receipt /home/jade/Projects/DualSPHysics-data/ds-data-02/families/F4/F4_DROP_CENTERED_REFERENCE_001_DP010/qualification-centered-fullwindow-001/execution-receipt.json \
  --output-root /home/jade/Projects/DualSPHysics-data/ds-data-02/families/F4/F4_DROP_GAP_ENDPOINTS/root-stage1-f4-gap0180-0260-qualification-inputs-065
```

The builder writes `qualification-input-binding-index.json`,
`solver-recipe-binding.json`, `original-063-failure-binding.json`, exact-byte
per-endpoint `derived-gencase/<endpoint>.xml/.bi4`, runtime-compatible
`derived-gencase/execution-receipt.json`, and two disabled request files under
`requests/`. Root should inspect the index and request hashes, then perform
the normal strict review/owner action before enabling either request. The
builder itself has no solver launch path.

No Q-N, precision, visual, or production claim follows from this package.
