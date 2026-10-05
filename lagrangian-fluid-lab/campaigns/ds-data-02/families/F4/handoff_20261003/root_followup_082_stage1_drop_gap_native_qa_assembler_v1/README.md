# F4 fresh082: Root195 to Root196 native QA assembler

This package is a source-only correction/binding layer over the adopted F4 fresh081 scope (`ae0d8a25`). It does not mutate fresh081, rerun GenCase, copy BI4, decode arrays, or write shared registry/ledger state.

Root195 produced eight genuine per-case GenCase subprocesses with OS returncode 0. The aggregate runtime receipt is intentionally preserved as `status=failed`, `returncode=0`, `error="GenCase actual particle count missing"`: the v2 post-check expects one gencase prefix and cannot promote an aggregate job. `evidence/root195-gencase-evidence-binding.json` binds that parent receipt and the eight actual `gencase-receipt.json` files. The binder treats the per-case receipts and generated XML/producer BI4 hashes as the actual GenCase evidence; it never promotes the parent receipt to completed.

`requests/initial-native-qa-196.request.json` is the only runnable request in this package. It is correctly `kind=cpu`, `cpu_task_kind=audit`, has `estimated_storage_bytes`, remains disabled, and consumes two CPU threads. It points to Root196's future `initial-native-qa-index.json`; all future audit output hashes remain null. Root must supply that index after the native audit job reads the generated BI4. The assembler then validates, for all eight cases:

* genuine per-case OS0 receipt, source condition, XML path/hash and producer BI4 hash;
* dynamic XML `np/nb/fluid` partition, actual dp/time recipe, marker partition and explicit 3D evidence, without hard-coding the mother count 83233;
* native audit checks for legal domain, initial drop/pool non-overlap, marker/type partition, positive drop and pool sources, UID completeness, finite/nonfinite safety and true 3D.

The assembler writes a structured failure result and exits nonzero when Root196 evidence is missing or incomplete. A pass remains initial-input QA only; it grants no Q-N, precision, visual, or production status.

Root can execute after the native QA index exists with the strict dispatch entry point and the disabled request. No GenCase command is included in this package because Root195's actual bytes are retained and must not be duplicated.

Source bindings: plan `/home/jade/.codex/worktrees/ds-data-02-f4/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F4/handoff_20261003/root_followup_081_stage1_drop_gap_internal8_source_v1/source-plan.json`, Root195 member evidence `/home/jade/.codex/worktrees/ds-data-02-f4/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F4/handoff_20261003/root_followup_082_stage1_drop_gap_native_qa_assembler_v1/evidence/root195-gencase-evidence-binding.json`.
