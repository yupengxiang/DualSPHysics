# DS-DATA-02 fresh150 cross-family membership audit

This F3-scoped package checks the explicit first8 and first24 membership records for F1, F4, and F7 against the 48 accepted decisions in Root checkpoint 192. It uses frozen JSON/source-plan metadata and preserves the source, native, converter/legacy, and accepted-decision roles separately. It does not sort names to manufacture a subset.

Findings:

- **F1:** certified. Root299’s eight actual case IDs are in the preserved first24 case IDs, and the fresh091 24+24 union matches the 48 accepted checkpoint case IDs. The source `physical_case_id` aliases remain alongside the accepted decision IDs.
- **F4:** partial with a real gap. The frozen current exact24 physical IDs are in the 48 accepted checkpoint physical IDs. The historical root_followup_053 eight-row batch explicitly has count increment 0 and is excluded from the current target, so there is no authoritative first8-to-first24 mapping. No subset is invented.
- **F7:** certified. The first8 angle plan, first24 angle plan, and root_followup_079 48-case inventory use explicit physical IDs; the 48-case inventory matches the 48 accepted checkpoint physical IDs. The 45-degree coarse/base alias is retained.

All guards are metadata-only: no BI4/H5/CSV/DAT/VTK/XMF/image payload was opened or hashed, no job was started, no shared index/ledger was changed, and this package grants no visual, precision, Q-N, or production credit.

Validate with:

```text
python3 scripts/validate_fresh150.py
```
