# fresh166: F3 remaining-nine pipeline census

This is a source-only, metadata-only census of the nine F3 rows selected from the frozen Root1284 index by `family_id == F3` and no `accepted_decision`. It does not grant case credit, visual credit, Q-N, Q-E, or production approval.

The builder read JSON metadata, XML/XMF path metadata, and `/proc` controller identity only. It did not open or hash H5, BI4, CSV, DAT, VTK, VTP, VTU, PVTU, or raw scientific payloads; it did not start, stop, restart, or mutate a job, ledger, registry, guard, receipt, or live input.

## Snapshot

- Observed UTC: `2026-10-07T02:53:32.070713+00:00`.
- Selected: **9** F3 rows; native completed/0: **9**; standard typed completed/0: **8**; AY0270 independent artifact audit completed/0: **1**; XMF completed/0: **9**.
- Render terminal/published at snapshot: **0**; exact controller PID/start-tick handles still live: **9**.
- Therefore all nine are upstream-ready for the already registered render consumers, while all nine remain visually unresolved at this snapshot.

## Per-case closure

| case | pitch | AY (m/s²) | native | typed / audit role | XMF | frames × particles / N3 | time end (s) | render handle | source-plan role |
|---|---:|---:|---|---|---|---|---:|---|---|
| `F3_STAGE1_DP006_P0800_AY0360` | 0.8 | 0.36 | completed/0 | typed 0 | completed/0 | 836 × 179208 / dim 3 | 8.35001341871951 | PID 4154594 / ticks 208492792 / S | key absent |
| `F3_STAGE1_DP006_P0800_AY0500` | 0.8 | 0.5 | completed/0 | typed 0 | completed/0 | 836 × 179208 / dim 3 | 8.350012599876457 | PID 104437 / ticks 209376424 / S | key absent |
| `F3_STAGE1_DP006_P0800_AY0570` | 0.8 | 0.57 | completed/0 | typed 0 | completed/0 | 836 × 179208 / dim 3 | 8.350005258058488 | PID 104443 / ticks 209376437 / S | key absent |
| `F3_STAGE1_DP006_P1000_AY0270` | 1.0 | 0.27 | completed/0 | old typed154 running / returncode absent; audit1166 0 | completed/0 | 836 × 179208 / dim 3 | 8.3500164870623 | PID 289746 / ticks 210642457 / S | key absent |
| `F3_STAGE1_DP006_P1200_AY0390` | 1.2 | 0.39 | completed/0 | typed 0 | completed/0 | 836 × 179208 / dim 3 | 8.350008849684302 | PID 202633 / ticks 210026020 / S | key present, distinct/nonmatching |
| `F3_STAGE1_DP006_P1200_AY0430` | 1.2 | 0.43 | completed/0 | typed 0 | completed/0 | 836 × 179208 / dim 3 | 8.350010348037522 | PID 202910 / ticks 210026642 / S | key present, distinct/nonmatching |
| `F3_STAGE1_DP006_P1200_AY0540` | 1.2 | 0.54 | completed/0 | typed 0 | completed/0 | 836 × 179208 / dim 3 | 8.350014835784549 | PID 239500 / ticks 210261151 / S | key present = source-condition SHA |
| `F3_STAGE1_DP006_P1200_AY0570` | 1.2 | 0.57 | completed/0 | typed 0 | completed/0 | 836 × 179208 / dim 3 | 8.350016793948717 | PID 242459 / ticks 210276801 / S | key present = source-condition SHA |
| `F3_STAGE1_DP006_P1200_AY0640` | 1.2 | 0.64 | completed/0 | typed 0 | completed/0 | 836 × 179208 / dim 3 | 8.350000843360164 | PID 250781 / ticks 210329564 / S | key present = source-condition SHA |

## Evidence boundaries and unresolved items

- The eight P0800/P1200 rows use the genuine parent initial QA (Root058 role) and Source704 prepared owner/condition/request plus each row’s own forcing/control metadata. That reused parent QA is not relabeled as a new independent QA.
- The AY0270 old request has no `physical_binding.v1` schema and no top-level `source_condition` field. The snapshot preserves its nested exact-clone/Root058 QA and Source064 prepared report/XML roles, and records the registered XMF condition-template metadata fallback explicitly. Its old typed154 receipt remains `running` with no returncode; Root1166’s independent artifact audit is a separate completed/0 role and is not retroactively substituted into the old receipt.
- Typed/XMF scope is recorded separately from native canonical condition and source condition template. For P1200 AY0390 and AY0430, the XMF source-plan key is present but its recorded value matches neither that row’s native condition nor its source-condition template; this is retained as a provenance discrepancy for Root review. For P1200 AY0540/0570/0640, the source-plan key is present and matches the source-condition template while remaining distinct from the native/actual converter scope.
- All nine typed lifecycle summaries record zero transient missing frames, zero missing MK/type events, empty first-missing maps, and zero initial exclusions. The AY0270 audit separately records zero UID lifecycle missing count and 835 checked transitions. The package records metadata attestations only; it does not recompute payload hashes.
- For P0800 AY0360/0500/0570 the registered outer render envelope still says 801 frames / 194427 particles / 34 contacts, while the loaded wrapper bound to the completed XMF says 836 / 179208 / 35. The loaded wrapper is the actual contract; the stale outer envelope is retained and explicitly marked.
- Every controller was live with an exact PID/start-tick match at the snapshot and had no terminal render receipt/publish evidence. No visual decision is made here; no PNG bytes were read.

Run the read-only validator with:

```sh
python3 scripts/validate_fresh166.py
```
