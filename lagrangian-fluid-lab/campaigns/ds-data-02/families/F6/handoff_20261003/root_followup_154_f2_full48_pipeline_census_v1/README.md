# F6 fresh154: F2 first48 pipeline census

This is a frozen, metadata-only census for the 24 F2 first48 expansion conditions. It was captured at the timestamp in `metadata/f2-first48-census.json` from the Root checkpoint, the existing fresh140/fresh142 owner packages, F2 execution receipts, and the Root handoff registration metadata.

The checkpoint snapshot has 29 accepted F2 physical IDs. The first48 set has 5 accepted and 19 still unaccepted. At this snapshot all 24 GenCase, initial-QA, and full401 native receipts are completed/0. Typed157 is 23 completed/0 and one missing. Normal N3 XMF is 21 completed/0, one registered live, and two missing. Render registration is two completed/0, thirteen live, and nine missing; live registrations remain pending and are not treated as failures or credit.

The five bounded actionable gaps are:

- `RX061/ROT075`: XMF 1118 is completed/0 with no render registration.
- `RX061/ROT105`: typed157 is completed/0 with no XMF registration.
- `RX063/ROT075`: XMF 1116 is completed/0 with no render registration.
- `RX063/ROT090`: XMF 1117 is completed/0 with no render registration.
- `RX063/ROT105`: native and initial-QA are completed/0, but typed157 and XMF have no terminal producer/registration.

`RX058/ROT075` has a live existing XMF registration and is explicitly deferred. The supplied Root registrations 1119 (`RX061/ROT090`) and 1120 (`RX058/ROT105`) are retained as live registrations; fresh154 does not duplicate them. The selected gap rows contain exact native/typed/XMF receipt or metadata paths and owner scope references. Source-plan, canonical-owner, and actual converter scopes remain separate; missing future producer scope remains null.

Run the bounded validator with:

```text
python3 scripts/validate_fresh154.py
```

`build_fresh154_snapshot.py` is a read-only snapshot builder for Root review. It only opens explicitly named JSON metadata, receipt/config files, and owner JSON; it does not open or hash BI4/H5/CSV/DAT/VTK payloads and never launches a task. Re-running it creates a new live snapshot and should not overwrite this frozen handoff without a new fresh ID.

This package does not start jobs, mutate shared state, grant visual/Q-N/production credit, or change the F2 source packages. Resource limits and global scheduling remain Root-owned.
