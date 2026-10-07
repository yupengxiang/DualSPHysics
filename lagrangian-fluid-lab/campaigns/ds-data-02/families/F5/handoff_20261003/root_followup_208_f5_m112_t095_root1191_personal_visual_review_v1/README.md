# F5 M112/T095 Root1191 personal visual review

This source-only handoff records the F5 personal review of the completed and atomically published full801 render for `F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M112_T095_NEXT34` / `F5_COMPACT_RUNUP_RECOVERY_C082S1_M112_T095`.

Root1191 completed with return code 0 and published 801 saved states. I viewed all 34 published contact sheets (`all_frames_000.png` through `all_frames_033.png`) and all 9 published keyframes (`frame_0000.png`, `0100`, `0200`, `0300`, `0400`, `0500`, `0600`, `0700`, `0800`). The views show a coherent, stable event with a weak/limited visible response. No gross explosion, abrupt termination, or broad visible escape was seen; no large runup or inundation claim is made.

The actual Root1332 QI records 194427 particles (158559 fixed, 4210 moving, 31658 fluid, 0 floating), 3-D data, 801 states, active UIDs, finite fields, exact saved times, and full-frame bed diagnostics. The bed report remains diagnostic-only and pending Root review. Zero 1DP/2DP bins are not a sub-DP or precision certificate.

Namespace roles are preserved exactly. Native source-plan condition and physical-plan fields are present with canonical `f0d480ec9e75c70daea8aca22dc155e7e62fa5dcd1a37a65699a000f31c416ca`. XMF source-plan condition is absent, while XMF physical-plan is present with the registered SourceDef value `92b9e7c7e80bbe1e0239dd3487923452e77af3d265fa6dc7794f8b3edcebaf97`. The typed/H5 legacy scope is `f7feb75534a3f33cac3d1fd906733dc231ccb63fd430bffe3e9184c6e92f484f` and remains a separate legacy-owner scope. No scope is substituted or declared equal across roles.

Numerical precision remains unaccepted; historical A/B and exact-lattice negatives remain retained. This handoff grants no Q-N/Q-E or case credit.

Run the metadata-only validator with:

```text
python3 scripts/validate_fresh208.py
```

The source agent read only published PNG derivatives for visual review and metadata JSON/XML. It did not read or hash H5/BI4/CSV/DAT/VTK payloads, copy payloads, start a scientific job, or write shared state. PNG hashes are producer-attested values copied from the publish receipt.
