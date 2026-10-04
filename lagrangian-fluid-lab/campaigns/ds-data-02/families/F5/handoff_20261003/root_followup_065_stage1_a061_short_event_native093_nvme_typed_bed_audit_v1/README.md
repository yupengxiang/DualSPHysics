# F5 A061 fresh065: actual093 short native products and bed audit

This is an isolated F5 source handoff. It prepares the owner metadata, the
existing NVMe direct-conversion wrapper, the existing temporal XMF publisher,
and the fresh064 framewise bed-footprint worker for Root execution. It does not
start DualSPHysics, GenCase, PartVTK, a converter, or an array reader.

The physical source is still the source061 Candidate A chain:

- candidate A removes only the duplicate STL invocation and retains the
  explicit 52-triangle closed mesh, clip plane, fluid fill, forcing, and solver
  controls;
- genuine GenCase 075 is completed with `214385` total particles, `40710`
  fluid particles, and dimension 3;
- actual initial QA 083 passed all fourteen checks. Its native fluid mass is
  `325.680016284 kg` versus continuum `325.714285714 kg`; no rescaling was
  performed;
- actual short solver 093 is completed with the genuine 075 prefix, `-tmax:1.0`
  and `-tout:0.02`, and has exactly 51 native `Part_0000.bi4` through
  `Part_0050.bi4` frames;
- the short event is right-censored diagnostic evidence. It does not increment
  the independent case count, grant Q-N, authorize a full 16-second run, or
  establish repair success.

The immutable actual093 source is
`/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_A061/root-stage1-f5-explicit-bed-repair-a-short-event-native-093`.
The Root integration handoff is
`/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f5_repair_a_actual_short_event_native_093`.

The intended Root sequence is:

1. Review and enable `nvme-conversion-request.json`. It uses
   `ds_data02_nvme_convert_v1.py` around the unchanged direct converter, with
   output attempt
   `root-stage1-f5-explicit-bed-repair-a-short-event-native-typed-nvme-065`.
   It must publish `trajectory.h5` and `conversion-report.json` with 51 frames,
   214385 particles, a 3-D evidence block, native identity/type/mk/weight
   provenance, and the unrescaled mass comparison.
2. Run the helper in `scripts/bind_completed_products.py` in `xmf` mode. It
   reads only the conversion report, receipt JSON, and byte hashes of the H5;
   it does not decode H5 arrays. It writes bound XMF metadata and a disabled
   `xmf-request.json` into the requested output directory.
3. Review and enable the bound XMF request. The copied exporter writes
   `case.xmf`, `manifest.json`, and a temporal 51-frame sidecar under the fresh
   `native-xmf-065` attempt. The H5 is referenced by absolute path and remains
   unchanged.
4. Run the helper in `bed` mode. It checks conversion metadata, hashes H5 and
   XMF, and checks the XMF textual time axis `0..1 s` at `0.02 s`; it does not
   open H5 datasets. It writes a bound bed-audit binding and disabled request.
5. Review and enable the bound bed-audit request. `workers/bed_audit.py` then
   scans all 51 saved frames read-only and reports, for every frame, finite
   Type-3 rows only inside the exact source x profile and y `[-0.15,0.15] m`,
   below-1DP and below-2DP counts and fractions, deepest depth and samples,
   nonfinite positions, and missing/extra/unexplained initial UIDs. The complete
   frame-zero Type-3 UID set remains the reference denominator.

Example binding commands after Root has completed the preceding artifact:

```text
/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python \
  /home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_065_stage1_a061_short_event_native093_nvme_typed_bed_audit_v1/scripts/bind_completed_products.py \
  --mode xmf --output-dir /home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_065_stage1_a061_short_event_native093_nvme_typed_bed_audit_v1/bound

/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python \
  /home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_065_stage1_a061_short_event_native093_nvme_typed_bed_audit_v1/scripts/bind_completed_products.py \
  --mode bed --output-dir /home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_065_stage1_a061_short_event_native093_nvme_typed_bed_audit_v1/bound
```

The source campaign declares condition hash
`268d4ea37228fb63ef493a6e535740bb765d165d874f97804443d5e11eb3497c`. The
converter recomputes its physical scope from the explicit `physical_binding.v1`
inside `owner-metadata.json`; the helper records that observed report hash and
writes `physical_condition_hash_match` alongside the declared hash. This is a
provenance check, not a permission to rewrite the source condition or to claim
that the two hashes agree. Root must review a false match before using the
products for any stronger claim.

The source-side worker checks are intentionally bounded. The copied bed worker
has a `--check` synthetic API check that reads no native data. A real worker
run, converter run, and XMF run remain Root-owned execution steps.
