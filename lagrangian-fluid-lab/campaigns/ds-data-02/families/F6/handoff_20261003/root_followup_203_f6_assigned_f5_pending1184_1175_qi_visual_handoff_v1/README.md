# fresh203 F5 original-render QI/visual handoff

This F6-scoped package records the two registered original F5 renderers from a verified live `/proc` preflight at `2026-10-07T11:26:27.488439+00:00`. It binds each case's actual native, GenCase, initial-placement QA, typed conversion, XMF, bed, source-definition and plan metadata. The mother alias remains separate from the unique physical case ID.

Both cases are 801 frames, 194427 particles, 3-D, and nominal `[0, 16] s`. Producer metadata records the actual terminal times independently: M095/T090 ends at `16.00009662908174 s`; M104/T085 records `16.00008833590506 s`. The package does not resample or replace either value with nominal `16.0`.

M095/T090 (render 1184) naturally reached execution `completed`/returncode `0` after the verified live preflight and has an atomic full-animation report and publish receipt. Its render status is therefore terminal/published, while root-owned full801 QI and personal 34-contact/9-key review remain pending. M104/T085 (render 1175) still has a matched live controller PID/start tick and a mutable execution receipt with status `running`; it has no terminal report or publish receipt in this snapshot. A later M104 terminal state must be a new immutable handoff. The final PID absence for M095 is recorded as natural termination after the matched preflight, never as a relaunch.

M095 keeps native canonical `88e4d21325c19591188a5ebea6041ff0e26ccd18ccc09860bdfea7271cadc167` separate from typed legacy `48385908daea6f6acc49f4b9b609c88fe5f69f121c4c53c1ca920df9b59ac71e`; its native request has both `source_plan_*` fields absent, while the XMF manifest separately records the SourceDef physical-plan hash `fc5f044b657f1cd02a9375b74a20ba0496a94e80410a61f71884f7ed8dcec28f`. M104 keeps native canonical `ec4a1681e7e516fbebe9eba20e24981eac564e61bec9408dbccde2239e4d6e91` separate from typed legacy `726fc15f5ac66ee242de95fd22e06a98dc7c5400a196dd8d5612b5b17e701d5a`; its native and XMF physical-plan roles are canonical and the source-definition XML remains a separate `d05391749f5b2446968f7f34f613e13286c5bf5263207dfbe16ba84f256e61c8` reference. Each own bed execution receipt/report/frozen progress/lineage and each real GenCase and initial-QA receipt are explicit metadata references; absent fields remain absent.

Validation is metadata-only:

```text
python3 scripts/validate_fresh203.py
```

The validator hashes only JSON/XML/XMF/code metadata refs explicitly marked `metadata_file`. The currently running M104 receipt is marked `metadata_live_snapshot`, so a later producer rewrite is not mistaken for corruption of this immutable observation. Producer-attested H5 refs are recorded without reading or hashing them. Case credit, Q-N, Q-E and numerical precision acceptance remain zero/false; the source agent did not run QI or view PNGs.
