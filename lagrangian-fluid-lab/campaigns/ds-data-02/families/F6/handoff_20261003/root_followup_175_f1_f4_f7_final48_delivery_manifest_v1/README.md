# F6-owned F1/F4/F7 final-48 delivery roster

This package is a read-only delivery index owned by the F6 handoff. It
describes the already accepted physical cases in families F1, F4 and F7;
`source_assignment_family` is `F6` while each case keeps its own physical
family, case ID, accepted decision, producer chain and scope roles. It does
not add acceptance, case credit, a checkpoint entry or a new computation.

The roster contains 48 cases for each family. The membership order is taken
from checkpoint 218 accepted decisions. The first 24 order is taken from
Root1232 for F1/F7 and Root1238 for F4. The first 8 is cross-checked against
the frozen Root1093 list, giving an explicit strict relation `8 < 24 < 48`
for every family. The checkpoint and membership authorities are recorded in
the roster with their current metadata SHA-256 values.

`role_aware_native_registration` is a separate role copied from the matching
Root1258 metadata row. Its `accepted_decision_top_condition_sha256` is kept
with the declared role text, and `native_request_scope` is kept independently.
A missing native scope remains missing. The accepted semantic declaration is
never used to manufacture an actual native scope or receipt. Original/direct
receipts, actual/recovery evidence, and nonterminal/nonzero records remain in
separate `receipt_roles` lists; an original receipt is never rewritten as a
successful recovery result.

Each case has metadata references for native, typed, XMF (`case.xmf` and its
`manifest.json`), render report/receipt, QA, GenCase/owner evidence, and PNG
contact/key entries. The builder hashes only JSON, XML, XMF and already
published PNG files. H5, BI4, CSV, DAT, VTK and related scientific payloads
are excluded before any read. No PNG was opened for a new visual review here;
the existing accepted visual decisions are referenced. The delivery label is
`视觉检查通过、数值精度未验收`; `q_n`, `q_e`, `case_credit`, and
`new_acceptance` remain false/zero.

Run the metadata-only validator from the F6 worktree:

```text
python3 /home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003/root_followup_175_f1_f4_f7_final48_delivery_manifest_v1/validate_final48_delivery.py
```

For a full current SHA check of the referenced JSON/XML/XMF/PNG files, use:

```text
python3 /home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003/root_followup_175_f1_f4_f7_final48_delivery_manifest_v1/validate_final48_delivery.py --rehash
```

Both modes are read-only. They require checkpoint 218, the Root1093/1232/1238
membership authorities and the Root1258 role-aware index to remain unchanged;
they do not read scientific arrays or update shared state.
