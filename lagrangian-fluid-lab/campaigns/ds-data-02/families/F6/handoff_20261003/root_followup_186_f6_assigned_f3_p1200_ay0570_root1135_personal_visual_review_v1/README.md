# fresh186 — delegated F3 P1200/AY0570 visual review

- Reviewer: `/root/f6_endpoint_initial_qa` using GPT-5.6-Luna/max.
- Assigned handoff family: **F6**. Actual physical/simulation family: **F3**.
- Case: `F3_STAGE1_DP006_P1200_AY0570`; physical case: `F3_TWOAXIS_P1200_AY0570_STAGE1_FIRST48_PITCH_VARIANT`.
- Decision: `visual-approved-by-delegated-agent`; `case_credit=0`, `Q-N=false`, `Q-E=false`. Parent/root integration remains required.
- Actual Root1135 render: completed/0 and atomically published; 836 frames over `[0.0, 8.350016793948717]` seconds, 35 contact sheets, 9 selected key frames.

## Personal visual result

All 35 contact sheets and key frames 0, 100, 200, 300, 400, 500, 600, 700, and 835 were viewed with `view_image`. The sequence shows a populated fixed-boundary and fluid field, wave/free-surface development, propagation/reflection/re-distribution, and late boundary-side crest activity. The metadata says fixed=111708, fluid=67500, moving=0, floating=0, so the visual mechanism is described as fluid/boundary evolution; no moving or floating-body mechanism is claimed.

No obvious scene-wide empty frame, premature termination, catastrophic explosion, or gross camera crop was seen. The high late crest near the right boundary remains within the rendered view. PNG inspection cannot prove local particle containment, conservation, numerical precision, or physical correctness.

## Evidence and scopes

`manifest.json` contains every viewed PNG path, byte count, local SHA256, and matching publish-receipt SHA. It also binds the actual GenCase/initial-QA/native/typed/XMF/render chain through JSON/XML/XMF metadata and the Root1325 QI proof. Native canonical and actual-converter scope are `e60d60e67cd9204546436c4947de01c774d003045b3cd421de16beec2b79b5a7`. Native source-plan condition and physical-condition fields are absent/null. XMF has source-plan condition `e61cb7352047037b91f4be0cd22379375980b5b51592a8e516608ea2d3b27aa9` in its own namespace; XMF source-plan physical-condition is absent/null. No absent field is filled from another namespace.

The package and validator do not open or hash H5, BI4, CSV, DAT, or VTK scientific payloads. Run:

```sh
python3 scripts/validate_fresh186.py
```
