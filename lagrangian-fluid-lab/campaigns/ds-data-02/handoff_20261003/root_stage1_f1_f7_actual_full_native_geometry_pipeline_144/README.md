# Root144 F1/F7 native geometry render handoff

Prepared in /tmp/ds02-root144-render-source only. No solver, GenCase, converter, ParaView render, BI4/H5/CSV array read, shared-registry write, or source-worktree mutation was performed.

The mature renderer is Root023 render.py (sha256 5e78f7b92ad7c6f1d15902e3ccacc9099affb04b1b992a42f540eb88241bde66). Its full run uses ParaView 6.1.1 pvpython --force-offscreen-rendering with software llvmpipe variables. It scans valid native positions at every saved XDMF time for camera bounds, keeps the XDMF reader unmasked, applies only display cutaway filters, preserves native fluid/fixed/moving/floating fields, and emits every saved frame. With 24 tiles per contact sheet this yields 17 pages for 401 frames and 26 pages for 601 frames.

## Actual dependencies

- F1 DUAL260 Root141 normal XMF: completed/0; manifest SHA 9a577d67...008ae3a, XMF SHA 16ce8e33...465100, receipt SHA f775cad8...030064f.
- F7 A030 Root141 normal XMF: completed/0; manifest SHA 6b1ae8ed...e3d3a7, XMF SHA bda243bd...aa4b7b, receipt SHA 84834d69...b6c490.
- F7 A065 typed conversion/native solver are actual completed inputs. Its conversion report binds H5 hash_scopes.physical_condition_sha256 to canonical 5812777b...e7fb0; source-plan 7694c57f...b8600 remains a separate source scope. A065 normal XMF was not started, so its normal-XMF and render requests remain disabled with all future output hashes null.

## Files for Root

- F1_STAGE1_DUAL_H260_DP020-render-request.json
- F7_OBSTACLE_QUINTIC_B08_A030-render-request.json
- F7_OBSTACLE_QUINTIC_B08_A065-xmf-binding.json
- F7_OBSTACLE_QUINTIC_B08_A065-normal-xmf-request.json
- F7_OBSTACLE_QUINTIC_B08_A065-render-request.json
- review-contract.json

All three render requests have launch_allowed: false, root_review_required: true, independent_case_count_increment: 0, and no precision/Q-N claim. Root can enable the two actual-XMF requests after review. For A065, first enable the normal-XMF request, record its actual completed/0 receipt, manifest, and XMF SHA values, then fill only the three future nulls in the render request and enable it. Root142 policy evidence is carried by hash and remains untouched.
