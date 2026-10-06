# F6 fresh121 delegated visual review of two Root715 F4 cases

This source-only sidecar records the next two Root715 renderer attempts that have actual
`completed`/return-code `0` receipts and complete 1201-frame reports, after excluding
checkpoint 108 and the previously integrated delegated batches through fresh120/Root846:

- `F4_DROP_gap0p20000_xoff0p08000_yoff0p04000_uz0p40000`
- `F4_DROP_gap0p20000_xoff0p08000_yoffm0p04000_uz0p40000`

I used `view_image` on every `all_frames_000.png` through `all_frames_050.png` and on
key frames 0, 150, 300, 450, 600, 750, 900, 1050, and 1200 for each case. Both
chronologies retain the full tank and wall outline while showing the drop, impact/splash,
redistribution, and late-time residual wave. No obvious camera clipping or abrupt
geometry disappearance was visible in the reviewed artifacts.

The render reports are producer artifacts with `frames=1201`, `source_frames=1201`,
`all_frames_rendered=true`, preserved actual times, native identity axis, and zero
nonfinite active states. Their stale title remains `VISUAL REVIEW PENDING ROOT` and
`PRECISION NOT ACCEPTED`; this review retains that boundary and makes no Q-N, Q-E,
precision, convergence, production, or global accepted-count claim. It also makes no
claim that Root personally inspected these images.

The second case has producer lifecycle metadata with 25 transient missing-frame events,
first missing frame 1176, and a maximum of 3 missing particles in a single frame. The
package keeps transient events, per-frame maximum, and final UID status separate; it
does not infer UID survival from images. The first case reports zero such events.

The third Root715 request, `F4_DROP_gap0p20000_xoff0p08000_yoff0p04000_uz0p60000`, is preserved in
`metadata/accepted-source-snapshot.json` as excluded because shared CPU reservation was
exceeded before a renderer artifact was produced. That is a scheduling/resource outcome,
not a scientific visual rejection.

The read-only Root773 controller diagnosis is in
`metadata/root773-controller-diagnosis.json`. Its result reports 24 requested, 2 completed
with return code 0, and 21 held. The first and only explicit failed case is the excluded
`uz0p60000` case: its producer receipt records `RuntimeError: shared CPU thread reservation
exceeded`, zero GPU seconds, zero output bytes, no start time, no stdout digest, and no
`render/` directory. Therefore the pvpython renderer did not start; the other 21 cases have
no case-specific failure reason in the Root773 result and remain held. Root773 and Root774
were not restarted or modified.

All actual converter, Root715 source-binding, source-owner, and source-plan condition
scopes are recorded separately. Scientific H5/BI4/CSV/VTK/DAT payloads were not read,
copied, or hashed by this review. No shared state, ledger, solver, or renderer job was
started.

Validate the package with:

```text
python3 workers/validate_fresh121.py
```
