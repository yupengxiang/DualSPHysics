# F2 H2 mDBC static range v5 CPU preflight

Date: 2026-09-20  
Scope: `F2_H2_mdbc_static_range_qualification_v5`  
Mode: CPU GenCase plus native `bi4_dump` decode only

The independent versioned materializer in `scripts/f2_h2_mdbc_static_range_v5_prepare.py` reads the v5 candidate card and applies its top-layer lateral lattice rule while reusing only the v4 conversion and native preflight plumbing. The v4/v1/v2 preparer is unchanged. The v5 plan is recorded in `campaigns/core-v1/cfd/f2-h2-mdbc-static-range-qualification-v5/v5-plan-20260920-final.json`, and the full materialization report is `campaigns/core-v1/cfd/f2-h2-mdbc-static-range-qualification-v5/prepared-20260920-v5-all/matrix-preparation.json`.

All 15 registered rows were materialized and passed CPU/native preflight (15 prepared, 0 failed, 0 unattempted). The fixed denominator remains 15, with the retained v4 cell-11 negative result recorded separately. The candidate remains `qualification_only=true`, `qualified=false`, and `T1_numerical=false`; no qualification credit is assigned.

For cell 11 (`q=0.75`, `dp=0.0075`), the generated Definition uses source-layer counts `[43,29,15]`, `[43,29,15]`, and `[42,29,16]`. The generated native XML reports fluid group counts `18705`, `18705`, and `19488`. The third source layer has relative mass error `0.004152671755724757`, compared with the retained v4 value `0.02806106870228997`; the decoded total native mass error is `0.0036100658513640305`. Native mDBC normals match the 319608 boundary particles, with zero zero-length normals.

The mass policy is native `rho*dp^3` with no rescaling. The report records solver, GPU, queue, ledger, and registry actions as false/zero. No solver binary was read or hashed, and no solver, GPU, queue, registry, or ledger operation was performed.

Validation: `./.venv/bin/python -m pytest -q tests/test_f2_h2_mdbc_static_range_prepare.py tests/test_f2_h2_mdbc_static_range_v5_prepare.py` → 4 passed.
