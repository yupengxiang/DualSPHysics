# F6 fresh100: Root607 typed -> Root658 H5 audit -> N3 XDMF -> Root023 render

This is a source-only F6 handoff. It contains the Root-approved `export_xmf.py` N3 writer
(the dynamic vector contract is `outshape = shape[1:]`, therefore `417505 3`) and the
Root023 renderer. It does not contain or read a BI4, H5, CSV, or motion payload.

At package creation, all 24 Root607 typed producer reports and receipts were metadata-verified
as `completed/0`, 241 frames, 417505 particles, solver dimension 3, and PartVTK
`all_passed=true`. Root658 audit metadata was bound per case. The package snapshot records 24 terminal Root658 audit passes after Root659 completion: F6_STAGE1_ANGULAR_RELEASE_DXYZ_S0375_YAWM12_DP025, F6_STAGE1_ANGULAR_RELEASE_DXYZ_S0625_YAWM06_DP025, F6_STAGE1_ANGULAR_RELEASE_DXYZ_S0875_YAWP06_DP025, F6_STAGE1_ANGULAR_RELEASE_DXYZ_S1125_YAWP12_DP025, F6_STAGE1_ANGULAR_RELEASE_DXYZ_S1375_YAWP18_DP025, F6_STAGE1_ANGULAR_RELEASE_DXYZ_S1625_YAWM18_DP025, F6_STAGE1_ANGULAR_RELEASE_DYXZ_S0375_YAWM12_DP025, F6_STAGE1_ANGULAR_RELEASE_DYXZ_S0625_YAWM06_DP025, F6_STAGE1_ANGULAR_RELEASE_DYXZ_S0875_YAWP06_DP025, F6_STAGE1_ANGULAR_RELEASE_DYXZ_S1125_YAWP12_DP025, F6_STAGE1_ANGULAR_RELEASE_DYXZ_S1375_YAWP18_DP025, F6_STAGE1_ANGULAR_RELEASE_DYXZ_S1625_YAWM18_DP025, F6_STAGE1_ANGULAR_RELEASE_DYZX_S0375_YAWM12_DP025, F6_STAGE1_ANGULAR_RELEASE_DYZX_S0625_YAWM06_DP025, F6_STAGE1_ANGULAR_RELEASE_DYZX_S0875_YAWP06_DP025, F6_STAGE1_ANGULAR_RELEASE_DYZX_S1125_YAWP12_DP025, F6_STAGE1_ANGULAR_RELEASE_DYZX_S1375_YAWP18_DP025, F6_STAGE1_ANGULAR_RELEASE_DYZX_S1625_YAWM18_DP025, F6_STAGE1_ANGULAR_RELEASE_DZXY_S0375_YAWM12_DP025, F6_STAGE1_ANGULAR_RELEASE_DZXY_S0625_YAWM06_DP025, F6_STAGE1_ANGULAR_RELEASE_DZXY_S0875_YAWP06_DP025, F6_STAGE1_ANGULAR_RELEASE_DZXY_S1125_YAWP12_DP025, F6_STAGE1_ANGULAR_RELEASE_DZXY_S1375_YAWP18_DP025, F6_STAGE1_ANGULAR_RELEASE_DZXY_S1625_YAWM18_DP025.
Each case retains its own terminal Root658 report/receipt paths and metadata SHA256 values. The source package hashes only these JSON metadata files; it never independently hashes the H5 payload.

The producer physical scope comes from each actual Root607 conversion report. Root606
classified-owner scope, fresh088 canonical-owner scope, and source-plan hashes remain
separate provenance fields. The source package does not independently hash the H5 payload;
the producer output digest is recorded only as an attestation from the JSON report.

## Root enable order

1. Run `python3 workers/validate_fresh100_source.py` from this package directory.
2. For a case whose `audit658_dependency.status` is `actual_root658_pass`, Root may create
   a strict enabled clone of `requests/xmf/<case>-root-xmf-request.json`, keeping its own
   input hashes and using a new empty `{attempt_root}/xdmf` child. Use Root142 CPU audit
   policy, one case first, then at most two conversion/audit slots as scheduled by Root.
3. After that case's XMF receipt and manifest are actual, Root may enable its paired render
   request. The render command uses Root023, automatic all-native bounds over all 241 saved
   frames, software offscreen ParaView, OMP/BLAS/VTK/LP limits of 2, and `MESA_GLTHREAD=false`.

All XMF and render outputs, receipts, manifests, and SHA256 values remain `null` in this
source package. The package grants no visual, Q-N, precision, or production credit.
