# F3 Stage 1 concrete production authorization v3

This handoff is a source-only concrete package for the five prospective F3
first8 interiors.  It builds on the v2 authorizer in
`../root_followup_055_stage1_production_adapter_v2` and leaves 052, 054, and
055 unchanged.  It does not create an approval index, acquire a lease, call
the strict dispatcher, or launch GenCase, DualSPHysics, conversion, or
ParaView.

The package binds the actual current Root domain decision
`root_stage1_f3_first8_observed_domain_decision_042/root-visual-domain-decision.json`
(SHA-256 `7f33f48ddd33446a9f6684c673764727f1f01c1f6390b8d409facb9a91daea1e`)
and the current GPT-5.6 Luna goal (SHA-256
`53d422511b5581266410de92c54627ac67e8085eccb75a9ebfe57de10a34316a`).  The
Root record authorizes the explicit prospective membership
AY=.32/.39/.46/.57/.64 after observing AY=.25/.50/.75; it does not authorize
interpolation, Q-N, or numerical precision.

`F3_FIRST8_V3_CASE_MANIFEST.json` contains all eight domain rows and concrete
rows for the five prospective cases.  Each prospective row binds its strict012
prepared-input report, transformed native forcing CSV, cloned XML and BI4,
physics/geometry/motion evidence, mass discrepancy report, exact-initial-clone
metadata, frozen solver argv/cwd, and the post-run visual review contract.
The exact initial XML and BI4 hashes are respectively
`1162322010c42b9a084d76db0e20de571111cb009eb3afb699f2ee4c17d37406` and
`c9c3fb8315dad402f77dd015539be376c3df68f332f3ed6d03e6c174e4c57d80` for all
five rows.  The genuine parent GenCase receipt and native initial QA remain
the original records; the strict012 preparation receipt is a clone/input
preparation receipt and is never rebranded as a new GenCase receipt.

The frozen solver command for each case is the consumed native command shape
with only the prepared prefix and attempt output substituted:

```text
/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64
-mdbc_noslip:1 <prepared_prefix> {attempt_root}/solver_output -tmax:8.35 -tout:0.01
```

Its frozen cwd is
`/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab`.
The request templates retain `launch_allowed: false` and
`production_approval: "none"`; Root may construct the actual v2 index entry
and set its runtime launch policy only after the explicit adapter/index review.
The five prospective cases still require complete actual solver state,
typed/native identity, original saved frames, and a case-level Root visual
decision before any independent case count.

## Exact validation invariants

The validator enforces the following invariants before a Root review:

1. The manifest and domain contain exactly the explicit eight case IDs, with
   three observed records and five prospective records.  AY=.50 retains the
   original mother identity and count role.
2. Every prospective row has the exact SI transverse amplitude in m/s²,
   nominal pitch multiplier 1, condition hash, mechanism/control owner,
   unchanged F3 plain-tank geometry, gravity, event window `[0, 8.35]`,
   save interval `.01`, and 836-frame expectation.
3. Each row has distinct physical identity and condition provenance.  The
   request command, cwd, numerical recipe, and complete event window match the
   frozen manifest exactly; no unlisted amplitude or range interpolation is
   accepted.
4. The strict012 input report, forcing output, XML, BI4, and all five evidence
   sidecars hash successfully.  Each forcing sidecar binds the actual
   amplitude-specific forcing hash and the common source forcing hash.
5. The genuine parent receipt is successful actual 3D input evidence.  The
   parent native QA binds 179,208 total particles, 67,500 fluid particles,
   111,708 fixed particles, the original XML/BI4 bytes, and the 14.58 kg
   continuum/native-mass metadata.
6. The clone branch requires XML/BI4 byte equality, zero independent-case
   increment, the genuine parent GenCase receipt, the parent initial QA, and
   the strict012 clone-preparation receipt.  The historical endpoint clone
   receipt 006 is retained as provenance and is not used as a fabricated new
   GenCase receipt.
7. Native and continuum mass remain explicit (`14.580000000000002` kg and
   `14.58` kg as reported), with `mass_rescaling: false` and no precision gate.
   Unknown post-run loss remains an observation for the later actual run.
8. Physics, geometry, motion, and initial no-overlap/finite-state evidence are
   explicit JSON sidecars.  The no-overlap sidecar is an initial metadata/QA
   binding and states that a full post-run state check is still required; it
   does not assert post-run particle retention.
9. The actual Root lower/mother/upper decisions and full saved-frame reports
   are content validated through v2.  All 836 frames, exact saved times,
   native identity, zero missing states, and zero nonfinite active states are
   checked.  Unknown-loss observations are preserved.
10. The current goal, Root domain decision, v2 adapter/authorizer, consumed
    strict/runtime source bytes, and native solver binary are hash-bound.  The
    mutable preflight fixture index is excluded from each request's immutable
    input hash map.
11. The v3 package carries `production_scope_approval: false`,
    `numerical_precision_status: "not_accepted"`, `q_n: "not_granted"`, and
    `q_e: "not_assessed"` throughout.  No case visual decision is supplied
    for a prospective case before its actual run.

## Source-only checks

From the infra worktree:

```text
python3 build_f3_v3_package.py
python3 build_f3_v3_templates.py
python3 validate_f3_v3_package.py
```

The final command first verifies all metadata and path hashes, then calls the
v2 `authorize()` function once for each of the five requests against the real
visual decisions and strict012 evidence.  Its output is explicitly
`preflight_authorize_passed_actual_evidence` with `fixture_only: true` and
`execution_allowed: false`; it is not a production grant and does not invoke
the dispatch adapter.  Use `--skip-authorize` for the fast metadata-only
check.

The generated request JSON files under `requests/` are the concrete inputs
Root can review and then route through the already-reviewed v2 adapter after
Root creates the real, selected scope index entry.  Future typed/ParaView
outputs and case visual decisions must be appended after each actual complete
run; they are intentionally absent from this prospective package.

`f3_v3_postrun_qa_worker_disabled.py` is a bounded checklist for those future
outputs.  It is hard-disabled (`ENABLED = false`), reads only the manifest,
does not inspect raw particle arrays or start a process, and never creates an
approval.  The included `test_f3_v3_package.py` exercises the metadata/hash
gate, one actual-evidence v2 `AUTHORIZE()` preflight, request launch flags,
and this disabled boundary.
