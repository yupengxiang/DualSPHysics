# F4 Root216 metadata-contract repair

Fresh085 remains an immutable disabled source package. Its actual Root212 run
failed before scientific array access with `KeyError: 'generated_bi4'`: the
fresh085 internal Root195-row adapter kept producer outputs nested under
`row`, while later receipt/report assembly addressed `generated_bi4` at the
flattened level. This package does not rerun Root212.

Fresh086 supplies the disabled Root216 replacement worker. It flattens only
the immutable producer references needed by those four consumer accesses and
adds the exact canonical owner `physical_binding`, including
`geometry.tank`, to every derived metadata file. Before any native decoder
stage, the wrapper validates all eight metadata paths: physical identity and
binding hash, `source_regions`, XML-derived per-source counts, `dp_m`,
continuum mass derivation, definition/XML/GenCase receipt hashes, and the
source read boundary. Its `--metadata-preflight` mode runs all eight adapter
contracts against JSON/XML in a temporary directory and does not open BI4.

The normal Root216 request stays disabled and uses the same physical Root195
inputs, raw `Posd`/`Idp` audit contract, and XML/UID-derived marker partition.
Root212's failed receipt is preserved as historical evidence. No solver,
converter, array read, shared ledger, or registry write occurs in source
preparation.

Root216 was later executed on the integration host. Its receipt is preserved
with `returncode=1` and all eight scientific `all_source_population_checks`
false; it is not promoted as QA and it does not authorize Root200. If a
future reviewed replacement ever produces a real completed0/pass index and
binding, Root can enable the existing fresh084 Root200 binder with:

```text
python3 /home/jade/.codex/worktrees/ds-data-02-f4/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F4/handoff_20261003/root_followup_084_stage1_drop_gap_full1201_qualification_binder_v1/workers/build_f4_root200_native_qualification_bindings_v1.py \
  --out-dir /home/jade/.codex/worktrees/ds-data-02-f4/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F4/handoff_20261003/root_followup_084_stage1_drop_gap_full1201_qualification_binder_v1/requests \
  --qa-index /home/jade/Projects/DualSPHysics-data/ds-data-02/families/F4/F4_INTERNAL_GAP8_DP010_INITIAL_QA/root-stage1-f4-internal8-native-initial-qa-metadata-contract-repair-216/initial-native-qa-index.json \
  --qa-binding /home/jade/Projects/DualSPHysics-data/ds-data-02/families/F4/F4_INTERNAL_GAP8_DP010_INITIAL_QA/root-stage1-f4-internal8-native-initial-qa-metadata-contract-repair-216/initial-native-qa-binding.json \
  --qa-receipt /home/jade/Projects/DualSPHysics-data/ds-data-02/families/F4/F4_INTERNAL_GAP8_DP010_INITIAL_QA/root-stage1-f4-internal8-native-initial-qa-metadata-contract-repair-216/execution-receipt.json
```

The builder accepts this Root216 attempt and records the actual hashes; until
then all Root200 solver requests remain disabled.
