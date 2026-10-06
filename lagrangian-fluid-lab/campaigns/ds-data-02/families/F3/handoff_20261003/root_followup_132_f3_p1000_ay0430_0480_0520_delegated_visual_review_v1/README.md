# fresh132 — F3 P1000 delegated visual review

This source-only package records the delegated visual review of `AY0430`, `AY0480`, and `AY0520`. CP150 was checked by case ID, manifest physical ID, census physical ID, and canonical source scope. The three selected cases were outside the accepted set; fresh129 (`AY0290`, `AY0300`), fresh130 (`AY0360`, `AY0370`, `AY0410`), fresh131 (`P0800 AY0320`), and the P1000 mother aliases were excluded before review.

Each selected case has a completed native→typed→normal XMF→full836 render chain. Every 35 chronological contact sheet and six full-size keyframes (`0, 260, 360, 430, 610, 835`) was inspected with `view_image`. The decisions record visual continuity only. They do not grant numerical precision, Q-N/Q-E, production scope, or a 2-D range. Canonical native/source physical hashes remain separate from the converter `legacy-owner-scope.v0` hashes. Genuine GenCase 056, initial QA 058, and the forcing producer before/after digest metadata are retained as provenance; no source agent opened or hashed BI4/H5/CSV/DAT/VTK payloads.

The package contains metadata and PNG hash sidecars only. It starts no task, writes no shared state, and leaves global count updates to Root. `source_review_commit` in each decision points to the fresh132 source-review provenance commit `2d903e18783b8b8ea2e6a50e5c0ece46e78faac4`; the final package commit is reported separately after validation.

Validation:

```text
PYTHONDONTWRITEBYTECODE=1 python3 scripts/validate_fresh132.py
```
