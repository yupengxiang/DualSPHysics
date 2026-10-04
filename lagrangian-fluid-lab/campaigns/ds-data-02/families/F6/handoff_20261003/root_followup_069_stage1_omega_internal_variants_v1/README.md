# F6 fresh069 first-eight angular-release source variants

The frozen original mother F6_ANGULAR_RELEASE_DP025 was verified at true scale 1.00 with angularvelini=(0.08,0.12,0.06), dp=0.025, TimeMax=12, and TimeOut=0.05. Its source hash is 9a052a620be27668ca5b8f42b0b91f2280a5b85588a94ccf845fb46905d258ba. The first eight are the original mother, existing S025/S200 endpoints, and new scales 0.50, 0.75, 1.25, 1.50, 1.75 (F6_STAGE1_ANGULAR_RELEASE_OMEGA_S050_DP025, F6_STAGE1_ANGULAR_RELEASE_OMEGA_S075_DP025, F6_STAGE1_ANGULAR_RELEASE_OMEGA_S125_DP025, F6_STAGE1_ANGULAR_RELEASE_OMEGA_S150_DP025, F6_STAGE1_ANGULAR_RELEASE_OMEGA_S175_DP025).

Run only the source builder when preparing source files: python3 builders/build_f6_omega_internal_variants.py --package-root . . It edits line 64 x/y/z only. The disabled requests are under gencase, qa, floatinginfo, and qualification. They preserve the mother solver recipe -tmax:12 -tout:0.05, all six DOF, DP .025, 241 native frames, and no extra DBC, forcing, time, CPU, or mass options.

Expected native contract: total 417505, fluid 327680, fixed 73441, floating 16384, true 3D, floating mk 60/type 2, center [2.4,1.2,1.08], physical mass 128 kg, native support 256 kg, masspart 0.015625 kg. No mass equality or rescale is applied. FloatingInfo state0 must corroborate each case-specific omega; particle V0=0 cannot prove no angular speed.

No numerical job, GenCase, PartVTK, FloatingInfo, conversion, BI4, H5, CSV array, or recursive task was run. Existing endpoints are native-complete but pending visual review; scale coverage is prospective and grants no Q-N or production approval. Historical QA019 and semantic020 remain unchanged. F3 .64 normal typed inspection is pending in its own work and is not a blocker for this F6 source package.
