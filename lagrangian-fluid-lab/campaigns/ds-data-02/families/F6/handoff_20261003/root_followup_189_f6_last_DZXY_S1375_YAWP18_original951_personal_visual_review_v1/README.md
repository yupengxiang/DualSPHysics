# F6 fresh189 — final DZXY S1375/YAWP18 Root951 personal visual review

This package records the delegated personal visual review of the already completed and atomically published Root951 full241 product for `F6_STAGE1_ANGULAR_RELEASE_DZXY_S1375_YAWP18_DP025`. The same renderer was observed until its terminal `completed/0` receipt and atomic publish; no render, solver, or scientific payload job was restarted.

I viewed all 11 chronological contact sheets (`all_frames_000.png` through `all_frames_010.png`) and all 10 requested keys (`0, 1, 30, 60, 90, 120, 150, 180, 210, 240`) with `view_image`. Frame 1 is separately recorded for the initial angular-response screen. The images show the gray fixed enclosure, blue fluid, and red floating body. Early wave/body interaction and later attitude/surface evolution are visually discernible. No obvious gross clipping, catastrophic scatter, severe visible penetration, blank interval, or premature termination was seen.

Producer metadata remains authoritative: 241 states, initial total 417505 (`fixed=73441`, `floating=16384`, `moving=0`, `fluid=327680`), terminal total 417502 with three missing fluid UIDs. The first missing frame is 7, 234 frames contain omissions, and cumulative particle-frame omissions are 700; location/state/cause are unknown. This review does not infer omega from particle V0, certify strict containment or numerical precision, or grant Q-N/Q-E or case credit.

Scope roles remain separate: native canonical `13c383a2ba67e520613cacb83f595a1c0745b2ac8ad2c67c9c6beaf43a6e4640`, typed/XMF legacy producer scope `a92da26df8424649239124012c23f1f893327573a302dc6914e962ceec5a0d90`, and existing source-plan condition `c503e879744b5f3e533ebf193b888d7cea57c3cf8a3e0a5c64a831ba8013fc41`. The source-plan physical-condition field is absent/null in both native and XMF namespaces. Physical mass is 128 kg and native support mass is 256 kg; no rescaling/equality claim is made.

Run the read-only validator:

```sh
python3 scripts/validate_fresh189.py
```

It hashes only JSON/XML metadata and compares published PNG paths/sizes against the producer publish receipt. It does not open or hash scientific H5/BI4/CSV/DAT/VTK payloads and never starts work.
