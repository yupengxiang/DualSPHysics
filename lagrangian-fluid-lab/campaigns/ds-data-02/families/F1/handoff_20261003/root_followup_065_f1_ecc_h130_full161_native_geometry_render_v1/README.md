# F1 H130 full-native geometry render handoff

This is a source-only handoff for the existing physical condition
`F1_STAGE1_ECC_H130_DP010` (`F1_ECC_HEAD_130_UNCHANGED_MOTHER_GEOMETRY_V1`).
It binds Root121's normal 161-frame temporal product to the reviewed native
renderer proxy at SHA256
`5e78f7b92ad7c6f1d15902e3ccacc9099affb04b1b992a42f540eb88241bde66`.

The checked-in `metadata/source-plan.json` and its pending request deliberately
keep the future XMF digest `null`.  After Root121 is completed, the same
metadata-only builder can verify the Root121 receipt and bind the completed
XMF digest:

```text
python3 build_f1_ecc_h130_native_render.py --mode plan
python3 build_f1_ecc_h130_native_render.py --mode bind
```

The current bound candidate records the completed XMF digest
`1ce812924d4281d11524ee55128edeee9de04990529c9e54747eb6550fc21d07` and
emits a disabled request.  `launch_allowed` remains `false`; Root must review
and authorize it separately.  The request is full native geometry over all 161
saved frames, producing seven renderer contact-sheet keys
`all_frames_000` through `all_frames_006`, the full saved GIF, PVSM state, and
the renderer report.  Camera bounds are discovered from all native valid
frames (`auto-all-frame-nativebounds`), and the fixed-boundary cutaway is the
renderer’s display-only `actualfixedcutaway`; no source or camera crop is
introduced.

The builder validates the frozen H130 owner, Root094 native receipt, typed063
receipt/conversion metadata, Root121 JSON metadata, and renderer source hash.
It only reads small metadata/XML files in bind mode.  It never opens the
trajectory H5, reads numeric arrays, launches ParaView, modifies the shared
registry/ledger, or makes a visual, precision, or case-count claim.
